"""Runs a single task execution: spawn, stream logs, timeout, cancel, finalize, retry."""

from __future__ import annotations

import logging
import os
import queue
import shutil
import threading
import time
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import IO

from rts.engine.context import EngineContext
from rts.engine.logwriter import LogWriter
from rts.engine.process import (
    FROZEN,
    SpawnError,
    default_shell,
    kill_tree,
    prepare_command,
    spawn,
)
from rts.models import LogStream, Run, RunStatus, RunTrigger
from rts.security.crypto import SecretDecryptError
from rts.security.masking import SecretMasker
from rts.services.runs import append_system_log, create_run
from rts.services.variables import build_task_environment

log = logging.getLogger(__name__)

TRIGGER_LABELS = {
    RunTrigger.SCHEDULED: "agendado",
    RunTrigger.MANUAL: "manual",
    RunTrigger.RETRY: "nova tentativa",
    RunTrigger.API: "API",
}
STATUS_LABELS = {
    RunStatus.SUCCESS: "sucesso",
    RunStatus.FAILED: "falha",
    RunStatus.TIMEOUT: "tempo esgotado",
    RunStatus.CANCELLED: "cancelada",
}


class PreconditionError(Exception):
    """Configuration problem detected before the process starts (no retry)."""


@dataclass
class _Plan:
    argv: list[str]
    cwd: Path
    env: dict[str, str]
    timeout: int | None
    script_dir: Path


def _child_base_env() -> dict[str, str]:
    # Never leak the RTS configuration (secret key, database URL...) to tasks.
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("RTS_")}
    if FROZEN:
        # PyInstaller points the library path at its bundle; give tasks the original one.
        for var in ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH"):
            original = env.pop(f"{var}_ORIG", None)
            env.pop(var, None)
            if original:
                env[var] = original
        for key in [k for k in env if k.startswith(("_PYI_", "_MEI"))]:
            env.pop(key)
    env["PYTHONUNBUFFERED"] = "1"
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


def _fallback_encoding() -> str:
    """Encoding of console programs that don't write UTF-8.

    On Windows, cmd and most native tools write in the OEM code page (cp850 on a
    Portuguese system), so "versão" would otherwise show up as "vers�o".
    """
    if os.name == "nt":
        try:
            import ctypes

            return f"cp{ctypes.windll.kernel32.GetOEMCP()}"
        except Exception:  # pragma: no cover
            return "cp850"
    return "latin-1"


FALLBACK_ENCODING = _fallback_encoding()


