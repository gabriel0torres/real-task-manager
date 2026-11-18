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
PORT_SET=0
ADMIN_PASSWORD=""
SERVICE=1
REPO="gabriel0torres/real-task-manager"

info() { printf '\033[36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[33mAVISO: %s\033[0m\n' "$*"; }
fail() { printf '\033[31mERRO: %s\033[0m\n' "$*" >&2; exit 1; }
# When run by the web updater (update.sh), report steps to its progress log.
report_progress() {  # STEP STATUS [DETAIL]
    [ -n "${RTS_UPDATE_PROGRESS:-}" ] || return 0
    detail=""
    [ -n "${3:-}" ] && detail=", \"detail\": \"$3\""
    printf '{"step": "%s", "status": "%s", "at": "%s"%s}\n' \
        "$1" "$2" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$detail" >> "$RTS_UPDATE_PROGRESS" 2>/dev/null || true
}

while [ $# -gt 0 ]; do
    case "$1" in
        --mode) MODE="$2"; shift 2 ;;
        --version) VERSION="$2"; shift 2 ;;
        --from) FROM="$2"; shift 2 ;;
        --dir) INSTALL_DIR="$2"; shift 2 ;;
        --port) PORT="$2"; PORT_SET=1; shift 2 ;;
        --admin-password) ADMIN_PASSWORD="$2"; shift 2 ;;
        --no-service) SERVICE=0; shift ;;
        --repo) REPO="$2"; shift 2 ;;
        -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
        *) fail "opção desconhecida: $1" ;;
    esac
done
case "$MODE" in auto|python|standalone) ;; *) fail "--mode deve ser auto, python ou standalone" ;; esac
case "$PORT" in ''|*[!0-9]*) fail "--port deve ser um número entre 1 e 65535" ;; esac
[ "$PORT" -ge 1 ] && [ "$PORT" -le 65535 ] || fail "--port deve ser um número entre 1 e 65535"

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
# On an update the existing virtual environment already has its own Python.
VENV_OK=0
if [ -x "$INSTALL_DIR/venv/bin/python" ] \
    && "$INSTALL_DIR/venv/bin/python" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' 2>/dev/null; then
    VENV_OK=1
fi

if [ -n "$FROM" ]; then
    [ -f "$FROM" ] || fail "arquivo não encontrado: $FROM"
    FROM="$(cd "$(dirname "$FROM")" && pwd)/$(basename "$FROM")"
    if [ "$MODE" = auto ]; then
        case "$FROM" in *.whl) MODE=python ;; *) MODE=standalone ;; esac
    fi
fi
if [ "$MODE" = auto ]; then
    if [ -n "$PYTHON" ] || [ $VENV_OK = 1 ]; then MODE=python; else MODE=standalone; fi
fi
if [ "$MODE" = python ] && [ -z "$PYTHON" ] && [ $VENV_OK = 0 ]; then
    fail "Python 3.12+ com o módulo venv não encontrado (Debian/Ubuntu: apt install python3-venv). Ou use --mode standalone."
fi
info "Modo de instalação: $MODE  |  diretório: $INSTALL_DIR"

# ------------------------------------------------------------------ download
fetch() {  # url output
    if command -v curl >/dev/null 2>&1; then curl -fsSL "$1" -o "$2"
    elif command -v wget >/dev/null 2>&1; then wget -qO "$2" "$1"
    else fail "instale curl ou wget"; fi
}

# Release files are downloaded straight from github.com/<repo>/releases/download: their
# names are predictable, and the GitHub API (60 requests per hour per IP without login)
# is not needed.
resolve_tag() {
    if [ "$VERSION" != latest ]; then
        case "$VERSION" in v*) echo "$VERSION" ;; *) echo "v$VERSION" ;; esac
        return
    fi
    info "Consultando a versão mais nova em github.com/$REPO ..." >&2
    if command -v curl >/dev/null 2>&1; then
        final="$(curl -fsSIL -o /dev/null -w '%{url_effective}' "https://github.com/$REPO/releases/latest" || true)"
    else
        final="$(wget -S --spider "https://github.com/$REPO/releases/latest" 2>&1 \
            | sed -n 's/^ *[Ll]ocation: *//p' | tail -n1 | tr -d '\r')"
    fi
    case "$final" in
        */releases/tag/*) echo "${final##*/releases/tag/}" ;;
        *) fail "nenhuma Release publicada em $REPO (ou sem acesso ao GitHub)" ;;
    esac
}

