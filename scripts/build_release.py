"""Build release artifacts into ./release.

    python scripts/build_release.py            # UI + wheel
    python scripts/build_release.py --exe      # + standalone executable for this OS

Artifacts:
    rts-<ver>-py3-none-any.whl          Python package with the built UI (needs Python 3.12+)
    rts-<ver>-windows-x64.zip           standalone executable (Windows)
    rts-<ver>-linux-x64.tar.gz          standalone executable (Linux)
    install.ps1 / install.sh            installers

Requirements: Node.js (UI build), and for --exe the backend installed in the
current environment plus PyInstaller (pip install -e "backend[postgres]" pyinstaller).
"""

from __future__ import annotations

import argparse
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
WEB_TARGET = BACKEND / "rts" / "web"
OUT = ROOT / "release"


def run(cmd: list[str], cwd: Path = ROOT) -> None:
    print("$", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=cwd, check=True, shell=(sys.platform == "win32" and cmd[0] == "npm"))


def version() -> str:
    text = (BACKEND / "rts" / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'__version__ = "([^"]+)"', text).group(1)


def build_web(skip_npm_install: bool) -> None:
    if not skip_npm_install:
        run(["npm", "ci", "--no-audit", "--no-fund"], cwd=FRONTEND)
    run(["npm", "run", "build"], cwd=FRONTEND)
    shutil.rmtree(WEB_TARGET, ignore_errors=True)
    shutil.copytree(FRONTEND / "dist", WEB_TARGET)
    print(f"UI copiada para {WEB_TARGET}")


def build_wheel() -> Path:
    for stale in OUT.glob("rts-*.whl"):
        stale.unlink()
    shutil.rmtree(BACKEND / "build", ignore_errors=True)
    run([sys.executable, "-m", "pip", "wheel", str(BACKEND), "--no-deps", "-w", str(OUT)])
    wheel = next(OUT.glob("rts-*.whl"))
    with zipfile.ZipFile(wheel) as z:
        names = z.namelist()
    assert any(n.startswith("rts/web/index.html") for n in names), "UI ausente no wheel"
    assert any(n.startswith("rts/migrations/versions/0002") for n in names), "migrations ausentes"
    print(f"Wheel: {wheel.name}")
    return wheel


def build_exe(ver: str) -> Path:
    work = ROOT / "build" / "pyinstaller"
    run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--distpath",
            str(work / "dist"),
            "--workpath",
            str(work / "work"),
            str(ROOT / "packaging" / "rts.spec"),
        ]
    )
    folder = work / "dist" / "rts"
    machine = {"amd64": "x64", "x86_64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(
        platform.machine().lower(), platform.machine().lower()
    )
    if sys.platform == "win32":
        target = OUT / f"rts-{ver}-windows-{machine}.zip"
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
            for path in folder.rglob("*"):
                z.write(path, Path("rts") / path.relative_to(folder))
    else:
        target = OUT / f"rts-{ver}-linux-{machine}.tar.gz"
        with tarfile.open(target, "w:gz") as tar:
            tar.add(folder, arcname="rts")
    print(f"Executável: {target.name} ({target.stat().st_size / 1e6:.0f} MB)")
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--exe", action="store_true", help="também gera o executável deste sistema")
    parser.add_argument("--skip-web", action="store_true", help="usa o UI já copiado em backend/rts/web")
    parser.add_argument("--skip-npm-install", action="store_true")
    parser.add_argument("--no-wheel", action="store_true")
    args = parser.parse_args()

    OUT.mkdir(exist_ok=True)
    ver = version()
    if not args.skip_web:
        build_web(args.skip_npm_install)
    if not (WEB_TARGET / "index.html").exists():
        sys.exit("UI não encontrada em backend/rts/web (rode sem --skip-web).")
    if not args.no_wheel:
        build_wheel()
    if args.exe:
        build_exe(ver)
    for script in ("install.ps1", "install.sh"):
        shutil.copy2(ROOT / script, OUT / script)
    print(f"\nArtefatos da versão {ver} em {OUT}:")
    for item in sorted(OUT.iterdir()):
        print(f"  {item.name}")


if __name__ == "__main__":
    main()
