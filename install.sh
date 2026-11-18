#!/usr/bin/env sh
# Instala (ou atualiza) o Real Task Scheduler no Linux, sem Docker.
#
#   curl -fsSL https://raw.githubusercontent.com/gabriel0torres/real-task-manager/main/install.sh | sudo sh
#   curl -fsSL .../install.sh | sh -s -- --mode standalone --port 8080
#   ./install.sh --from ./rts-0.1.0-py3-none-any.whl --no-service
#
# - Com Python 3.12+ (e o módulo venv): instala o pacote num ambiente virtual.
# - Sem Python: usa o executável autônomo (não precisa de nada instalado).
# Como root: instala em /opt/rts, cria o usuário de sistema "rts" e os serviços systemd.
# Sem root: instala em ~/.local/share/rts e cria serviços systemd do usuário.
# Reexecutar atualiza a instalação e preserva configuração (.env) e dados.
set -eu

MODE=auto
VERSION=latest
FROM=""
INSTALL_DIR=""
PORT=8000
ADMIN_PASSWORD=""
SERVICE=1
REPO="gabriel0torres/real-task-manager"

info() { printf '\033[36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[33mAVISO: %s\033[0m\n' "$*"; }
fail() { printf '\033[31mERRO: %s\033[0m\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
    case "$1" in
        --mode) MODE="$2"; shift 2 ;;
        --version) VERSION="$2"; shift 2 ;;
        --from) FROM="$2"; shift 2 ;;
        --dir) INSTALL_DIR="$2"; shift 2 ;;
        --port) PORT="$2"; shift 2 ;;
        --admin-password) ADMIN_PASSWORD="$2"; shift 2 ;;
        --no-service) SERVICE=0; shift ;;
        --repo) REPO="$2"; shift 2 ;;
        -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
        *) fail "opção desconhecida: $1" ;;
    esac
done
case "$MODE" in auto|python|standalone) ;; *) fail "--mode deve ser auto, python ou standalone" ;; esac

IS_ROOT=0; [ "$(id -u)" = "0" ] && IS_ROOT=1
if [ -z "$INSTALL_DIR" ]; then
    if [ $IS_ROOT = 1 ]; then INSTALL_DIR=/opt/rts; else INSTALL_DIR="$HOME/.local/share/rts"; fi
fi
case "$(uname -m)" in
    x86_64|amd64) ARCH=x64 ;;
    aarch64|arm64) ARCH=arm64 ;;
    *) ARCH="$(uname -m)" ;;
esac

# ------------------------------------------------------------------ python
find_python() {
    for candidate in python3.14 python3.13 python3.12 python3 python; do
        if command -v "$candidate" >/dev/null 2>&1 \
            && "$candidate" -c 'import sys, venv, ensurepip; sys.exit(0 if sys.version_info >= (3, 12) else 1)' 2>/dev/null; then
            command -v "$candidate"; return 0
        fi
    done
    return 1
}
PYTHON="$(find_python || true)"

if [ -n "$FROM" ]; then
    [ -f "$FROM" ] || fail "arquivo não encontrado: $FROM"
    FROM="$(cd "$(dirname "$FROM")" && pwd)/$(basename "$FROM")"
    if [ "$MODE" = auto ]; then
        case "$FROM" in *.whl) MODE=python ;; *) MODE=standalone ;; esac
    fi
fi
if [ "$MODE" = auto ]; then
    if [ -n "$PYTHON" ]; then MODE=python; else MODE=standalone; fi
fi
if [ "$MODE" = python ] && [ -z "$PYTHON" ]; then
    fail "Python 3.12+ com o módulo venv não encontrado (Debian/Ubuntu: apt install python3-venv). Ou use --mode standalone."
fi
info "Modo de instalação: $MODE  |  diretório: $INSTALL_DIR"

# ------------------------------------------------------------------ download
fetch() {  # url output
    if command -v curl >/dev/null 2>&1; then curl -fsSL "$1" -o "$2"
    elif command -v wget >/dev/null 2>&1; then wget -qO "$2" "$1"
    else fail "instale curl ou wget"; fi
}