get_artifact() {  # file name after "rts-<versão>-", e.g. py3-none-any.whl
    if [ -n "$FROM" ]; then echo "$FROM"; return; fi
    tag="$(resolve_tag)"
    name="rts-${tag#v}-$1"
    out="${TMPDIR:-/tmp}/$name"
    info "Baixando $name ($tag)..." >&2
    fetch "https://github.com/$REPO/releases/download/$tag/$name" "$out" \
        || fail "não foi possível baixar $name da versão $tag (a versão existe?)"
    echo "$out"
}

# ------------------------------------------------------------------ stop running instance
SYSTEMCTL=""
if [ $SERVICE = 1 ] && command -v systemctl >/dev/null 2>&1; then
    if [ $IS_ROOT = 1 ]; then SYSTEMCTL="systemctl"; else SYSTEMCTL="systemctl --user"; fi
    $SYSTEMCTL stop rts-worker.service rts-api.service 2>/dev/null || true
fi

# ------------------------------------------------------------------ port
ENV_FILE="$INSTALL_DIR/.env"
FRESH=0; [ -f "$ENV_FILE" ] || FRESH=1

port_in_use() {  # PORT - true when anything listens on it (IPv4 or IPv6, any address)
    hex="$(printf '%04X' "$1")"
    for table in /proc/net/tcp /proc/net/tcp6; do
        [ -r "$table" ] || continue
        # Columns: sl local_address rem_address st ...; state 0A = LISTEN.
        if awk -v port="$hex" 'NR > 1 && $4 == "0A" { split($2, a, ":"); if (a[2] == port) found = 1 }
                               END { exit !found }' "$table"; then
            return 0
        fi
    done
    return 1
}

