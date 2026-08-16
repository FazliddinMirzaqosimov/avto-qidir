#!/bin/sh
# Seed the persistent volume on first start, then hand over to the scanner.
set -eu

DATA_DIR="${EV_HUNTER_DATA_DIR:-/data}"
mkdir -p "$DATA_DIR"

if [ ! -f "$DATA_DIR/config.json" ]; then
    cp /app/config.default.json "$DATA_DIR/config.json"
    echo "[entrypoint] seeded $DATA_DIR/config.json from the image default"
fi

if [ -z "${TELEGRAM_BOT_TOKEN:-}" ] || [ -z "${TELEGRAM_CHAT_ID:-}" ]; then
    echo "[entrypoint] WARNING: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID are not set."
    echo "[entrypoint] Put them in .env next to docker-compose.yml, then: docker compose up -d"
fi

exec python /app/ev_hunter.py "$@"
