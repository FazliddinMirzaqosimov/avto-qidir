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
import carfilters as cf
import locations as loclib
import models as modellib
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
    "pick_brand_first_toast": "Аввал брендни танланг.",
    "models_btn": "🚙 Моделлар",
    "model_prompt": ("🚙 <b>{brand}</b> — қайси моделлар керак?\n"
                     "<i>Ҳеч бири танланмаса, ушбу бренднинг барча моделлари юборилади.</i>"),
    "pick_brand_first": ("⚠️ <b>Аввал брендни танлашингиз керак.</b>\n\n"
                         "Моделни танлаш учун дастлаб қайси бренд кераклигини "
                         "белгиланг — сўнг ўша бренднинг моделлари рўйхати очилади.\n\n"
                         "Қуйидан брендни танланг 👇"),
    # Different situation, different message: the subscriber DID pick a brand, that
    # brand simply has no model list yet. Telling them to "pick a brand first" here
    # is just confusing.
    "no_models_for_brands": ("ℹ️ Сиз танлаган бренд(лар) — <b>{brands}</b> — учун "
                             "моделлар рўйхати ҳозирча тузилмаган.\n\n"
                             "Хавотир олманг: бу брендларнинг <b>барча</b> эълонлари "
                             "сизга юборилаверади.\n\n"
                             "Модел бўйича танлаш учун моделлари мавжуд брендни "
                             "қўшишингиз мумкин 👇"),
    "no_models_toast": "Бу бренд учун моделлар рўйхати йўқ.",
    "choose_brand_for_models": ("🚙 <b>Модел танлаш</b>\n"
                                "<i>Қайси бренд ичидан модел танламоқчисиз?</i>"),
    "no_models": "Бу бренд учун моделлар рўйхати ҳозирча йўқ — барча эълонлар юборилади.",
    "back": "◀️ Орқага",
    "all_models": "🌍 Барча моделлар",
    "model_added": "{name} қўшилди",
    "model_removed": "{name} олиб ташланди",
    "models_cleared": "Барча моделлар (чеклов олиб ташланди)",
    "announce": (
        "🎉 <b>Янгилик: модел бўйича фильтр қўшилди!</b>\n\n"
        "Энди фақат брендни эмас, аниқ <b>моделни</b> ҳам танлашингиз мумкин — "
        "масалан, Chevrolet ичидан фақат <b>Onix</b>, ёки BYD ичидан фақат "
        "<b>Seagull</b>.\n\n"
        "Фильтрни тезроқ ва аниқроқ созлаш учун ҳозироқ синаб кўринг 👇\n"
        "/brands — брендни танланг, сўнг <b>🚙 Моделлар</b> тугмасини босинг."),
    "mileage_btn": "🛣 Юриш (км)",
    "mileage_prompt": ("🛣 <b>Қанча юрган машиналар керак?</b>\n"
                       "<i>Керакли оралиқларни белгиланг. Ҳеч нарса танланмаса, "
                       "барча оралиқлар юборилади.</i>"),
    "all_mileage": "🌍 Барчаси",
    "mileage_added": "{name} қўшилди",
    "mileage_removed": "{name} олиб ташланди",
    "mileage_cleared": "Барча оралиқлар (чеклов олиб ташланди)",
    "every_mileage": "барча оралиқлар",
    "announce_mileage": (
        "🎉 <b>Янгилик: юриш (км) бўйича фильтр қўшилди!</b>\n\n"
        "Энди машина қанча юрганини ҳам танлашингиз мумкин:\n"
        "🥇 50 000 км гача\n"
        "🥈 50 000 – 100 000 км\n"
        "🥉 100 000 – 150 000 км\n"
        "❔ Кўрсатилмаган\n\n"
        "Масалан, фақат кам юрган машиналарни кўрмоқчи бўлсангиз — "
        "<b>50 000 км гача</b> ни белгиланг, қолганлари юборилмайди.\n\n"
        "Ҳозироқ синаб кўринг 👇\n"
        "/mileage — юриш оралиғини танлаш\n"
        "/brands — бренд · /models — модел"),
    "year_btn": "📅 Йил",
    "year_prompt": ("📅 <b>Қайси йилги машиналар керак?</b>\n"
                    "<i>Керакли йилларни белгиланг. Ҳеч нарса танланмаса, "
                    "барча йиллар юборилади.</i>"),
    "year_added": "{name} қўшилди",
    "year_removed": "{name} олиб ташланди",
    "years_cleared": "Барча йиллар (чеклов олиб ташланди)",
    "every_year": "барча йиллар",
    "announce_filters": (
        "🎉 <b>Янгилик: фильтрлар анча кенгайди!</b>\n\n"
        "🛣 <b>Юриш (км)</b> энди 10 та аниқ оралиқда:\n"
        "0–10 минг · 10–20 · 20–30 · 30–40 · 40–50 · 50–70 · 70–100 · "
        "100–150 · 150–200 · 200 мингдан юқори\n\n"
        "📅 <b>Йил бўйича фильтр</b> ҳам қўшилди — 2026 дан 2009 ва ундан "
        "олдингисигача.\n\n"
        "Энди керагини аниқ танлашингиз мумкин: масалан, "
        "<b>20–30 минг км</b> ва <b>2024</b> йил.\n\n"
        "Ҳозироқ синаб кўринг 👇\n"
        "/mileage — юриш оралиғи\n"
        "/year — йил\n"
        "/brands — бренд · /models — модел"),
    # Admin-only notes. Per CLAUDE.md these go to ADMIN_CHAT_ID alone, never to
    # subscribers — nobody wants a message for a repair they never noticed.
    "fix_models_message": (
        "🔧 <b>Тузатилди</b> (фақат админ учун)\n\n"
        "<b>Муаммо:</b> фойдаланувчи бренд танлаган бўлса ҳам (масалан Li Auto), "
        "/models буйруғи «Аввал брендни танланг» деб хато хабар берарди.\n\n"
        "<b>Сабаб:</b> «бренд танланмаган» ва «танланган бренднинг моделлари "
        "рўйхати йўқ» ҳолатлари бир хил кўрилган эди.\n\n"
        "<b>Ечим:</b> энди уччала ҳолат алоҳида:\n"
        "• бренд танланмаган — брендни танланг\n"
        "• бренд бор, лекин моделлари йўқ — буни аниқ айтади ва барча эълонлар "
        "барибир келишини эслатади\n"
        "• бренд ва моделлари бор — рўйхат очилади\n\n"
        "<b>Қўшимча:</b> моделлар рўйхати 25 та бренддан <b>72</b> тага, "
        "150 тадан <b>314</b> та моделга кенгайтирилди "
        "(Li Auto, Xpeng, NIO, MG, Volvo, Lexus ва бошқалар).\n\n"
        "<i>Тестлар: 105 + 149 — барчаси ўтди.</i>"),
    "menu_latest": "🚗 Сўнгги эълонлар",
    "menu_filters": "⚙️ Фильтрлар",
    "menu_help": "❓ Ёрдам",
    "loc_btn": "📍 Жой",
    "loc_prompt": ("📍 <b>Қаердаги машиналар керак?</b>\n"
                   "<i>Керакли жойларни белгиланг. Ҳеч нарса танланмаса, "
                   "барча жойлардан юборилади.</i>"),
    "loc_added": "{name} қўшилди",
    "loc_removed": "{name} олиб ташланди",
    "locs_cleared": "Барча жойлар (чеклов олиб ташланди)",
    "every_loc": "барча жойлар",
    "hub": ("⚙️ <b>Сизнинг фильтрларингиз</b>\n"
            "<code>─────────────────────</code>\n"
            "🚗 <b>Бренд:</b> {brands}\n"
            "🚙 <b>Модел:</b> {models}\n"
            "🛣 <b>Юриш:</b> {mileage}\n"
            "📅 <b>Йил:</b> {years}\n"
            "📍 <b>Жой:</b> {locs}\n"
            "<code>─────────────────────</code>\n"
            "<i>Ўзгартириш учун пастдаги тугмани босинг.</i>"),
    "hub_none": "барчаси",
    "clear_all": "🧹 Ҳаммасини тозалаш",
    "clear_all_done": "Барча фильтрлар тозаланди",
    "hub_saved": ("✅ <b>Тайёр!</b>\n\n"
                  "Янги мос эълонлар пайдо бўлиши билан сизга дарҳол юбораман.\n\n"
                  "<i>Фильтрни ўзгартириш учун «⚙️ Фильтрлар» тугмасини босинг.</i>"),
    "onboard": ("🎉 <b>Тайёр! Ҳаммаси ишлаяпти.</b>\n\n"
                "Пастда доимий тугмалар пайдо бўлди — ҳеч қандай буйруқ ёзиш "
                "шарт эмас:\n\n"
                "🚗 <b>Сўнгги эълонлар</b> — ҳозирги энг янги машиналар\n"
                "⚙️ <b>Фильтрлар</b> — бренд, модел, юриш, йил ва жойни танлаш\n"
                "❓ <b>Ёрдам</b> — қисқа қўлланма\n\n"
                "Ҳеч нарса танламасангиз ҳам ишлайверади — барча янги эълонлар "
                "келади. Керак бўлса, кейин торайтирасиз."),
    "help_full": ("❓ <b>Қандай ишлайди?</b>\n\n"
                  "Мен ҳар <b>10 дақиқада</b> olx.uz, avtoelon.uz ва avto.uz "
                  "сайтларини текшираман. Янги машина пайдо бўлса — сизга "
                  "дарҳол юбораман. Бир эълон икки марта юборилмайди.\n\n"
                  "<b>Пастдаги тугмалар:</b>\n"
                  "🚗 <b>Сўнгги эълонлар</b> — ҳозирги энг янгилари\n"
                  "⚙️ <b>Фильтрлар</b> — нима керак эканини танлаш\n\n"
                  "<b>Фильтрлар ичида:</b>\n"
                  "🚗 Бренд · 🚙 Модел · 🛣 Юриш (км) · 📅 Йил · 📍 Жой\n\n"
                  "<i>Ҳеч нарса танламасангиз — барчаси келади. "
                  "Танласангиз — фақат ўшалари.</i>\n\n"
                  "Хабарларни тўхтатиш: «⚙️ Фильтрлар» → /stop"),
    "nothing_matches": ("🔍 Ҳозирча сизнинг фильтрингизга мос эълон йўқ.\n\n"
                        "Фильтрни бироз кенгайтириб кўринг — «⚙️ Фильтрлар» → "
                        "«🧹 Ҳаммасини тозалаш»."),
    "announce_location": (
        "🎉 <b>Янгилик: жой бўйича фильтр ва янги, осон меню!</b>\n\n"
        "📍 <b>Жой бўйича фильтр</b> қўшилди — Тошкент шаҳри, Чирчиқ, Келес, "
        "Қибрай, Зангиота, Янгийўл, Олмалиқ, Ангрен, Нурафшон ва бошқалар.\n\n"
        "⌨️ Энди <b>ҳеч қандай буйруқ ёзиш шарт эмас</b> — пастда доимий "
        "тугмалар пайдо бўлди:\n"
        "🚗 Сўнгги эълонлар · ⚙️ Фильтрлар · ❓ Ёрдам\n\n"
        "⚙️ <b>Фильтрлар</b> тугмасини боссангиз — бренд, модел, юриш, йил ва "
        "жой бир экранда кўринади, ҳозирги танловингиз билан бирга. "
        "Битта босишда ўзгартирасиз.\n\n"
        "Ҳозироқ синаб кўринг 👇"),
    "fix_index_crash": (
        "🔧 <b>Тузатилди</b> (фақат админ учун)\n\n"
        "<b>Муаммо:</b> жой фильтри чиққандан сўнг бот бир неча дақиқа "
        "қайта-қайта ишга тушиб, тўхтаб қолди.\n\n"
        "<b>Сабаб:</b> базага янги <code>region</code> устуни қўшилишидан "
        "<i>олдин</i> ўша устун учун индекс яратилган эди. Янги базада устун "
        "дарҳол мавжуд бўлгани учун тестлар ўтиб кетган, сервердаги эски "
        "базада эса хато берган.\n\n"
        "<b>Ечим:</b> индекс энди устун қўшилгандан кейин яратилади. "
        "Эски шаклдаги база билан текширадиган алоҳида тест ёзилди — "
        "бундай хато яна ўтиб кетмайди.\n\n"
        "<i>Бот тикланди, барча 4 640 та эълон жойи бўйича белгиланди.</i>"),
    "ice": "⛽",
    "ev": "🔋",
}

