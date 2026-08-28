#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One-off announcement sender.

    docker exec ev-hunter python /app/broadcast.py --key announce_mileage
    docker exec ev-hunter python /app/broadcast.py --key announce_mileage --send

Sends the named bot.T[...] entry to every non-blocked subscriber. A chat that answers 400/403
is unreachable until the user starts the bot again, so it is reported, not retried.
"""

import sys
import time

sys.path.insert(0, "/app")

import bot as botmod          # noqa: E402
import botdb                  # noqa: E402
import ev_hunter as ev        # noqa: E402
from telegram_api import Telegram  # noqa: E402


def main() -> int:
    send = "--send" in sys.argv
    key = "announce"
    if "--key" in sys.argv:
        key = sys.argv[sys.argv.index("--key") + 1]
    if key not in botmod.T:
        print(f"no such message key: {key!r}")
        return 1
    cfg = ev.load_config()
    botdb.init()
    tg = Telegram(cfg["telegram"]["bot_token"], logger=ev.log)
    text = botmod.T[key]

    targets = [u for u in botdb.all_users() if not u["blocked"]]
    print(f"{'SENDING to' if send else 'DRY RUN -'} {len(targets)} subscriber(s)\n")
    if not send:
        print(text)
        print("\n-- re-run with --send to deliver --")
        for u in targets:
            print(f"  would send to {u['tg_id']} {u.get('first_name')}")
        return 0

    ok = failed = 0
    for u in targets:
        result, error = tg.send_checked(u["tg_id"], text)
        if result:
            ok += 1
            print(f"  ok        {u['tg_id']} {u.get('first_name')}")
        else:
            failed += 1
            print(f"  FAILED {error} {u['tg_id']} {u.get('first_name')}")
        time.sleep(0.4)          # stay well inside Telegram's rate limit
    print(f"\ndelivered {ok}, failed {failed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
