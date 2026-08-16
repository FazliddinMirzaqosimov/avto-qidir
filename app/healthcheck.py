#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Container healthcheck: is the scanner still completing runs?

`last_run` is written only after a scan finishes without a delivery failure, so a stale
value means either the loop died or Telegram has been unreachable for hours. Exit 0 =
healthy, exit 1 = unhealthy (docker restarts nothing on its own, but `docker ps` and any
monitoring will show it).
"""

import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

DATA_DIR = os.environ.get("EV_HUNTER_DATA_DIR", "/data")
DB_PATH = os.path.join(DATA_DIR, "ev_hunter.db")
TASHKENT_TZ = timezone(timedelta(hours=5))

# Allow three missed cycles before shouting.
interval = int(os.environ.get("EV_HUNTER_INTERVAL_MINUTES", "60") or 60)
max_age = timedelta(minutes=max(interval, 5) * 3 + 15)


def main() -> int:
    if not os.path.exists(DB_PATH):
        print("no database yet")
        return 1
    try:
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=5)
        row = conn.execute("SELECT value FROM meta WHERE key='last_run'").fetchone()
        conn.close()
    except sqlite3.Error as exc:
        print(f"database unreadable: {exc}")
        return 1

    if not row or not row[0]:
        print("no completed scan recorded yet")
        return 1

    try:
        last = datetime.fromisoformat(row[0])
    except ValueError:
        print(f"unparsable last_run: {row[0]!r}")
        return 1
    if last.tzinfo is None:
        last = last.replace(tzinfo=TASHKENT_TZ)

    age = datetime.now(TASHKENT_TZ) - last
    if age > max_age:
        print(f"last successful scan was {age.total_seconds() / 3600:.1f}h ago")
        return 1
    print(f"ok - last scan {age.total_seconds() / 60:.0f} min ago")
    return 0


if __name__ == "__main__":
    sys.exit(main())
