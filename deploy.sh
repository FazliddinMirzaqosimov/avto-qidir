#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# EV Hunter — one-shot deploy / update script. Run as root on the server:
#
#   bash deploy.sh
#
# Safe to re-run. It only ever touches /opt/ev-hunter, the `ev-hunter` container
# and the `ev-hunter-data` volume; it never restarts, rebuilds or reconfigures
# anything else on the host.
# ---------------------------------------------------------------------------
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/FazliddinMirzaqosimov/avto-qidir.git}"
APP_DIR="${APP_DIR:-/opt/ev-hunter}"
BRANCH="${BRANCH:-main}"

info()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn()  { printf '\033[1;33m!!!\033[0m %s\n' "$*"; }
die()   { printf '\033[1;31mERR\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Run this as root (sudo -i, then bash deploy.sh)."

# --- 1. Docker -------------------------------------------------------------
if command -v docker >/dev/null 2>&1; then
    info "Docker already installed: $(docker --version)  — leaving it untouched."
else
    info "Docker not found. Installing via the official convenience script…"
    curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
    sh /tmp/get-docker.sh
    rm -f /tmp/get-docker.sh
fi

# compose v2 plugin preferred; fall back to the standalone v1 binary.
if docker compose version >/dev/null 2>&1; then
    COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE="docker-compose"
else
    info "Installing the docker compose plugin…"
    if command -v apt-get >/dev/null 2>&1; then
        apt-get update -qq && apt-get install -y -qq docker-compose-plugin
    else
        die "No docker compose available and no apt-get to install it with."
    fi
    COMPOSE="docker compose"
fi
info "Using: $COMPOSE"

# --- 2. Survive reboots ----------------------------------------------------
# The container's restart policy only helps if the daemon itself comes back up.
if command -v systemctl >/dev/null 2>&1; then
    systemctl enable docker >/dev/null 2>&1 || warn "Could not enable the docker service."
    systemctl start docker  >/dev/null 2>&1 || true
    info "docker.service enabled: $(systemctl is-enabled docker 2>/dev/null || echo unknown)"
fi

# --- 3. Code ---------------------------------------------------------------
command -v git >/dev/null 2>&1 || {
    info "Installing git…"
    apt-get update -qq && apt-get install -y -qq git
}

if [ -d "$APP_DIR/.git" ]; then
    info "Updating existing checkout at $APP_DIR…"
    git -C "$APP_DIR" fetch --depth 1 origin "$BRANCH"
    git -C "$APP_DIR" reset --hard "origin/$BRANCH"
else
    info "Cloning $REPO_URL into $APP_DIR…"
    mkdir -p "$(dirname "$APP_DIR")"
    git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
fi
cd "$APP_DIR"

# --- 4. Secrets ------------------------------------------------------------
# .env is gitignored, so a fresh clone never has one. It also survives `git reset`
# above, which is exactly what we want on re-deploys.
if [ ! -f "$APP_DIR/.env" ]; then
    cp "$APP_DIR/.env.example" "$APP_DIR/.env"
    chmod 600 "$APP_DIR/.env"
    warn "Created $APP_DIR/.env from the template."
    warn "Fill in TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID, then re-run this script."
    exit 1
fi
chmod 600 "$APP_DIR/.env"

if ! grep -qE '^TELEGRAM_BOT_TOKEN=.+' "$APP_DIR/.env"; then
    die "TELEGRAM_BOT_TOKEN is empty in $APP_DIR/.env — fill it in and re-run."
fi

# --- 5. Build & run --------------------------------------------------------
info "Building the image…"
$COMPOSE build --pull

info "Starting the container…"
$COMPOSE up -d

# --- 6. Report -------------------------------------------------------------
sleep 5
info "Container status:"
docker ps --filter name=ev-hunter --format 'table {{.Names}}\t{{.Status}}\t{{.Image}}'

cat <<EOF

$(info "Deployed.")

  Follow the live scan   : docker logs -f ev-hunter
  Check it is alive      : docker ps --filter name=ev-hunter
  Database stats         : docker exec ev-hunter python /app/ev_hunter.py --stats
  Send a Telegram test   : docker exec ev-hunter python /app/ev_hunter.py --test-telegram
  Edit filters           : docker run --rm -v ev-hunter-data:/data -it busybox vi /data/config.json
  Restart after edits    : cd $APP_DIR && $COMPOSE restart
  Update to latest code  : bash $APP_DIR/deploy.sh

EOF