get_artifact() {  # glob-like suffix to match the asset name
    if [ -n "$FROM" ]; then echo "$FROM"; return; fi
    if [ "$VERSION" = latest ]; then api="https://api.github.com/repos/$REPO/releases/latest"
    else api="https://api.github.com/repos/$REPO/releases/tags/$VERSION"; fi
    tmp="$(mktemp)"
    info "Consultando versões em github.com/$REPO ..." >&2
    fetch "$api" "$tmp" || fail "não foi possível obter a versão '$VERSION' de $REPO (há uma Release publicada?)"
    url="$(grep -o "\"browser_download_url\": *\"[^\"]*$1\"" "$tmp" | head -n1 | sed 's/.*"\(http[^"]*\)"/\1/')"
    rm -f "$tmp"
    [ -n "$url" ] || fail "a versão não tem um arquivo terminado em $1"
    out="${TMPDIR:-/tmp}/$(basename "$url")"
    info "Baixando $(basename "$url")..." >&2
    fetch "$url" "$out"
    echo "$out"
}

# ------------------------------------------------------------------ stop running instance
SYSTEMCTL=""
if [ $SERVICE = 1 ] && command -v systemctl >/dev/null 2>&1; then
    if [ $IS_ROOT = 1 ]; then SYSTEMCTL="systemctl"; else SYSTEMCTL="systemctl --user"; fi
    $SYSTEMCTL stop rts-worker.service rts-api.service 2>/dev/null || true
fi

mkdir -p "$INSTALL_DIR"

# ------------------------------------------------------------------ install
if [ "$MODE" = python ]; then
    WHEEL="$(get_artifact "py3-none-any.whl")"
    VENV="$INSTALL_DIR/venv"
    if [ ! -x "$VENV/bin/python" ]; then
        info "Criando ambiente virtual..."
        "$PYTHON" -m venv "$VENV" || fail "falha ao criar o ambiente virtual"
    fi
    info "Instalando o pacote (pode levar alguns minutos)..."
    "$VENV/bin/python" -m pip install --upgrade --quiet --disable-pip-version-check pip
    "$VENV/bin/python" -m pip install --upgrade --force-reinstall --no-deps --quiet --disable-pip-version-check "$WHEEL"
    "$VENV/bin/python" -m pip install --quiet --disable-pip-version-check "$WHEEL[postgres]"
    RUNNER="$VENV/bin/rts"
    rm -rf "$INSTALL_DIR/app"
else
    ARCHIVE="$(get_artifact "linux-$ARCH.tar.gz")"
    rm -rf "$INSTALL_DIR/app"
    mkdir -p "$INSTALL_DIR/app"
    info "Extraindo o executável..."
    tar -xzf "$ARCHIVE" -C "$INSTALL_DIR/app"
    RUNNER="$INSTALL_DIR/app/rts/rts"
fi
[ -x "$RUNNER" ] || fail "executável não encontrado após a instalação: $RUNNER"

# ------------------------------------------------------------------ configuration
ENV_FILE="$INSTALL_DIR/.env"
GENERATED=""
FRESH=0
if [ ! -f "$ENV_FILE" ]; then
    FRESH=1
    cat > "$ENV_FILE" <<EOF
# Configuração do Real Task Scheduler (veja o README para todas as opções)
RTS_DATA_DIR=$INSTALL_DIR/data
RTS_PORT=$PORT
RTS_ADMIN_USERNAME=admin
RTS_DEFAULT_TIMEZONE=America/Sao_Paulo
# RTS_DATABASE_URL=postgresql+psycopg://usuario:senha@host:5432/rts
# RTS_PUBLIC_URL=http://servidor:$PORT
EOF
    chmod 600 "$ENV_FILE"
    info "Configuração criada em $ENV_FILE"
else
    info "Mantendo a configuração existente em $ENV_FILE"
fi

