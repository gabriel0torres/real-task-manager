"""OS-level process handling: building the command line, spawning, killing trees."""

from __future__ import annotations

import contextlib
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

import psutil

from rts.models.enums import Shell

IS_WINDOWS = os.name == "nt"

_EXTENSIONS = {
    Shell.BASH: ".sh",
    Shell.SH: ".sh",
    Shell.CMD: ".cmd",
    Shell.POWERSHELL: ".ps1",
    Shell.PWSH: ".ps1",
    Shell.PYTHON: ".py",
}

_PS_FLAGS = ["-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File"]


class SpawnError(RuntimeError):
    """The process could not be started (message is user-facing, pt-BR)."""


def default_shell() -> Shell:
    if IS_WINDOWS:
        return Shell.CMD
    return Shell.BASH if shutil.which("bash") else Shell.SH


def _resolve(executable: str) -> str:
    path = shutil.which(executable)
    if path is None:
        raise SpawnError(f"Interpretador '{executable}' não encontrado no servidor.")
    return path


def prepare_command(shell: Shell | None, command: str, script_dir: Path) -> list[str]:
    """Write the task command to a script file and return the argv to execute it."""
    shell = shell or default_shell()
    script_dir.mkdir(parents=True, exist_ok=True)
    script = script_dir / f"script{_EXTENSIONS[shell]}"
    text = command.replace("\r\n", "\n")
    encoding = "utf-8"
    if shell is Shell.CMD:
        text = "@echo off\r\n" + text.replace("\n", "\r\n")
    elif shell in (Shell.POWERSHELL, Shell.PWSH):
        encoding = "utf-8-sig"  # Windows PowerShell needs the BOM to read UTF-8
    script.write_text(text, encoding=encoding, newline="")

    match shell:
        case Shell.BASH:
            return [_resolve("bash"), str(script)]
        case Shell.SH:
            return [_resolve("sh"), str(script)]
        case Shell.CMD:
            return [_resolve("cmd"), "/d", "/c", str(script)]
        case Shell.POWERSHELL:
            return [_resolve("powershell"), *_PS_FLAGS, str(script)]
        case Shell.PWSH:
            return [_resolve("pwsh"), *_PS_FLAGS, str(script)]
        case Shell.PYTHON:
            # The RTS interpreter: always present and predictable.
            return [sys.executable, "-u", str(script)]
    raise SpawnError(f"Shell não suportado: {shell}")  # pragma: no cover


def spawn(argv: list[str], cwd: Path, env: dict[str, str]) -> subprocess.Popen[bytes]:
    kwargs: dict = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "cwd": str(cwd),
        "env": env,
    }
    if IS_WINDOWS:
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    else:
        # Own process group so the whole tree can be signalled at once.
        kwargs["start_new_session"] = True
    try:
        return subprocess.Popen(argv, **kwargs)
    except OSError as exc:
        raise SpawnError(f"Falha ao iniciar o processo: {exc}") from exc


def _signal_group(pid: int, sig: int) -> None:
    if not IS_WINDOWS:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(pid, sig)


def kill_tree(pid: int, grace_seconds: float = 5.0) -> None:
    """Terminate a process and all its descendants (graceful, then forced)."""
    try:
        parent = psutil.Process(pid)
        procs = [*parent.children(recursive=True), parent]
    except psutil.Error:
        procs = []

    _signal_group(pid, signal.SIGTERM)
    for proc in procs:
        with contextlib.suppress(psutil.Error):
            proc.terminate()
    _gone, alive = psutil.wait_procs(procs, timeout=grace_seconds)

    if not IS_WINDOWS:
        _signal_group(pid, signal.SIGKILL)
    for proc in alive:
        with contextlib.suppress(psutil.Error):
            proc.kill()
    psutil.wait_procs(alive, timeout=grace_seconds)


def pid_alive(pid: int) -> bool:
    try:
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except psutil.Error:
        return False
