#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The Telegram front end: registration, brand subscriptions and admin controls."""

from __future__ import annotations

import time
from datetime import datetime

import botdb
import brands as brandlib
from telegram_api import Telegram, esc

BRANDS_PER_PAGE = 12          # 6 rows of 2 - fits without scrolling on a phone
LATEST_ON_START = 5


# ------------------------------------------------------------------- rendering ---

def fmt_money(value) -> str:
    return f"${value:,}".replace(",", " ") if value else "price on request"


def fmt_km(value) -> str:
    if value is None:
        return "mileage n/a"
    return "0 km (new)" if value == 0 else f"{value:,} km".replace(",", " ")


def render_listing(row: dict, index: int | None = None) -> str:
    head = f"<b>{index}.</b> " if index else ""
    title = esc((row.get("title") or "Listing")[:90])
    lines = [f"{head}🔋 <a href=\"{esc(row.get('url'))}\">{title}</a>"]

    facts = [f"💵 <b>{fmt_money(row.get('price_usd'))}</b>"]
    if row.get("year"):
        facts.append(f"📅 {row['year']}")
    facts.append(f"🛣 {fmt_km(row.get('mileage_km'))}")
    lines.append("      " + "  ·  ".join(facts))

    extras = []
    if row.get("brand"):
        extras.append(f"🏭 {esc(row['brand'])}")
    if row.get("city"):
        extras.append(f"📍 {esc(str(row['city'])[:40])}")
    extras.append(f"🏷 {esc(row.get('source') or '')}")
    lines.append("      " + "  ·  ".join(extras))
    if row.get("tier") == "stretch":
        lines.append("      <i>⚠️ stretch match — check the details</i>")
    return "\n".join(lines)


def render_user_card(user: dict, title: str = "New user") -> str:
    name = " ".join(filter(None, [user.get("first_name"), user.get("last_name")])) or "—"
    username = f"@{user['username']}" if user.get("username") else "—"
    joined = (user.get("joined_at") or "")[:16].replace("T", " ")
    flag = "🚫 BLOCKED" if user.get("blocked") else "✅ active"
    return (
        f"👤 <b>{esc(title)}</b>\n"
        f"<code>─────────────────────</code>\n"
        f"<b>Name</b>      {esc(name)}\n"
        f"<b>Username</b>  {esc(username)}\n"
        f"<b>Phone</b>     <code>{esc(user.get('phone') or '—')}</code>\n"
        f"<b>ID</b>        <code>{user.get('tg_id')}</code>\n"
        f"<b>Language</b>  {esc(user.get('language_code') or '—')}\n"
        f"<b>Premium</b>   {'⭐ yes' if user.get('is_premium') else 'no'}\n"
        f"<b>Joined</b>    {esc(joined)}\n"
        f"<b>Status</b>    {flag}"
    )


# -------------------------------------------------------------------- keyboards ---

def contact_keyboard() -> dict:
    return {"keyboard": [[{"text": "📱 Share my phone number", "request_contact": True}]],
            "resize_keyboard": True, "one_time_keyboard": True}


