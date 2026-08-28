#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""EV Hunter service: the Telegram bot and the scanner, side by side.

Two threads in one process:
  * the bot polls Telegram for commands and button presses;
  * the scanner sweeps the marketplaces on an interval and fans new listings out to
    every subscriber according to the brands they picked.

They share one SQLite database in WAL mode.
"""

from __future__ import annotations

import os
import sys
import threading
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bot as botmod          # noqa: E402
import botdb                  # noqa: E402
import brands as brandlib     # noqa: E402
import locations as loclib    # noqa: E402
import models as modellib     # noqa: E402
import ev_hunter as ev        # noqa: E402


def scan_cycle(cfg: dict, bot: botmod.Bot) -> None:
    """One sweep: refresh the catalogue, then deliver to each subscriber."""
    matches, diag = ev.collect_matches(cfg)

    fresh = 0
    for tier, listing in matches:
        brand = brandlib.detect_brand(listing.title, listing.blob)
        model = modellib.detect_model(brand, listing.title, listing.blob)
        region = loclib.detect_location(listing.city)
        if botdb.upsert_listing(listing, brand, tier, model, region):
            fresh += 1
    ev.log(f"Catalogue: {fresh} new of {len(matches)} matches.")

    users = botdb.active_users()
    if not users:
        ev.log("No active subscribers yet — nothing to deliver.")
        botdb.set_meta("last_run", botdb.now_iso())
        return

    per_user = int(cfg["runtime"].get("max_new_per_user_per_cycle", 10))
    for user in users:
        chosen = botdb.get_brands(user["tg_id"])
        rows = botdb.undelivered_for(user["tg_id"], chosen, per_user)
        if not rows:
            continue
        scope = bot.scope_text(user["tg_id"], chosen)
        header = botmod.T["new_header"].format(n=len(rows), scope=botmod.esc(scope))
        delivered = bot.send_listings(user["tg_id"], rows, header)
        botdb.mark_sent(user["tg_id"], delivered)
        if delivered:
            ev.log(f"  sent {len(delivered)} to {user['tg_id']}")

    botdb.set_meta("last_run", botdb.now_iso())


def scanner_loop(cfg: dict, bot: botmod.Bot) -> None:
    interval = max(5, int(cfg["runtime"].get("interval_minutes", 60))) * 60
    while True:
        started = time.time()
        try:
            scan_cycle(cfg, bot)
        except Exception as exc:  # noqa: BLE001 - the loop must outlive any single failure
            ev.log(f"Scan crashed: {type(exc).__name__}: {exc}", "ERROR")
            ev.log(traceback.format_exc(), "DEBUG")
        sleep_for = max(60, interval - (time.time() - started))
        ev.log(f"Next scan in {sleep_for / 60:.0f} minutes.")
        time.sleep(sleep_for)


def main() -> int:
    cfg = ev.load_config()
    if not cfg["telegram"]["bot_token"]:
        ev.log("TELEGRAM_BOT_TOKEN is not set.", "ERROR")
        return 1

    bot = botmod.Bot(cfg, ev.log)
    botdb.init(admin_id=bot.admin_id)
    ev.log(f"Admin chat id: {bot.admin_id}")
    ev.log(f"Brands available: {len(brandlib.BRAND_NAMES)}")
    ev.log(f"Subscribers: {botdb.stats()}")

    poller = threading.Thread(target=bot.poll_forever, name="telegram", daemon=True)
    poller.start()

    scanner = threading.Thread(target=scanner_loop, args=(cfg, bot),
                               name="scanner", daemon=True)
    scanner.start()

    # Keep the main thread alive, and notice if either worker dies.
    while True:
        time.sleep(30)
        if not poller.is_alive():
            ev.log("Telegram poller died — restarting the container.", "ERROR")
            return 1
        if not scanner.is_alive():
            ev.log("Scanner died — restarting the container.", "ERROR")
            return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
