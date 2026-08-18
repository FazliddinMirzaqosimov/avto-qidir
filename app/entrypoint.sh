#!/bin/sh
# Seed the persistent volume on first start, then hand over to the service.
set -eu

DATA_DIR="${EV_HUNTER_DATA_DIR:-/data}"
mkdir -p "$DATA_DIR"

if [ ! -f "$DATA_DIR/config.json" ]; then
    cp /app/config.default.json "$DATA_DIR/config.json"
    echo "[entrypoint] seeded $DATA_DIR/config.json from the image default"
fi

if [ -z "${TELEGRAM_BOT_TOKEN:-}" ]; then
    echo "[entrypoint] WARNING: TELEGRAM_BOT_TOKEN is not set."
    echo "[entrypoint] Put it in .env next to docker-compose.yml, then: docker compose up -d"
fi
if [ -z "${ADMIN_CHAT_ID:-}" ] && [ -z "${TELEGRAM_CHAT_ID:-}" ]; then
    echo "[entrypoint] WARNING: no admin id set - new-user cards will not be delivered."
fi

# "service" (default) runs the bot + scanner. Anything else is passed to the old CLI,
# so `docker exec ev-hunter python /app/ev_hunter.py --stats` style calls still work.
if [ "${1:-service}" = "service" ]; then
    exec python /app/main.py
fi
exec python /app/ev_hunter.py "$@"