def brand_keyboard(tg_id: int, page: int = 0) -> dict:
    chosen = botdb.get_brands(tg_id)
    names = brandlib.BRAND_NAMES
    pages = max(1, (len(names) + BRANDS_PER_PAGE - 1) // BRANDS_PER_PAGE)
    page = max(0, min(page, pages - 1))
    start = page * BRANDS_PER_PAGE

    rows, row = [], []
    for idx in range(start, min(start + BRANDS_PER_PAGE, len(names))):
        name = names[idx]
        mark = "✅ " if name in chosen else ""
        row.append({"text": f"{mark}{name}", "callback_data": f"b:{idx}:{page}"})
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    nav = []
    if page > 0:
        nav.append({"text": "◀️", "callback_data": f"p:{page - 1}"})
    nav.append({"text": f"{page + 1}/{pages}", "callback_data": "noop"})
    if page < pages - 1:
        nav.append({"text": "▶️", "callback_data": f"p:{page + 1}"})
    rows.append(nav)

    rows.append([{"text": "🌍 All brands", "callback_data": f"all:{page}"},
                 {"text": "🧹 Clear", "callback_data": f"none:{page}"}])
    rows.append([{"text": "✅ Done", "callback_data": "done"}])
    return {"inline_keyboard": rows}


def admin_keyboard(tg_id: int, blocked: bool) -> dict:
    button = ({"text": "♻️ Unblock", "callback_data": f"adm:unblock:{tg_id}"} if blocked
              else {"text": "🚫 Block", "callback_data": f"adm:block:{tg_id}"})
    return {"inline_keyboard": [[button]]}


# -------------------------------------------------------------------- the bot ---

class Bot:
    def __init__(self, cfg: dict, log):
        self.cfg = cfg
        self.log = log
        self.tg = Telegram(cfg["telegram"]["bot_token"], logger=log)
        admin = str(cfg["telegram"].get("admin_chat_id")
                    or cfg["telegram"].get("chat_id") or "").strip()
        self.admin_id = int(admin) if admin.lstrip("-").isdigit() else None
        self.max_per_push = int(cfg["runtime"].get("max_items_per_message", 5))

    # ---- outbound -------------------------------------------------------------

    def notify_admin_new_user(self, user: dict) -> None:
        if not self.admin_id:
            return
        self.tg.send(self.admin_id, render_user_card(user, "New user joined"),
                     reply_markup=admin_keyboard(user["tg_id"], bool(user.get("blocked"))))

    def send_listings(self, tg_id: int, rows: list[dict], header: str) -> list[str]:
        """Send listings in chunks. Returns the keys that were actually delivered."""
        delivered: list[str] = []
        chunk = max(1, self.max_per_push)
        for start in range(0, len(rows), chunk):
            batch = rows[start:start + chunk]
            parts = [header] if start == 0 else ["🚘 <b>…continued</b>"]
            for offset, row in enumerate(batch, start=start + 1):
                parts.append(render_listing(row, offset))
            if self.tg.send(tg_id, "\n\n".join(parts)) is None:
                self.log(f"delivery to {tg_id} failed; will retry next cycle", "WARN")
                break
            delivered += [r["key"] for r in batch]
            time.sleep(0.6)
        return delivered

    # ---- inbound --------------------------------------------------------------

    def handle_update(self, update: dict) -> None:
        if "message" in update:
            self.handle_message(update["message"])
        elif "callback_query" in update:
            self.handle_callback(update["callback_query"])

    def handle_message(self, msg: dict) -> None:
        chat_id = (msg.get("chat") or {}).get("id")
        tg_user = msg.get("from") or {}
        if not chat_id or not tg_user.get("id"):
            return

        is_admin = self.admin_id is not None and tg_user["id"] == self.admin_id
        result = botdb.upsert_user(tg_user, is_admin=is_admin)
        user = result["user"]

        if user.get("blocked"):
            self.tg.send(chat_id, "🚫 Your access to this bot has been disabled.")
            return

        # Phone number arrives as a contact attachment.
        contact = msg.get("contact")
        if contact:
            if contact.get("user_id") and contact["user_id"] != tg_user["id"]:
                self.tg.send(chat_id, "Please share <b>your own</b> number using the button.",
                             reply_markup=contact_keyboard())
                return
            botdb.set_user_field(tg_user["id"], "phone", contact.get("phone_number"))
            botdb.set_user_field(tg_user["id"], "state", "active")
            fresh = botdb.get_user(tg_user["id"])
            self.tg.send(chat_id,
                         "✅ Thanks! You're registered.\n\n"
                         "Now pick the brands you want to hear about 👇",
                         reply_markup={"remove_keyboard": True})
            self.tg.send(chat_id, self.brand_prompt(),
                         reply_markup=brand_keyboard(tg_user["id"], 0))
            self.notify_admin_new_user(fresh)
            return

        text = (msg.get("text") or "").strip()
        command = text.split()[0].lower().lstrip("/").split("@")[0] if text else ""

        if command == "start":
            if user.get("state") != "active" or not user.get("phone"):
                self.tg.send(
                    chat_id,
                    "👋 <b>Welcome to EV Hunter</b>\n\n"
                    "I watch olx.uz, avtoelon.uz and avto.uz around the clock and send you "
                    "new car listings the moment they appear.\n\n"
                    "To get started, please share your phone number 👇",
                    reply_markup=contact_keyboard())
                return
            self.cmd_latest(chat_id, user)
            self.tg.send(chat_id, self.brand_prompt(),
                         reply_markup=brand_keyboard(tg_user["id"], 0))
        elif command in ("brands", "cars", "mycars"):
            self.tg.send(chat_id, self.brand_prompt(),
                         reply_markup=brand_keyboard(tg_user["id"], 0))
        elif command == "latest":
            self.cmd_latest(chat_id, user)
        elif command == "stop":
            botdb.set_user_field(tg_user["id"], "state", "paused")
            self.tg.send(chat_id, "🔕 Paused. Send /start to resume.")
        elif command == "help":
            self.tg.send(chat_id,
                         "<b>Commands</b>\n"
                         "/latest — the newest listings\n"
                         "/brands — choose which brands to follow\n"
                         "/stop — pause notifications\n"
                         "/start — resume")
        elif command == "admin" and is_admin:
            self.cmd_admin(chat_id)
        else:
            self.tg.send(chat_id, "Use /latest, /brands or /help.")

    def brand_prompt(self) -> str:
        return ("🚗 <b>Which brands should I watch?</b>\n"
                "<i>Tap to select — pick as many as you like. "
                "Selecting none means you get everything.</i>")

    def cmd_latest(self, chat_id: int, user: dict) -> None:
        chosen = botdb.get_brands(user["tg_id"])
        rows = botdb.latest_for(user["tg_id"], chosen, LATEST_ON_START)
        if not rows:
            self.tg.send(chat_id, "Nothing in the catalogue yet — the next scan will fill it.")
            return
        scope = ", ".join(sorted(chosen)) if chosen else "all brands"
        header = f"🚘 <b>Latest {len(rows)} listings</b>\n<i>{esc(scope)}</i>"
        self.send_listings(chat_id, rows, header)

    def cmd_admin(self, chat_id: int) -> None:
        s = botdb.stats()
        lines = [f"📊 <b>Bot stats</b>",
                 f"Users: {s['users']}  ·  active: {s['active']}  ·  blocked: {s['blocked']}",
                 f"Listings: {s['listings']}  ·  deliveries: {s['deliveries']}", ""]
        for u in botdb.all_users()[:20]:
            name = " ".join(filter(None, [u.get("first_name"), u.get("last_name")])) or "—"
            tag = "🚫" if u.get("blocked") else "✅"
            lines.append(f"{tag} {esc(name)} · <code>{u.get('phone') or '—'}</code> "
                         f"· <code>{u['tg_id']}</code>")
        self.tg.send(chat_id, "\n".join(lines))

    def handle_callback(self, cq: dict) -> None:
        data = cq.get("data") or ""
        cq_id = cq.get("id")
        tg_user = cq.get("from") or {}
        message = cq.get("message") or {}
        chat_id = (message.get("chat") or {}).get("id")
        message_id = message.get("message_id")
        tg_id = tg_user.get("id")
        if not tg_id:
            return

        # ---- admin actions ----
        if data.startswith("adm:"):
            if self.admin_id is None or tg_id != self.admin_id:
                self.tg.answer_callback(cq_id, "Not allowed.", alert=True)
                return
            _, action, target = data.split(":", 2)
            target_id = int(target)
            botdb.set_user_field(target_id, "blocked", 1 if action == "block" else 0)
            victim = botdb.get_user(target_id)
            if victim:
                self.tg.edit(chat_id, message_id,
                             render_user_card(victim, "New user joined"),
                             reply_markup=admin_keyboard(target_id, bool(victim["blocked"])))
            self.tg.answer_callback(
                cq_id, "Blocked." if action == "block" else "Unblocked.")
            return

        if data == "noop":
            self.tg.answer_callback(cq_id)
            return

        # ---- brand picker ----
        if data.startswith("b:"):
            _, idx, page = data.split(":")
            name = brandlib.brand_by_id(int(idx))
            if name:
                selected = botdb.toggle_brand(tg_id, name)
                self.tg.answer_callback(cq_id, f"{'Added' if selected else 'Removed'} {name}")
                self.tg.edit_markup(chat_id, message_id,
                                    reply_markup=brand_keyboard(tg_id, int(page)))
            return

        if data.startswith("p:"):
            page = int(data.split(":")[1])
            self.tg.edit_markup(chat_id, message_id,
                                reply_markup=brand_keyboard(tg_id, page))
            self.tg.answer_callback(cq_id)
            return

        if data.startswith("all:"):
            botdb.set_brands(tg_id, list(brandlib.BRAND_NAMES))
            self.tg.answer_callback(cq_id, "All brands selected")
            self.tg.edit_markup(chat_id, message_id,
                                reply_markup=brand_keyboard(tg_id, int(data.split(":")[1])))
            return

        if data.startswith("none:"):
            botdb.set_brands(tg_id, [])
            self.tg.answer_callback(cq_id, "Cleared")
            self.tg.edit_markup(chat_id, message_id,
                                reply_markup=brand_keyboard(tg_id, int(data.split(":")[1])))
            return

        if data == "done":
            chosen = botdb.get_brands(tg_id)
            scope = ", ".join(sorted(chosen)) if chosen else "every brand"
            self.tg.edit(chat_id, message_id,
                         f"✅ <b>Saved.</b>\nYou'll get new listings for: <b>{esc(scope)}</b>\n\n"
                         f"<i>Change any time with /brands.</i>")
            self.tg.answer_callback(cq_id, "Saved")
            return

        self.tg.answer_callback(cq_id)

    # ---- poll loop ------------------------------------------------------------

    def poll_forever(self) -> None:
        self.tg.delete_webhook()
        offset = None
        saved = botdb.get_meta("update_offset")
        if saved and str(saved).isdigit():
            offset = int(saved)
        self.log("Bot polling started.")
        while True:
            try:
                updates = self.tg.get_updates(offset=offset, poll_timeout=30)
                for update in updates or []:
                    offset = update["update_id"] + 1
                    try:
                        self.handle_update(update)
                    except Exception as exc:  # noqa: BLE001 - one bad update must not stop the bot
                        self.log(f"update {update.get('update_id')} failed: "
                                 f"{type(exc).__name__}: {exc}", "ERROR")
                    botdb.set_meta("update_offset", offset)
            except Exception as exc:  # noqa: BLE001
                self.log(f"poll loop error: {type(exc).__name__}: {exc}", "ERROR")
                time.sleep(5)
