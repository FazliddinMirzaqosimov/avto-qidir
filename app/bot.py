#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The Telegram front end: registration, brand subscriptions and admin controls.

Every subscriber-facing string is in Uzbek Cyrillic (ўзбекча, кирилл).
"""

from __future__ import annotations

import hashlib
import time

import botdb
import brands as brandlib
from telegram_api import Telegram, esc

BRANDS_PER_PAGE = 12          # 6 rows of 2 - fits without scrolling on a phone
LATEST_ON_START = 5

# --------------------------------------------------------------------------- texts ---

T = {
    "welcome": (
        "👋 <b>EV Hunter'га хуш келибсиз!</b>\n\n"
        "Мен olx.uz, avtoelon.uz ва avto.uz сайтларини тинимсиз кузатиб бораман ва янги "
        "эълон пайдо бўлиши биланоқ сизга юбораман.\n\n"
        "Бошлаш учун телефон рақамингизни юборинг 👇"),
    "share_phone": "📱 Телефон рақамимни юбориш",
    "own_number": "Илтимос, тугма орқали <b>ўзингизнинг</b> рақамингизни юборинг.",
    "registered": ("✅ Раҳмат! Сиз рўйхатдан ўтдингиз.\n\n"
                   "Энди қайси брендлар қизиқтиришини танланг 👇"),
    "blocked": "🚫 Сизнинг ботдан фойдаланиш ҳуқуқингиз тўхтатилган.",
    "brand_prompt": ("🚗 <b>Қайси брендларни кузатай?</b>\n"
                     "<i>Танлаш учун устига босинг — хоҳлаганингизча танласангиз бўлади. "
                     "Ҳеч нарса танламасангиз, барча эълонлар юборилади.</i>"),
    "all_brands": "🌍 Барча брендлар",
    "clear": "🧹 Тозалаш",
    "done": "✅ Тайёр",
    "saved_cb": "Сақланди",
    "cleared_cb": "Тозаланди",
    "all_selected_cb": "Барча брендлар танланди",
    "added": "{name} қўшилди",
    "removed": "{name} олиб ташланди",
    "saved": ("✅ <b>Сақланди.</b>\n"
              "Сизга қуйидагилар бўйича янги эълонлар келади: <b>{scope}</b>\n\n"
              "<i>Исталган вақтда /brands орқали ўзгартиришингиз мумкин.</i>"),
    "every_brand": "барча брендлар",
    "all_brands_scope": "барча брендлар",
    "empty_catalogue": "Ҳозирча каталогда ҳеч нарса йўқ — кейинги текширувдан сўнг тўлади.",
    "latest_header": "🚘 <b>Сўнгги {n} та эълон</b>\n<i>{scope}</i>",
    "new_header": "🚘 <b>{n} та янги эълон</b>\n<i>{scope}</i>",
    "continued": "🚘 <b>…давоми</b>",
    "paused": "🔕 Хабарлар тўхтатилди. Давом эттириш учун /start юборинг.",
    "help": ("<b>Буйруқлар</b>\n"
             "/latest — энг сўнгги эълонлар\n"
             "/brands — кузатиладиган брендларни танлаш\n"
             "/stop — хабарларни тўхтатиш\n"
             "/start — қайта бошлаш"),
    "unknown": "/latest, /brands ёки /help буйруқларидан фойдаланинг.",
    "not_allowed": "Рухсат йўқ.",
    "blocked_cb": "Блокланди.",
    "unblocked_cb": "Блокдан чиқарилди.",
    "block_btn": "🚫 Блоклаш",
    "unblock_btn": "♻️ Блокдан чиқариш",
    "new_user": "Янги фойдаланувчи қўшилди",
    "price_on_request": "нархи келишилади",
    "mileage_na": "юриши номаълум",
    "km_new": "0 км (янги)",
    "listing_fallback": "Эълон",
    "stretch": "⚠️ чегарадаги мослик — маълумотларни текширинг",
}

BOT_COMMANDS = [
    {"command": "latest", "description": "Энг сўнгги эълонлар"},
    {"command": "brands", "description": "Брендларни танлаш"},
    {"command": "stop", "description": "Хабарларни тўхтатиш"},
    {"command": "start", "description": "Қайта бошлаш"},
    {"command": "help", "description": "Ёрдам"},
]


# ------------------------------------------------------------------- rendering ---

def fmt_money(value) -> str:
    return f"${value:,}".replace(",", " ") if value else T["price_on_request"]


def fmt_km(value) -> str:
    if value is None:
        return T["mileage_na"]
    return T["km_new"] if value == 0 else f"{value:,} км".replace(",", " ")


def render_listing(row: dict, index: int | None = None) -> str:
    head = f"<b>{index}.</b> " if index else ""
    title = esc((row.get("title") or T["listing_fallback"])[:90])
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
        lines.append(f"      <i>{T['stretch']}</i>")
    return "\n".join(lines)


def render_user_card(user: dict, title: str | None = None) -> str:
    title = title or T["new_user"]
    name = " ".join(filter(None, [user.get("first_name"), user.get("last_name")])) or "—"
    username = f"@{user['username']}" if user.get("username") else "—"
    joined = (user.get("joined_at") or "")[:16].replace("T", " ")
    status = "🚫 БЛОКЛАНГАН" if user.get("blocked") else "✅ фаол"
    return (
        f"👤 <b>{esc(title)}</b>\n"
        f"<code>─────────────────────</code>\n"
        f"<b>Исм:</b> {esc(name)}\n"
        f"<b>Логин:</b> {esc(username)}\n"
        f"<b>Телефон:</b> <code>{esc(user.get('phone') or '—')}</code>\n"
        f"<b>ID:</b> <code>{user.get('tg_id')}</code>\n"
        f"<b>Тил:</b> {esc(user.get('language_code') or '—')}\n"
        f"<b>Премиум:</b> {'⭐ ҳа' if user.get('is_premium') else 'йўқ'}\n"
        f"<b>Қўшилган сана:</b> {esc(joined)}\n"
        f"<b>Ҳолат:</b> {status}"
    )


# -------------------------------------------------------------------- keyboards ---

def contact_keyboard() -> dict:
    return {"keyboard": [[{"text": T["share_phone"], "request_contact": True}]],
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

    rows.append([{"text": T["all_brands"], "callback_data": f"all:{page}"},
                 {"text": T["clear"], "callback_data": f"none:{page}"}])
    rows.append([{"text": T["done"], "callback_data": "done"}])
    return {"inline_keyboard": rows}


def admin_keyboard(tg_id: int, blocked: bool) -> dict:
    button = ({"text": T["unblock_btn"], "callback_data": f"adm:unblock:{tg_id}"} if blocked
              else {"text": T["block_btn"], "callback_data": f"adm:block:{tg_id}"})
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
        self.tg.send(self.admin_id, render_user_card(user),
                     reply_markup=admin_keyboard(user["tg_id"], bool(user.get("blocked"))))

    # Telegram cannot open a conversation the user never started. After a bot-token swap
    # every previously-registered chat answers 400 "chat not found", and a user who blocks
    # the bot answers 403. Neither clears on its own, so retrying every cycle forever just
    # fills the log - park the subscriber instead until they press Start again.
    UNREACHABLE = (400, 403)

    def send_listings(self, tg_id: int, rows: list[dict], header: str) -> list[str]:
        """Send listings in chunks. Returns the keys actually delivered."""
        delivered: list[str] = []
        chunk = max(1, self.max_per_push)
        for start in range(0, len(rows), chunk):
            batch = rows[start:start + chunk]
            parts = [header] if start == 0 else [T["continued"]]
            for offset, row in enumerate(batch, start=start + 1):
                parts.append(render_listing(row, offset))
            result, error = self.tg.send_checked(tg_id, "\n\n".join(parts))
            if result is None:
                if error in self.UNREACHABLE:
                    botdb.set_user_field(tg_id, "state", "new")
                    self.log(f"{tg_id} is unreachable (Telegram {error}) — parked until "
                             f"they send /start again.", "WARN")
                else:
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
            self.tg.send(chat_id, T["blocked"])
            return

        contact = msg.get("contact")
        if contact:
            if contact.get("user_id") and contact["user_id"] != tg_user["id"]:
                self.tg.send(chat_id, T["own_number"], reply_markup=contact_keyboard())
                return
            botdb.set_user_field(tg_user["id"], "phone", contact.get("phone_number"))
            botdb.set_user_field(tg_user["id"], "state", "active")
            fresh = botdb.get_user(tg_user["id"])
            self.tg.send(chat_id, T["registered"], reply_markup={"remove_keyboard": True})
            self.tg.send(chat_id, T["brand_prompt"],
                         reply_markup=brand_keyboard(tg_user["id"], 0))
            self.notify_admin_new_user(fresh)
            return

        text = (msg.get("text") or "").strip()
        command = text.split()[0].lower().lstrip("/").split("@")[0] if text else ""

        if command == "start":
            if user.get("state") != "active" or not user.get("phone"):
                self.tg.send(chat_id, T["welcome"], reply_markup=contact_keyboard())
                return
            self.cmd_latest(chat_id, user)
            self.tg.send(chat_id, T["brand_prompt"],
                         reply_markup=brand_keyboard(tg_user["id"], 0))
        elif command in ("brands", "cars", "mycars"):
            self.tg.send(chat_id, T["brand_prompt"],
                         reply_markup=brand_keyboard(tg_user["id"], 0))
        elif command == "latest":
            self.cmd_latest(chat_id, user)
        elif command == "stop":
            botdb.set_user_field(tg_user["id"], "state", "paused")
            self.tg.send(chat_id, T["paused"])
        elif command == "help":
            self.tg.send(chat_id, T["help"])
        elif command == "admin" and is_admin:
            self.cmd_admin(chat_id)
        else:
            self.tg.send(chat_id, T["unknown"])

    def cmd_latest(self, chat_id: int, user: dict) -> None:
        chosen = botdb.get_brands(user["tg_id"])
        rows = botdb.latest_for(user["tg_id"], chosen, LATEST_ON_START)
        if not rows:
            self.tg.send(chat_id, T["empty_catalogue"])
            return
        scope = ", ".join(sorted(chosen)) if chosen else T["all_brands_scope"]
        header = T["latest_header"].format(n=len(rows), scope=esc(scope))
        self.send_listings(chat_id, rows, header)

    def cmd_admin(self, chat_id: int) -> None:
        s = botdb.stats()
        lines = ["📊 <b>Бот статистикаси</b>",
                 f"Фойдаланувчилар: {s['users']}  ·  фаол: {s['active']}  ·  "
                 f"блокланган: {s['blocked']}",
                 f"Эълонлар: {s['listings']}  ·  юборилган: {s['deliveries']}", ""]
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

        if data.startswith("adm:"):
            if self.admin_id is None or tg_id != self.admin_id:
                self.tg.answer_callback(cq_id, T["not_allowed"], alert=True)
                return
            _, action, target = data.split(":", 2)
            target_id = int(target)
            botdb.set_user_field(target_id, "blocked", 1 if action == "block" else 0)
            victim = botdb.get_user(target_id)
            if victim:
                self.tg.edit(chat_id, message_id, render_user_card(victim),
                             reply_markup=admin_keyboard(target_id, bool(victim["blocked"])))
            self.tg.answer_callback(
                cq_id, T["blocked_cb"] if action == "block" else T["unblocked_cb"])
            return

        if data == "noop":
            self.tg.answer_callback(cq_id)
            return

        if data.startswith("b:"):
            _, idx, page = data.split(":")
            name = brandlib.brand_by_id(int(idx))
            if name:
                selected = botdb.toggle_brand(tg_id, name)
                key = "added" if selected else "removed"
                self.tg.answer_callback(cq_id, T[key].format(name=name))
                self.tg.edit_markup(chat_id, message_id,
                                    reply_markup=brand_keyboard(tg_id, int(page)))
            return

        if data.startswith("p:"):
            self.tg.edit_markup(chat_id, message_id,
                                reply_markup=brand_keyboard(tg_id, int(data.split(":")[1])))
            self.tg.answer_callback(cq_id)
            return

        if data.startswith("all:"):
            botdb.set_brands(tg_id, list(brandlib.BRAND_NAMES))
            self.tg.answer_callback(cq_id, T["all_selected_cb"])
            self.tg.edit_markup(chat_id, message_id,
                                reply_markup=brand_keyboard(tg_id, int(data.split(":")[1])))
            return

        if data.startswith("none:"):
            botdb.set_brands(tg_id, [])
            self.tg.answer_callback(cq_id, T["cleared_cb"])
            self.tg.edit_markup(chat_id, message_id,
                                reply_markup=brand_keyboard(tg_id, int(data.split(":")[1])))
            return

        if data == "done":
            chosen = botdb.get_brands(tg_id)
            scope = ", ".join(sorted(chosen)) if chosen else T["every_brand"]
            self.tg.edit(chat_id, message_id, T["saved"].format(scope=esc(scope)))
            self.tg.answer_callback(cq_id, T["saved_cb"])
            return

        self.tg.answer_callback(cq_id)

    # ---- poll loop ------------------------------------------------------------

    def poll_forever(self) -> None:
        self.tg.delete_webhook()
        self.tg.call("setMyCommands", commands=BOT_COMMANDS)

        # update_id counters are per-bot. Carrying an old bot's offset over to a new token
        # would make getUpdates skip everything below it, so reset when the token changes.
        # Only a fingerprint is stored - never the token itself.
        fingerprint = hashlib.sha256(self.tg.token.encode("utf-8")).hexdigest()[:16]
        offset = None
        if botdb.get_meta("bot_token_fp") != fingerprint:
            botdb.set_meta("bot_token_fp", fingerprint)
            botdb.set_meta("update_offset", "")
            self.log("Bot token changed — update offset reset.")
        else:
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