port_owner() {  # PORT - "name (PID n)" when ss can tell (other users' processes need root)
    owner=""
    if command -v ss >/dev/null 2>&1; then
        owner="$(ss -Hltnp "sport = :$1" 2>/dev/null \
            | sed -n 's/.*users:(("\([^"]*\)",pid=\([0-9]*\).*/\1 (PID \2)/p' | head -n1)"
    fi
    echo "${owner:-outro programa}"
}

rts_on_port() {  # PORT - true when an RTS API answers there
    body=""
    if command -v curl >/dev/null 2>&1; then
        body="$(curl -fsS --max-time 3 "http://127.0.0.1:$1/api/v1/health" 2>/dev/null || true)"
    elif command -v wget >/dev/null 2>&1; then
        body="$(wget -qO- -T 3 -t 1 "http://127.0.0.1:$1/api/v1/health" 2>/dev/null || true)"
    fi
    printf '%s' "$body" | grep -q '"status": *"ok"' && printf '%s' "$body" | grep -q '"version"'
}

find_free_port() {  # PORT - first free port among the next 100 (prints nothing if none)
    p=$(($1 + 1)); last=$(($1 + 100)); [ $last -le 65535 ] || last=65535
    while [ $p -le $last ]; do
        if ! port_in_use $p; then echo $p; return 0; fi
        p=$((p + 1))
    done
    return 0
}

# Port the installation will use: --port on a fresh install (or when passed explicitly),
# otherwise the one already in .env.
CURRENT_PORT=""
if [ $FRESH = 0 ]; then
    CURRENT_PORT="$(sed -n 's/^RTS_PORT=//p' "$ENV_FILE" | tail -n1 | tr -d ' \r')"
    case "$CURRENT_PORT" in ''|*[!0-9]*) CURRENT_PORT=8000 ;; esac
fi
if [ $FRESH = 1 ] || [ $PORT_SET = 1 ]; then WANTED_PORT=$PORT; else WANTED_PORT=$CURRENT_PORT; fi
EFFECTIVE_PORT=$WANTED_PORT

BUSY=0; port_in_use "$WANTED_PORT" && BUSY=1
if [ $BUSY = 1 ] && [ $FRESH = 0 ] && [ "$WANTED_PORT" = "$CURRENT_PORT" ]; then
    # Upgrade: the RTS stopped above may take a moment to release the port...
    i=0
    while [ $BUSY = 1 ] && [ $i -lt 5 ]; do
        sleep 1; i=$((i + 1)); port_in_use "$WANTED_PORT" || BUSY=0
    done
    # ...or it is this same installation still running (e.g. started by hand): keep the port.
    if [ $BUSY = 1 ] && rts_on_port "$WANTED_PORT"; then
        warn "O RTS desta instalação está em execução na porta $WANTED_PORT; a porta será mantida. Reinicie-o depois para usar a nova versão."
        BUSY=0
    fi
fi
if [ $BUSY = 1 ]; then
    OWNER="$(port_owner "$WANTED_PORT")"
    FREE="$(find_free_port "$WANTED_PORT")"
    if [ $PORT_SET = 1 ]; then
        if [ -n "$FREE" ]; then HINT=" Escolha outra, por exemplo: --port $FREE"; else HINT=" Escolha outra com --port."; fi
        fail "a porta $WANTED_PORT já está em uso ($OWNER).$HINT"
    fi
    [ -n "$FREE" ] || fail "a porta $WANTED_PORT e as 100 seguintes estão em uso. Escolha uma livre com --port."
    warn "A porta $WANTED_PORT já está em uso ($OWNER); o RTS usará a porta $FREE."
    EFFECTIVE_PORT=$FREE
fi
info "Porta da interface web: $EFFECTIVE_PORT"

mkdir -p "$INSTALL_DIR"

# ------------------------------------------------------------------ install
if [ "$MODE" = python ]; then
    WHEEL="$(get_artifact "py3-none-any.whl")"
    VENV="$INSTALL_DIR/venv"
    if [ $VENV_OK = 1 ]; then
        info "Usando o ambiente virtual existente ($VENV)."
    else
        [ -n "$PYTHON" ] || fail "Python 3.12+ não encontrado para recriar o ambiente virtual."
        rm -rf "$VENV"  # missing or broken (its Python is gone)
        info "Criando ambiente virtual com $PYTHON..."
        "$PYTHON" -m venv "$VENV" || fail "falha ao criar o ambiente virtual"
    fi
    info "Instalando o pacote (pode levar alguns minutos)..."
    report_progress install running "instalando o pacote Python e as dependências"
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
    report_progress install running "extraindo o executável"
    tar -xzf "$ARCHIVE" -C "$INSTALL_DIR/app"
    RUNNER="$INSTALL_DIR/app/rts/rts"
fi
[ -x "$RUNNER" ] || fail "executável não encontrado após a instalação: $RUNNER"

# ------------------------------------------------------------------ configuration
GENERATED=""
set_env_value() {  # KEY VALUE - replace/append a line in .env (empty value removes the key)
    tmp="$ENV_FILE.tmp"
    grep -v "^$1=" "$ENV_FILE" > "$tmp" || true
    if [ -n "$2" ]; then printf '%s=%s\n' "$1" "$2" >> "$tmp"; fi
    cat "$tmp" > "$ENV_FILE"   # keeps owner and permissions of .env
    rm -f "$tmp"
}
if [ $FRESH = 1 ]; then
    cat > "$ENV_FILE" <<EOF
# Configuração do Real Task Scheduler (veja o README para todas as opções)
RTS_DATA_DIR=$INSTALL_DIR/data
RTS_PORT=$EFFECTIVE_PORT
RTS_ADMIN_USERNAME=admin
RTS_DEFAULT_TIMEZONE=America/Sao_Paulo
# RTS_DATABASE_URL=postgresql+psycopg://usuario:senha@host:5432/rts
# RTS_PUBLIC_URL=http://servidor:$EFFECTIVE_PORT
EOF
    chmod 600 "$ENV_FILE"
    info "Configuração criada em $ENV_FILE"
else
    info "Mantendo a configuração existente em $ENV_FILE"
    if [ "$EFFECTIVE_PORT" != "$CURRENT_PORT" ]; then
        set_env_value RTS_PORT "$EFFECTIVE_PORT"
        info "Porta alterada de $CURRENT_PORT para $EFFECTIVE_PORT em $ENV_FILE"
    fi
fi
set_env_value RTS_INSTALL_TYPE "$MODE"

# Updater used by "Atualizar" in the web interface: started by rts-update.service when
# data/update-request.json appears. Order: download the new version while the RTS still
# runs, then stop it, back up the database, install and wait for the new API. Each step
# is appended to data/update-progress.log, which the web interface shows. Written to a
# temp file and renamed, because a running updater may be reading the current one.
cat > "$INSTALL_DIR/update.sh.tmp" <<'UPDATER'
#!/bin/sh
# Atualizador do Real Task Scheduler (iniciado por rts-update.service).
DIR="$(cd "$(dirname "$0")" && pwd)"
DATA="$DIR/data"
REQ="$DATA/update-request.json"
RES="$DATA/update-result.json"
PROG="$DATA/update-progress.log"
[ -f "$REQ" ] || exit 0
field() { sed -n "s/.*\"$1\": *\"\([^\"]*\)\".*/\1/p" "$REQ" | head -n1; }
VERSION="$(field version)"; FROM="$(field from_version)"; REPO="$(field repo)"; REQUESTED="$(field requested_at)"
rm -f "$REQ"
env_value() { sed -n "s/^$1=//p" "$DIR/.env" | tail -n1 | tr -d ' \r'; }
MODE="$(env_value RTS_INSTALL_TYPE)"
if [ "$MODE" != python ] && [ "$MODE" != standalone ]; then
    if [ -x "$DIR/venv/bin/python" ]; then MODE=python; else MODE=standalone; fi
fi
if [ "$(id -u)" = 0 ]; then SYSTEMCTL=systemctl; else SYSTEMCTL="systemctl --user"; fi
touch "$PROG"; chown --reference="$DATA" "$PROG" 2>/dev/null || true
STEP=start
progress() {  # STEP STATUS [DETAIL]
    STEP="$1"
    detail=""
    if [ -n "${3:-}" ]; then
        detail=", \"detail\": \"$(printf '%s' "$3" | tr -d '"\\' | tr '\n' ' ')\""
    fi
    printf '{"step": "%s", "status": "%s", "at": "%s"%s}\n' \
        "$1" "$2" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$detail" >> "$PROG"
}
result() {
    printf '{"ok": %s, "version": "%s", "from_version": "%s", "requested_at": "%s", "finished_at": "%s", "message": "%s"}\n' \
        "$1" "$VERSION" "$FROM" "$REQUESTED" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$(printf '%s' "$2" | tr -d '"\\')" > "$RES"
    chown --reference="$DATA" "$RES" 2>/dev/null || true
}
mb() { awk -v b="${1:-0}" 'BEGIN { printf "%.1f", b / 1048576 }'; }
fetch() { if command -v curl >/dev/null 2>&1; then curl -fsSL "$1" -o "$2"; else wget -qO "$2" "$1"; fi; }
http_get() {
    if command -v curl >/dev/null 2>&1; then curl -fsS --max-time 3 "$1" 2>/dev/null
    else wget -qO- -T 3 -t 1 "$1" 2>/dev/null; fi
}
download() {  # URL TARGET NAME - reports "x de y MB" every 2 seconds
    rm -f "$2"
    total=""
    if command -v curl >/dev/null 2>&1; then
        total="$(curl -fsSIL "$1" 2>/dev/null | tr -d '\r' | sed -n 's/^[Cc]ontent-[Ll]ength: *//p' | tail -n1)"
        curl -fsSL "$1" -o "$2" &
    else
        wget -qO "$2" "$1" &
    fi
    pid=$!
    while kill -0 "$pid" 2>/dev/null; do
        got="$(wc -c < "$2" 2>/dev/null || echo 0)"
        if [ -n "$total" ]; then of=" de $(mb "$total") MB"; else of=" MB"; fi
        progress download running "$3: $(mb "$got")$of"
        sleep 2
    done
    wait "$pid"
}
fail() { progress "$STEP" failed "$1"; result false "Falha na atualização: $1 (veja data/update.log)"; }
{
    echo "=== $(date) atualização $FROM -> $VERSION"
    progress start done
    PLAIN="${VERSION#v}"
    BASE="https://github.com/$REPO/releases/download/$VERSION"
    case "$(uname -m)" in
        x86_64|amd64) ARCH=x64 ;;
        aarch64|arm64) ARCH=arm64 ;;
        *) ARCH="$(uname -m)" ;;
    esac
    if [ "$MODE" = python ]; then ASSET="rts-$PLAIN-py3-none-any.whl"; else ASSET="rts-$PLAIN-linux-$ARCH.tar.gz"; fi
    WORK="$(mktemp -d)"
    STOPPED=0
    # 1. Download while the RTS keeps running: a failure here interrupts nothing.
    progress download running install.sh
    if ! fetch "$BASE/install.sh" "$WORK/install.sh"; then
        fail "não foi possível baixar install.sh de $VERSION"
    elif ! download "$BASE/$ASSET" "$WORK/$ASSET" "$ASSET"; then
        fail "não foi possível baixar $ASSET"
    else
        progress download done "$ASSET ($(mb "$(wc -c < "$WORK/$ASSET")") MB)"
        # 2. Stop the RTS.
        progress stop running
        $SYSTEMCTL stop rts-worker.service rts-api.service
        STOPPED=1
        progress stop done
        # 3. Back up the SQLite database.
        progress backup running
        STAMP="$(date +%Y%m%d-%H%M%S)"
        mkdir -p "$DATA/backups"
        COPIED=0
        for f in rts.db rts.db-wal rts.db-shm; do
            if [ -f "$DATA/$f" ]; then
                cp -p "$DATA/$f" "$DATA/backups/$(echo "$f" | sed "s/^rts/rts-$FROM-$STAMP/")"
                COPIED=$((COPIED + 1))
            fi
        done
        chown -R --reference="$DATA" "$DATA/backups" 2>/dev/null || true
        if [ $COPIED -gt 0 ]; then progress backup done "data/backups/rts-$FROM-$STAMP.db"
        else progress backup done "sem banco SQLite local (nada a copiar)"; fi
        # 4. Install (the installer reports its own progress through RTS_UPDATE_PROGRESS).
        progress install running "modo $MODE"
        if RTS_UPDATE_PROGRESS="$PROG" sh "$WORK/install.sh" --version "$VERSION" --dir "$DIR" \
            --mode "$MODE" --repo "$REPO" --from "$WORK/$ASSET"; then
            progress install done
            # 5. Wait for the new API (the installer already started the services).
            progress restart running "aguardando a API responder"
            PORT="$(env_value RTS_PORT)"; [ -n "$PORT" ] || PORT=8000
            i=0
            until http_get "http://127.0.0.1:$PORT/api/v1/health" | grep -q "\"version\": *\"$PLAIN\""; do
                i=$((i + 1))
                [ $i -ge 90 ] && break
                sleep 1
            done
            if [ $i -lt 90 ]; then
                progress restart done "versão $PLAIN respondendo na porta $PORT"
                result true "Atualizado para $VERSION."
                STOPPED=0
            else
                fail "a nova versão foi instalada, mas a API não respondeu em 90 s na porta $PORT"
            fi
        else
            fail "o instalador falhou"
        fi
        if [ $STOPPED = 1 ]; then
            $SYSTEMCTL start rts-api.service
            sleep 3
            $SYSTEMCTL start rts-worker.service
        fi
    fi
    rm -rf "$WORK"
} >> "$DATA/update.log" 2>&1
UPDATER
chmod +x "$INSTALL_DIR/update.sh.tmp"
mv -f "$INSTALL_DIR/update.sh.tmp" "$INSTALL_DIR/update.sh"

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
report_progress install done
report_progress restart running "iniciando os serviços"
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
    # Updater: the path unit starts it when the web interface writes the request file.
    # As root it runs as root (the RTS itself runs as the unprivileged "rts" user).
    cat > "$UNIT_DIR/rts-update.service" <<EOF