# Wrapper so "rts <comando>" always runs with the installation's configuration.
cat > "$INSTALL_DIR/rts" <<EOF
#!/usr/bin/env sh
cd "$INSTALL_DIR" && exec "$RUNNER" "\$@"
EOF
chmod +x "$INSTALL_DIR/rts"
if [ $IS_ROOT = 1 ]; then ln -sf "$INSTALL_DIR/rts" /usr/local/bin/rts; fi

# Admin password: set through the CLI, so it is never stored in plain text in .env.
if [ $FRESH = 1 ]; then
    if [ -n "$ADMIN_PASSWORD" ]; then
        OUT="$("$INSTALL_DIR/rts" admin reset-password --password "$ADMIN_PASSWORD" 2>&1)" || fail "falha ao preparar o banco: $OUT"
    else
        OUT="$("$INSTALL_DIR/rts" admin reset-password 2>&1)" || fail "falha ao preparar o banco: $OUT"
        GENERATED="$(printf '%s\n' "$OUT" | sed -n 's/.*redefinida: \([^ ]*\).*/\1/p' | head -n1)"
    fi
fi

# ------------------------------------------------------------------ service
SERVICE_OK=0
if [ -n "$SYSTEMCTL" ]; then
    if [ $IS_ROOT = 1 ]; then
        UNIT_DIR=/etc/systemd/system
        id rts >/dev/null 2>&1 || useradd --system --home-dir "$INSTALL_DIR" --shell /usr/sbin/nologin rts
        mkdir -p "$INSTALL_DIR/data"
        chown -R rts:rts "$INSTALL_DIR"
        USER_LINE="User=rts
Group=rts"
        WANTED=multi-user.target
    else
        UNIT_DIR="$HOME/.config/systemd/user"
        USER_LINE=""
        WANTED=default.target
    fi
    mkdir -p "$UNIT_DIR"
    for name in api worker; do
        cat > "$UNIT_DIR/rts-$name.service" <<EOF
[Unit]
Description=Real Task Scheduler ($name)
After=network-online.target
Wants=network-online.target
$( [ $name = worker ] && printf 'After=rts-api.service\n' )

[Service]
$USER_LINE
WorkingDirectory=$INSTALL_DIR
Environment=RTS_ENV_FILE=$ENV_FILE
ExecStart=$RUNNER $name
Restart=always
RestartSec=3
KillMode=mixed
TimeoutStopSec=30

[Install]
WantedBy=$WANTED
EOF
    done
    $SYSTEMCTL daemon-reload
    $SYSTEMCTL enable --now rts-api.service >/dev/null
    sleep 3
    $SYSTEMCTL enable --now rts-worker.service >/dev/null
    SERVICE_OK=1
    if [ $IS_ROOT = 0 ]; then
        warn "Serviços do usuário só rodam com você logado. Para iniciar no boot: sudo loginctl enable-linger $(id -un)"
    fi
elif [ $SERVICE = 1 ]; then
    warn "systemd não encontrado: inicie manualmente com '$INSTALL_DIR/rts start'."
fi

# ------------------------------------------------------------------ summary
URL="http://localhost:$PORT"
if [ $SERVICE_OK = 1 ]; then
    info "Aguardando o RTS responder em $URL ..."
    i=0
    until fetch "$URL/api/v1/health" /dev/null 2>/dev/null; do
        i=$((i + 1)); [ $i -ge 60 ] && { warn "o RTS ainda não respondeu; veja: journalctl -u rts-api"; break; }
        sleep 1
    done
fi

echo
printf '\033[32mReal Task Scheduler instalado em %s\033[0m\n' "$INSTALL_DIR"
echo "  Interface:     $URL"
echo "  Usuário:       admin"
[ -n "$GENERATED" ] && echo "  Senha:         $GENERATED  (troque no primeiro acesso)"
echo "  Configuração:  $ENV_FILE"
if [ $SERVICE_OK = 1 ]; then
    echo "  Serviços:      rts-api e rts-worker ($SYSTEMCTL status rts-api)"
else
    echo "  Para iniciar:  $INSTALL_DIR/rts start"
fi
echo "  Senha perdida: $INSTALL_DIR/rts admin reset-password"