def decode_line(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode(FALLBACK_ENCODING, errors="replace")


def _reader(pipe: IO[bytes], stream: LogStream, out: queue.Queue) -> None:
    try:
        for raw in iter(lambda: pipe.readline(8192), b""):
            out.put((stream, decode_line(raw)))
    except (OSError, ValueError):  # pipe closed underneath us
        pass
    finally:
        out.put((stream, None))


class RunExecutor:
    cancel_poll_seconds = 1.0
    flush_interval_seconds = 0.5
    pipe_drain_grace_seconds = 5.0
    kill_grace_seconds = 5.0

    def __init__(self, ctx: EngineContext, run_id: int) -> None:
        self.ctx = ctx
        self.run_id = run_id
        self._interrupt = threading.Event()
        self._interrupt_reason = ""
        self._writer: LogWriter | None = None

    # ------------------------------------------------------------------ public
    def interrupt(self, reason: str) -> None:
        """Stop the run from the engine (e.g. worker shutdown); ends as FAILED."""
        self._interrupt_reason = reason
        self._interrupt.set()

    def execute(self) -> RunStatus:
        try:
            plan = self._prepare()
        except PreconditionError as exc:
            return self._finalize(RunStatus.FAILED, str(exc), retry=False)
        except Exception as exc:  # pragma: no cover - defensive
            log.exception("Run %s: preparation failed", self.run_id)
            return self._finalize(RunStatus.FAILED, f"Erro interno do RTS: {exc}", retry=False)
        try:
            return self._run(plan)
        except Exception as exc:  # pragma: no cover - defensive
            log.exception("Run %s: execution failed", self.run_id)
            return self._finalize(RunStatus.FAILED, f"Erro interno do RTS: {exc}", retry=False)
        finally:
            shutil.rmtree(plan.script_dir, ignore_errors=True)

    # ------------------------------------------------------------------ steps
    def _prepare(self) -> _Plan:
        settings = self.ctx.settings
        with self.ctx.session_factory() as session:
            run = session.get(Run, self.run_id)
            task = run.task
            sub = task.subcategory
            group = sub.group

            try:
                resolved = build_task_environment(session, self.ctx.secret_box, task)
            except SecretDecryptError as exc:
                self._writer = LogWriter(
                    self.ctx.session_factory, self.run_id, SecretMasker([]), settings.max_log_bytes
                )
                raise PreconditionError(str(exc)) from exc

            self._writer = LogWriter(
                self.ctx.session_factory,
                self.run_id,
                SecretMasker(resolved.secret_values),
                settings.max_log_bytes,
            )
            w = self._writer
            w.system(
                f"Execução #{run.id} da tarefa '{group.name} / {sub.name} / {task.name}' "
                f"(tentativa {run.attempt}, gatilho: {TRIGGER_LABELS[run.trigger]})."
            )
            if resolved.missing_keys:
                raise PreconditionError(
                    "Variáveis sem valor (preencha antes de executar): "
                    + ", ".join(resolved.missing_keys)
                )

            if task.working_dir:
                cwd = Path(task.working_dir)
                if not cwd.is_dir():
                    raise PreconditionError(f"Diretório de trabalho não encontrado: {cwd}")
            else:
                cwd = settings.workspaces_dir / str(task.id)
                cwd.mkdir(parents=True, exist_ok=True)

            env = _child_base_env()
            env.update(
                {
                    "RTS_RUN_ID": str(run.id),
                    "RTS_TASK_ID": str(task.id),
                    "RTS_TASK": task.name,
                    "RTS_SUBCATEGORY": sub.name,
                    "RTS_GROUP": group.name,
                    "RTS_ATTEMPT": str(run.attempt),
                    "RTS_TRIGGER": run.trigger.value,
                    "RTS_SCHEDULED_FOR": run.scheduled_for.isoformat() if run.scheduled_for else "",
                }
            )
            env.update(resolved.env)

            script_dir = settings.tmp_dir / f"run-{run.id}"
            try:
                argv = prepare_command(task.shell, task.command, script_dir)
            except SpawnError as exc:
                shutil.rmtree(script_dir, ignore_errors=True)
                raise PreconditionError(str(exc)) from exc

            shell = task.shell.value if task.shell else f"{default_shell().value} (padrão)"
            w.system(
                f"Diretório: {cwd} | shell: {shell}"
                + (f" | timeout: {task.timeout_seconds}s" if task.timeout_seconds else "")
            )
            return _Plan(argv, cwd, env, task.timeout_seconds, script_dir)

    def _run(self, plan: _Plan) -> RunStatus:
        w = self._writer
        assert w is not None
        try:
            proc = spawn(plan.argv, plan.cwd, plan.env)
        except SpawnError as exc:
            return self._finalize(RunStatus.FAILED, str(exc), retry=False)

        with self.ctx.session_factory() as session:
            run = session.get(Run, self.run_id)
            run.pid = proc.pid
            session.commit()
        w.flush()

        lines: queue.Queue = queue.Queue()
        threads = [
            threading.Thread(
                target=_reader, args=(proc.stdout, LogStream.STDOUT, lines), daemon=True
            ),
            threading.Thread(
                target=_reader, args=(proc.stderr, LogStream.STDERR, lines), daemon=True
            ),
        ]
        for t in threads:
            t.start()

        start = time.monotonic()
        deadline = start + plan.timeout if plan.timeout else None
        last_flush = last_cancel_check = start
        open_streams = len(threads)
        exited_at: float | None = None
        forced: tuple[RunStatus, str] | None = None

        while True:
            try:
                stream, text = lines.get(timeout=0.1)
                if text is None:
                    open_streams -= 1
                else:
                    w.write(stream, text)
            except queue.Empty:
                pass

            now = time.monotonic()
            if exited_at is None and proc.poll() is not None:
                exited_at = now
            if exited_at is not None and open_streams == 0:
                break

            if exited_at is not None and now - exited_at > self.pipe_drain_grace_seconds:
                # Background children still hold stdout/stderr open.
                w.system("Processo principal terminou; encerrando processos filhos remanescentes.")
                kill_tree(proc.pid, self.kill_grace_seconds)
                for pipe in (proc.stdout, proc.stderr):
                    pipe.close()
                exited_at = float("inf")  # don't repeat

            if forced is None:
                if deadline is not None and now >= deadline:
                    forced = (RunStatus.TIMEOUT, f"Tempo limite de {plan.timeout}s excedido.")
                elif self._interrupt.is_set():
                    forced = (RunStatus.FAILED, self._interrupt_reason)
                elif now - last_cancel_check >= self.cancel_poll_seconds:
                    last_cancel_check = now
                    if self._cancel_requested():
                        forced = (RunStatus.CANCELLED, "Cancelada pelo usuário.")
                if forced is not None:
                    w.system(f"{forced[1]} Encerrando o processo e seus filhos...")
                    w.flush()
                    kill_tree(proc.pid, self.kill_grace_seconds)

            if now - last_flush >= self.flush_interval_seconds:
                w.flush()
                last_flush = now

        exit_code = proc.wait()
        for t in threads:
            t.join(timeout=1)
        if forced is not None:
            return self._finalize(forced[0], forced[1], exit_code=exit_code, retry=True)
        if exit_code == 0:
            return self._finalize(RunStatus.SUCCESS, None, exit_code=0)
        return self._finalize(
            RunStatus.FAILED, f"Código de saída {exit_code}.", exit_code=exit_code, retry=True
        )

    def _cancel_requested(self) -> bool:
        with self.ctx.session_factory() as session:
            run = session.get(Run, self.run_id)
            return bool(run and run.cancel_requested)

    def _finalize(
        self,
        status: RunStatus,
        reason: str | None,
        *,
        exit_code: int | None = None,
        retry: bool = False,
    ) -> RunStatus:
        if self._writer is not None:
            suffix = f" - {reason}" if reason else ""
            code = f" (código {exit_code})" if exit_code is not None else ""
            self._writer.system(f"Finalizada: {STATUS_LABELS[status]}{code}{suffix}")
            self._writer.flush()

        now = self.ctx.clock()
        with self.ctx.session_factory() as session:
            run = session.get(Run, self.run_id)
            run.status = status
            run.status_reason = reason
            run.exit_code = exit_code
            run.finished_at = now
            if run.started_at is not None:
                run.duration_ms = int((now - run.started_at).total_seconds() * 1000)
            if self._writer is None and reason:
                append_system_log(session, run.id, reason)

            task = run.task
            if (
                retry
                and status in (RunStatus.FAILED, RunStatus.TIMEOUT)
                and run.attempt <= task.max_retries
            ):
                due = now + timedelta(seconds=task.retry_interval_seconds)
                nxt = create_run(
                    session,
                    task.id,
                    RunTrigger.RETRY,
                    scheduled_for=due,
                    attempt=run.attempt + 1,
                    root_run_id=run.root_run_id or run.id,
                )
                append_system_log(
                    session,
                    run.id,
                    f"Nova tentativa {nxt.attempt}/{task.max_retries + 1} (execução #{nxt.id}) "
                    f"em {task.retry_interval_seconds}s.",
                )
            session.commit()
        log.info("Run %s finished: %s", self.run_id, status.value)
        if self.ctx.notifier is not None:
            self.ctx.notifier.notify_run(self.run_id)
        return status