# Message grouping uses the same buckets as the filter, so a listing can never be
# grouped under one heading and filtered by another.
BAND_ORDER = {key: i for i, key in enumerate(cf.MILEAGE_KEYS)}
BAND_TITLES = {key: f"<b>━━ {label} ━━</b>" for key, label in cf.MILEAGE_LABELS.items()}


def band_of(row: dict) -> str:
    """Bucket for a listing, derived from its mileage rather than the stored tier.

    Rows catalogued under the older schemes carry legacy tier values, so recomputing
    keeps everything grouped correctly without a migration.
    """
    return cf.mileage_band(row.get("mileage_km"))


BOT_COMMANDS = [
    {"command": "latest", "description": "Энг сўнгги эълонлар"},
    {"command": "brands", "description": "Брендларни танлаш"},
    {"command": "models", "description": "Моделларни танлаш"},
    {"command": "mileage", "description": "Юриш (км) оралиғини танлаш"},
    {"command": "year", "description": "Йилни танлаш"},
    {"command": "location", "description": "Жойни танлаш"},
    {"command": "filters", "description": "Барча фильтрлар"},
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
    fuel = str(row.get("fuel") or "").lower()
    icon = T["ev"] if any(w in fuel for w in ("ev", "phev", "electr", "электро",
                                              "elektr")) else T["ice"]
    lines = [f"{head}{icon} <a href=\"{esc(row.get('url'))}\">{title}</a>"]

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
    # No per-listing warning any more - the mileage band heading carries that meaning.
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
    models_row = models_button_row(tg_id)
    rows.append(models_row + [{"text": T["mileage_btn"], "callback_data": "km"},
                              {"text": T["year_btn"], "callback_data": "yr"}])
    rows.append([{"text": T["done"], "callback_data": "done"}])
    return {"inline_keyboard": rows}


def models_button_row(tg_id: int) -> list[dict]:
    """The drill-down entry point, shown only once a brand with models is selected."""
    chosen = botdb.get_brands(tg_id)
    if any(modellib.has_models(b) for b in chosen):
        return [{"text": T["models_btn"], "callback_data": "mods"}]
    return []


def model_brand_keyboard(tg_id: int) -> dict:
    """Which of the user's brands to drill into."""
    chosen = sorted(b for b in botdb.get_brands(tg_id) if modellib.has_models(b))
    picked = botdb.get_models(tg_id)
    rows, row = [], []
    for name in chosen:
        n = len(picked.get(name, ()))
        label = f"{name} ({n})" if n else name
        row.append({"text": label, "callback_data": f"mb:{brandlib.brand_id(name)}"})
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([{"text": T["back"], "callback_data": "hub"}])
    return {"inline_keyboard": rows}


def model_keyboard(tg_id: int, brand: str) -> dict:
    """Models of one brand, ticked where the user selected them."""
    picked = botdb.get_models(tg_id, brand).get(brand, set())
    rows, row = [], []
    for idx, name in enumerate(modellib.models_for(brand)):
        mark = "✅ " if name in picked else ""
        row.append({"text": f"{mark}{name}",
                    "callback_data": f"m:{brandlib.brand_id(brand)}:{idx}"})
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([{"text": T["all_models"],
                  "callback_data": f"mall:{brandlib.brand_id(brand)}"}])
    rows.append([{"text": T["back"], "callback_data": "mods"},
                 {"text": T["done"], "callback_data": "done"}])
    return {"inline_keyboard": rows}


# Both pickers are generated from carfilters, so adding a bucket there is enough.
BAND_KEYS = cf.MILEAGE_KEYS
BAND_LABELS = cf.MILEAGE_LABELS
YEAR_KEYS = cf.YEAR_KEYS
YEAR_LABELS = cf.YEAR_LABELS


def _bucket_keyboard(chosen: set, keys, labels, prefix: str, clear_cb: str) -> dict:
    """Two buckets per row, ticked where selected, then clear-all / back / done."""
    rows, row = [], []
    for key in keys:
        mark = "✅ " if key in chosen else ""
        row.append({"text": f"{mark}{labels[key]}", "callback_data": f"{prefix}{key}"})
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([{"text": T["all_mileage"], "callback_data": clear_cb}])
    rows.append([{"text": T["back"], "callback_data": "hub"},
                 {"text": T["done"], "callback_data": "done"}])
    return {"inline_keyboard": rows}


def mileage_keyboard(tg_id: int) -> dict:
    return _bucket_keyboard(botdb.get_bands(tg_id), BAND_KEYS, BAND_LABELS, "km:", "kmall")


def year_keyboard(tg_id: int) -> dict:
    return _bucket_keyboard(botdb.get_years(tg_id), YEAR_KEYS, YEAR_LABELS, "yr:", "yrall")


def _summary(chosen: set, keys, labels, every: str) -> str:
    if not chosen or set(chosen) >= set(keys):
        return every
    return ", ".join(labels[k] for k in keys if k in chosen)


def mileage_summary(tg_id: int) -> str:
    return _summary(botdb.get_bands(tg_id), BAND_KEYS, BAND_LABELS, T["every_mileage"])


def year_summary(tg_id: int) -> str:
    return _summary(botdb.get_years(tg_id), YEAR_KEYS, YEAR_LABELS, T["every_year"])


# The bottom menu is always on screen, so nothing here needs a typed command. Novices
# never have to discover that commands exist at all.
def main_menu() -> dict:
    return {"keyboard": [[{"text": T["menu_latest"]}],
                         [{"text": T["menu_filters"]}, {"text": T["menu_help"]}]],
            "resize_keyboard": True, "is_persistent": True}


LOC_KEYS = loclib.LOCATION_KEYS
LOC_LABELS = loclib.LOCATION_LABELS
LOCS_PER_PAGE = 12


def location_keyboard(tg_id: int, page: int = 0) -> dict:
    chosen = botdb.get_locations(tg_id)
    pages = max(1, (len(LOC_KEYS) + LOCS_PER_PAGE - 1) // LOCS_PER_PAGE)
    page = max(0, min(page, pages - 1))
    start = page * LOCS_PER_PAGE

    rows, row = [], []
    for key in LOC_KEYS[start:start + LOCS_PER_PAGE]:
        mark = "✅ " if key in chosen else ""
        row.append({"text": f"{mark}{LOC_LABELS[key]}", "callback_data": f"lc:{key}"})
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    nav = []
    if page > 0:
        nav.append({"text": "◀️", "callback_data": f"lp:{page - 1}"})
    nav.append({"text": f"{page + 1}/{pages}", "callback_data": "noop"})
    if page < pages - 1:
        nav.append({"text": "▶️", "callback_data": f"lp:{page + 1}"})
    rows.append(nav)
    rows.append([{"text": T["all_mileage"], "callback_data": "lcall"}])
    rows.append([{"text": T["back"], "callback_data": "hub"},
                 {"text": T["done"], "callback_data": "done"}])
    return {"inline_keyboard": rows}


def location_summary(tg_id: int) -> str:
    chosen = botdb.get_locations(tg_id)
    if not chosen or set(chosen) >= set(LOC_KEYS):
        return T["every_loc"]
    return ", ".join(LOC_LABELS[k] for k in LOC_KEYS if k in chosen)


def hub_keyboard() -> dict:
    """One screen, one tap to every filter - the whole point of the hub."""
    return {"inline_keyboard": [
        [{"text": T["all_brands"].replace("🌍 ", "🚗 "), "callback_data": "p:0"},
         {"text": T["models_btn"], "callback_data": "mods"}],
        [{"text": T["mileage_btn"], "callback_data": "km"},
         {"text": T["year_btn"], "callback_data": "yr"}],
        [{"text": T["loc_btn"], "callback_data": "lp:0"}],
        [{"text": T["clear_all"], "callback_data": "clearall"}],
        [{"text": T["done"], "callback_data": "done"}],
    ]}


def hub_text(tg_id: int) -> str:
    """Current settings, spelled out, so nothing is hidden behind a menu."""
    brands_sel = botdb.get_brands(tg_id)
    models_sel = botdb.get_models(tg_id)
    model_bits = [f"{b}: {', '.join(sorted(m))}" for b, m in sorted(models_sel.items()) if m]
    return T["hub"].format(
        brands=esc(", ".join(sorted(brands_sel)) if brands_sel else T["hub_none"]),
        models=esc(", ".join(model_bits) if model_bits else T["hub_none"]),
        mileage=esc(mileage_summary(tg_id)),
        years=esc(year_summary(tg_id)),
        locs=esc(location_summary(tg_id)))


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
        """Send listings grouped by mileage band. Returns the keys actually delivered."""
        delivered: list[str] = []
        chunk = max(1, self.max_per_push)

        # Order by band first, then by the ranking the query already applied, so each
        # band is contiguous and its heading is emitted exactly once per message.
        ordered = sorted(rows, key=lambda r: BAND_ORDER.get(band_of(r), 99))

        blocks: list[tuple[str, dict]] = []      # (band, row)
        for row in ordered:
            blocks.append((band_of(row), row))

        counter = 0
        current_band = None
        for start in range(0, len(blocks), chunk):
            batch = blocks[start:start + chunk]
            parts = [header] if start == 0 else [T["continued"]]
            # A message that continues mid-band still needs the heading for context.
            current_band = None
            for band, row in batch:
                if band != current_band:
                    parts.append(BAND_TITLES[band])
                    current_band = band
                counter += 1
                parts.append(render_listing(row, counter))
            result, error = self.tg.send_checked(tg_id, "\n\n".join(parts))
            if result is None:
                if error in self.UNREACHABLE:
                    botdb.set_user_field(tg_id, "state", "new")
                    self.log(f"{tg_id} is unreachable (Telegram {error}) — parked until "
                             f"they send /start again.", "WARN")
                else:
                    self.log(f"delivery to {tg_id} failed; will retry next cycle", "WARN")
                break
            delivered += [row["key"] for _band, row in batch]
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
            self.tg.send(chat_id, T["onboard"], reply_markup=main_menu())
            self.cmd_latest(chat_id, fresh)
            self.notify_admin_new_user(fresh)
            return

        text = (msg.get("text") or "").strip()
        # The bottom-menu buttons arrive as ordinary text. Mapping them onto the same
        # commands means a subscriber never has to know commands exist.
        BUTTONS = {T["menu_latest"]: "latest",
                   T["menu_filters"]: "filters",
                   T["menu_help"]: "help"}
        if text in BUTTONS:
            command = BUTTONS[text]
        else:
            command = text.split()[0].lower().lstrip("/").split("@")[0] if text else ""

        if command == "start":
            if user.get("state") != "active" or not user.get("phone"):
                self.tg.send(chat_id, T["welcome"], reply_markup=contact_keyboard())
                return
            self.tg.send(chat_id, T["onboard"], reply_markup=main_menu())
            self.cmd_latest(chat_id, user)
        elif command in ("filters", "filter", "sozlama"):
            self.tg.send(chat_id, hub_text(tg_user["id"]), reply_markup=hub_keyboard())
        elif command in ("location", "region", "joy", "city"):
            self.tg.send(chat_id, T["loc_prompt"],
                         reply_markup=location_keyboard(tg_user["id"], 0))
        elif command in ("year", "yil", "god"):
            self.tg.send(chat_id, T["year_prompt"],
                         reply_markup=year_keyboard(tg_user["id"]))
        elif command in ("mileage", "km", "probeg"):
            self.tg.send(chat_id, T["mileage_prompt"],
                         reply_markup=mileage_keyboard(tg_user["id"]))
        elif command in ("models", "model"):
            self.open_model_picker(chat_id, tg_user["id"])
        elif command in ("brands", "cars", "mycars"):
            self.tg.send(chat_id, T["brand_prompt"],
                         reply_markup=brand_keyboard(tg_user["id"], 0))
        elif command == "latest":
            self.cmd_latest(chat_id, user)
        elif command == "stop":
            botdb.set_user_field(tg_user["id"], "state", "paused")
            self.tg.send(chat_id, T["paused"])
        elif command == "help":
            self.tg.send(chat_id, T["help_full"], reply_markup=main_menu())
        elif command == "admin" and is_admin:
            self.cmd_admin(chat_id)
        else:
            # Anything unrecognised: show the menu rather than scold them.
            self.tg.send(chat_id, T["help_full"], reply_markup=main_menu())

    def _extra_scope(self, tg_id: int, separator: str = " · ") -> str:
        """The mileage/year part of a subscription summary, omitted when unrestricted."""
        bits = []
        km = mileage_summary(tg_id)
        if km != T["every_mileage"]:
            bits.append("🛣 " + km)
        yr = year_summary(tg_id)
        if yr != T["every_year"]:
            bits.append("📅 " + yr)
        return (separator + separator.join(bits)) if bits else ""

    def scope_text(self, tg_id: int, chosen: set) -> str:
        if not chosen:
            return T["all_brands_scope"] + self._extra_scope(tg_id)
        picked = botdb.get_models(tg_id)
        parts = []
        for brand in sorted(chosen):
            models = sorted(picked.get(brand, ()))
            parts.append(f"{brand}: {', '.join(models)}" if models else brand)
        text = ", ".join(parts)
        return text + self._extra_scope(tg_id)

    def scope_summary(self, tg_id: int) -> str:
        """Human-readable description of what this user is subscribed to."""
        chosen = botdb.get_brands(tg_id)
        if not chosen:
            scope = T["every_brand"]
        else:
            picked = botdb.get_models(tg_id)
            parts = []
            for brand in sorted(chosen):
                models = sorted(picked.get(brand, ()))
                parts.append(f"{brand} ({', '.join(models)})" if models else brand)
            scope = ", ".join(parts)
        return T["saved"].format(scope=esc(scope + self._extra_scope(tg_id, "\n")))

    def open_model_picker(self, chat_id: int, tg_id: int) -> None:
        """Open the model drill-down, explaining precisely why if it cannot be opened.

        Three outcomes, and they are genuinely different: no brand chosen at all, a
        brand chosen that has no model list yet, or a normal drill-down. Collapsing the
        first two into one message is what confused subscribers.
        """
        all_brands = botdb.get_brands(tg_id)
        with_models = [b for b in all_brands if modellib.has_models(b)]
        if not all_brands:
            self.tg.send(chat_id, T["pick_brand_first"])
            self.tg.send(chat_id, T["brand_prompt"], reply_markup=brand_keyboard(tg_id, 0))
        elif not with_models:
            self.tg.send(chat_id, T["no_models_for_brands"].format(
                brands=esc(", ".join(sorted(all_brands)))))
            self.tg.send(chat_id, T["brand_prompt"], reply_markup=brand_keyboard(tg_id, 0))
        else:
            self.tg.send(chat_id, T["choose_brand_for_models"],
                         reply_markup=model_brand_keyboard(tg_id))

    def cmd_latest(self, chat_id: int, user: dict) -> None:
        chosen = botdb.get_brands(user["tg_id"])
        rows = botdb.latest_for(user["tg_id"], chosen, LATEST_ON_START)
        if not rows:
            has_filters = (botdb.get_brands(user["tg_id"]) or botdb.get_bands(user["tg_id"])
                           or botdb.get_years(user["tg_id"])
                           or botdb.get_locations(user["tg_id"]))
            self.tg.send(chat_id,
                         T["nothing_matches"] if has_filters else T["empty_catalogue"],
                         reply_markup=main_menu())
            return
        scope = self.scope_text(user["tg_id"], chosen)
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

        # ---- mileage bands -------------------------------------------------------
        if data == "km":
            self.tg.edit(chat_id, message_id, T["mileage_prompt"],
                         reply_markup=mileage_keyboard(tg_id))
            self.tg.answer_callback(cq_id)
            return

        if data.startswith("km:"):
            band = data.split(":", 1)[1]
            if band in BAND_KEYS:
                selected = botdb.toggle_band(tg_id, band)
                key = "mileage_added" if selected else "mileage_removed"
                self.tg.answer_callback(cq_id, T[key].format(name=BAND_LABELS[band]))
                self.tg.edit_markup(chat_id, message_id,
                                    reply_markup=mileage_keyboard(tg_id))
            return

        if data == "kmall":
            botdb.clear_bands(tg_id)
            self.tg.answer_callback(cq_id, T["mileage_cleared"])
            self.tg.edit_markup(chat_id, message_id, reply_markup=mileage_keyboard(tg_id))
            return

        if data == "yr":
            self.tg.edit(chat_id, message_id, T["year_prompt"],
                         reply_markup=year_keyboard(tg_id))
            self.tg.answer_callback(cq_id)
            return

        if data.startswith("yr:"):
            yband = data.split(":", 1)[1]
            if yband in YEAR_KEYS:
                selected = botdb.toggle_year(tg_id, yband)
                key = "year_added" if selected else "year_removed"
                self.tg.answer_callback(cq_id, T[key].format(name=YEAR_LABELS[yband]))
                self.tg.edit_markup(chat_id, message_id, reply_markup=year_keyboard(tg_id))
            return

        if data == "hub":
            self.tg.edit(chat_id, message_id, hub_text(tg_id),
                         reply_markup=hub_keyboard())
            self.tg.answer_callback(cq_id)
            return

        if data.startswith("lp:"):
            self.tg.edit(chat_id, message_id, T["loc_prompt"],
                         reply_markup=location_keyboard(tg_id, int(data.split(":")[1])))
            self.tg.answer_callback(cq_id)
            return

        if data.startswith("lc:"):
            key = data.split(":", 1)[1]
            if key in LOC_KEYS:
                selected = botdb.toggle_location(tg_id, key)
                label = LOC_LABELS[key]
                tkey = "loc_added" if selected else "loc_removed"
                self.tg.answer_callback(cq_id, T[tkey].format(name=label))
                self.tg.edit_markup(chat_id, message_id,
                                    reply_markup=location_keyboard(tg_id, 0))
            return

        if data == "lcall":
            botdb.clear_locations(tg_id)
            self.tg.answer_callback(cq_id, T["locs_cleared"])
            self.tg.edit_markup(chat_id, message_id,
                                reply_markup=location_keyboard(tg_id, 0))
            return

        if data == "clearall":
            botdb.clear_all_filters(tg_id)
            self.tg.answer_callback(cq_id, T["clear_all_done"])
            self.tg.edit(chat_id, message_id, hub_text(tg_id),
                         reply_markup=hub_keyboard())
            return

        if data == "yrall":
            botdb.clear_years(tg_id)
            self.tg.answer_callback(cq_id, T["years_cleared"])
            self.tg.edit_markup(chat_id, message_id, reply_markup=year_keyboard(tg_id))
            return

        # ---- model drill-down ----------------------------------------------------
        if data == "mods":
            all_brands = botdb.get_brands(tg_id)
            with_models = [b for b in all_brands if modellib.has_models(b)]
            if not all_brands:
                self.tg.answer_callback(cq_id, T["pick_brand_first_toast"], alert=True)
                return
            if not with_models:
                self.tg.answer_callback(cq_id, T["no_models_toast"], alert=True)
                self.tg.send(chat_id, T["no_models_for_brands"].format(
                    brands=esc(", ".join(sorted(all_brands)))))
                return
            self.tg.edit(chat_id, message_id, T["choose_brand_for_models"],
                         reply_markup=model_brand_keyboard(tg_id))
            self.tg.answer_callback(cq_id)
            return

        if data.startswith("mb:"):
            brand = brandlib.brand_by_id(int(data.split(":")[1]))
            if not brand or not modellib.has_models(brand):
                self.tg.answer_callback(cq_id, T["no_models"], alert=True)
                return
            self.tg.edit(chat_id, message_id,
                         T["model_prompt"].format(brand=esc(brand)),
                         reply_markup=model_keyboard(tg_id, brand))
            self.tg.answer_callback(cq_id)
            return

        if data.startswith("m:"):
            _, bidx, midx = data.split(":")
            brand = brandlib.brand_by_id(int(bidx))
            model = modellib.model_by_index(brand, int(midx)) if brand else None
            if brand and model:
                selected = botdb.toggle_model(tg_id, brand, model)
                key = "model_added" if selected else "model_removed"
                self.tg.answer_callback(cq_id, T[key].format(name=model))
                self.tg.edit_markup(chat_id, message_id,
                                    reply_markup=model_keyboard(tg_id, brand))
            return

        if data.startswith("mall:"):
            brand = brandlib.brand_by_id(int(data.split(":")[1]))
            if brand:
                botdb.clear_models(tg_id, brand)
                self.tg.answer_callback(cq_id, T["models_cleared"])
                self.tg.edit_markup(chat_id, message_id,
                                    reply_markup=model_keyboard(tg_id, brand))
            return

        if data == "done":
            self.tg.edit(chat_id, message_id, hub_text(tg_id))
            self.tg.send(chat_id, T["hub_saved"], reply_markup=main_menu())
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