[Unit]
Description=Real Task Scheduler (atualizador)

[Service]
Type=oneshot
ExecStart=/bin/sh $INSTALL_DIR/update.sh
TimeoutStartSec=1800
EOF
    cat > "$UNIT_DIR/rts-update.path" <<EOF
[Unit]
Description=Real Task Scheduler (pedido de atualização)

[Path]
PathExists=$INSTALL_DIR/data/update-request.json
Unit=rts-update.service

[Install]
WantedBy=$WANTED
EOF
    if [ $IS_ROOT = 1 ]; then set_env_value RTS_UPDATER systemd-path; else set_env_value RTS_UPDATER systemd-user-path; fi
    $SYSTEMCTL daemon-reload
    $SYSTEMCTL enable --now rts-update.path >/dev/null
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
if [ $SERVICE_OK = 0 ]; then set_env_value RTS_UPDATER ""; fi

# ------------------------------------------------------------------ summary
URL="http://localhost:$EFFECTIVE_PORT"
if [ $SERVICE_OK = 1 ]; then
    info "Aguardando o RTS responder em $URL ..."
    i=0
    until rts_on_port "$EFFECTIVE_PORT"; do
        i=$((i + 1))
        if [ $i -ge 60 ]; then
            warn "o RTS ainda não respondeu na porta $EFFECTIVE_PORT; veja: journalctl -u rts-api"
            warn "se a porta foi ocupada por outro programa, troque RTS_PORT em $ENV_FILE e reinicie rts-api"
            break
        fi
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
echo "  Atualizar:     pela interface (Configurações > Atualizações) ou rodando este instalador de novo"
