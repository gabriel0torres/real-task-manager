"""New-version check (GitHub Releases) and update requests.

The API never updates itself in place: it writes ``<data_dir>/update-request.json``
and wakes an updater that runs *outside* the RTS processes (which the update
stops):

* Windows: the scheduled task "RTS Update" (registered by install.ps1);
* Linux: the systemd path unit ``rts-update.path`` watching the request file
  (registered by install.sh), which starts ``rts-update.service`` as root.

The updater backs up the database, runs the installer of the requested version
and writes ``<data_dir>/update-result.json``.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from rts import __version__
from rts.config import Settings
from rts.models.base import utcnow
from rts.services.errors import ConflictError, InvalidInputError
from rts.services.settings import get_setting, set_setting

log = logging.getLogger(__name__)

STATUS_KEY = "update_status"
CHECK_INTERVAL = timedelta(hours=12)
REQUEST_FILE = "update-request.json"
RESULT_FILE = "update-result.json"
SELF_UPDATERS = {"windows-task", "systemd-path", "systemd-user-path"}
WINDOWS_TASK = "RTS Update"
_check_lock = threading.Lock()


class UpdateCheckError(RuntimeError):
    pass


def parse_version(value: str) -> tuple[int, ...] | None:
    """'v1.2.3' -> (1, 2, 3); pre-releases / invalid -> None."""
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", value.strip())
    return tuple(int(p) for p in match.groups()) if match else None


def is_newer(candidate: str, current: str = __version__) -> bool:
    new, cur = parse_version(candidate), parse_version(current)
    return bool(new and cur and new > cur)


def fetch_latest(repo: str, timeout: float = 8.0) -> dict:
    """Latest published (non-draft, non-prerelease) release of the repository."""
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/releases/latest",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "rts-update-check"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            data = json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise UpdateCheckError("Nenhuma versão publicada no GitHub.") from exc
        raise UpdateCheckError(f"GitHub respondeu HTTP {exc.code}.") from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise UpdateCheckError(f"Sem acesso ao GitHub: {getattr(exc, 'reason', exc)}") from exc
    tag = data.get("tag_name", "")
    return {
        "tag": tag,
        "version": tag.lstrip("v"),
        "url": data.get("html_url"),
        "notes": (data.get("body") or "").strip()[:5000],
        "published_at": data.get("published_at"),
    }


# --------------------------------------------------------------------------- status
def _cached(session: Session) -> dict:
    return dict(get_setting(session, STATUS_KEY, {}) or {})


def refresh(session: Session, settings: Settings) -> dict:
    """Query GitHub now and store the result (errors are stored too)."""
    status = _cached(session)
    status["checked_at"] = utcnow().isoformat()
    try:
        status.update(fetch_latest(settings.update_repo), error=None)
    except UpdateCheckError as exc:
        status["error"] = str(exc)
        log.info("Verificação de nova versão falhou: %s", exc)
    set_setting(session, STATUS_KEY, status)
    session.commit()
    return status


def _stale(status: dict) -> bool:
    checked = status.get("checked_at")
    if not checked:
        return True
    try:
        return utcnow() - datetime.fromisoformat(checked) > CHECK_INTERVAL
    except ValueError:
        return True


def _read_json(path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def instructions(settings: Settings, tag: str | None) -> str:
    version = tag or "<nova versão>"
    if settings.install_type == "docker":
        return (
            "Instalação com Docker: na pasta do projeto, rode\n"
            "  git pull\n"
            "  docker compose up -d --build\n"
            "Os dados no volume rts-data são mantidos."
        )
    if settings.install_type in ("python", "standalone"):
        return (
            "Rode o instalador novamente (como Administrador / root):\n"
            "  Windows: irm https://raw.githubusercontent.com/"
            f"{settings.update_repo}/main/install.ps1 | iex\n"
            "  Linux:   curl -fsSL https://raw.githubusercontent.com/"
            f"{settings.update_repo}/main/install.sh | sudo sh\n"
            "Configuração e dados são mantidos."
        )
    return (
        "Instalação a partir do código-fonte: atualize o repositório "
        f"(git pull ou git checkout {version}), reinstale o backend "
        "(pip install -e backend) e gere a interface (npm run build); "
        "depois reinicie a API e o worker."
    )


def get_status(session: Session, settings: Settings, *, force: bool = False) -> dict:
    status = _cached(session)
    if settings.update_check and (force or _stale(status)):
        with _check_lock:
            status = _cached(session)
            if force or _stale(status):
                status = refresh(session, settings)

    latest = status.get("version")
    available = bool(latest and is_newer(latest))
    data_dir = settings.data_dir
    request = _read_json(data_dir / REQUEST_FILE)
    return {
        "current_version": __version__,
        "check_enabled": settings.update_check,
        "checked_at": status.get("checked_at"),
        "error": status.get("error"),
        "latest_version": latest,
        "latest_tag": status.get("tag"),
        "release_url": status.get("url"),
        "release_notes": status.get("notes") if available else None,
        "published_at": status.get("published_at"),
        "update_available": available,
        "install_type": settings.install_type or "source",
        "can_self_update": settings.updater in SELF_UPDATERS,
        "update_in_progress": request is not None,
        "last_result": _read_json(data_dir / RESULT_FILE),
        "instructions": instructions(settings, status.get("tag")),
    }


# --------------------------------------------------------------------------- apply
def _trigger_windows_task() -> None:
    result = subprocess.run(
        ["schtasks", "/Run", "/TN", WINDOWS_TASK], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise InvalidInputError(
            "Não foi possível iniciar o atualizador (tarefa agendada 'RTS Update'): "
            + (result.stderr or result.stdout).strip()
        )


def request_update(session: Session, settings: Settings, version: str | None = None) -> dict:
    if settings.updater not in SELF_UPDATERS:
        raise InvalidInputError(
            "Esta instalação não tem atualizador automático. " + instructions(settings, None)
        )
    status = get_status(session, settings)
    target = version or status["latest_tag"]
    if not target or not parse_version(target):
        raise InvalidInputError("Nenhuma versão nova conhecida. Use “Verificar agora”.")
    if not is_newer(target):
        raise InvalidInputError(f"A versão {target} não é mais nova que a atual ({__version__}).")
    request_path = settings.data_dir / REQUEST_FILE
    if request_path.exists():
        raise ConflictError("Já existe uma atualização em andamento.")

    payload = {
        "version": target if target.startswith("v") else f"v{target}",
        "from_version": __version__,
        "requested_at": utcnow().isoformat(),
        "repo": settings.update_repo,
    }
    (settings.data_dir / RESULT_FILE).unlink(missing_ok=True)
    request_path.write_text(json.dumps(payload), encoding="utf-8")
    log.warning("Atualização para %s solicitada.", payload["version"])
    if settings.updater == "windows-task":
        try:
            _trigger_windows_task()
        except Exception:
            request_path.unlink(missing_ok=True)
            raise
    # systemd: the path unit starts the updater as soon as the file appears.
    return payload
