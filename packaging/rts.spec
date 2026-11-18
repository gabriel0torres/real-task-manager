# PyInstaller spec for the standalone RTS executable (no Python needed on the target).
#
# Built by scripts/build_release.py:  pyinstaller packaging/rts.spec
# Output: dist/rts/ (folder with rts / rts.exe and its libraries)
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

ROOT = Path(SPECPATH).parent  # noqa: F821 - provided by PyInstaller
BACKEND = ROOT / "backend"

hiddenimports = (
    collect_submodules("rts")
    + collect_submodules("uvicorn")
    + collect_submodules("apscheduler")
    + collect_submodules("alembic", filter=lambda name: not name.startswith("alembic.testing"))
    + collect_submodules("sqlalchemy.dialects")
    + ["psycopg", "psycopg_binary"]
)

datas = (
    # Alembic reads env.py and the revision scripts from disk; the built UI is served from rts/web.
    collect_data_files(
        "rts",
        include_py_files=True,
        includes=["migrations/env.py", "migrations/script.py.mako", "migrations/versions/*.py", "web/**/*"],
    )
    + collect_data_files("tzdata")  # time zones on Windows
    + collect_data_files("alembic")
    # APScheduler finds its job stores/executors through package entry points.
    + copy_metadata("apscheduler")
    + copy_metadata("rts")
)

a = Analysis(  # noqa: F821
    [str(BACKEND / "rts" / "__main__.py")],
    pathex=[str(BACKEND)],
    hiddenimports=hiddenimports,
    datas=datas,
    excludes=["tkinter", "pytest", "ruff"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="rts",
    console=True,
    icon=None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="rts")  # noqa: F821
