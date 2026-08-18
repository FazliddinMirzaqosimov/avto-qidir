#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline tests for the multi-user bot layer. No network, no Telegram."""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Point the database at a scratch file before importing anything that opens it.
_TMP = tempfile.mkdtemp(prefix="evbot_test_")
os.environ["EV_HUNTER_DATA_DIR"] = _TMP

import bot as botmod        # noqa: E402
import botdb                # noqa: E402
import brands as brandlib   # noqa: E402

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name} {detail}")


ADMIN = 5520661044
print("\n=== 1. brand catalogue ===")
check("catalogue is large", len(brandlib.BRAND_NAMES) > 100, len(brandlib.BRAND_NAMES))
check("names unique", len(set(brandlib.BRAND_NAMES)) == len(brandlib.BRAND_NAMES))
check("BYD Seagull -> BYD", brandlib.detect_brand("BYD Seagull 2024") == "BYD")
check("Onix -> Chevrolet", brandlib.detect_brand("Onix 2023 avtomat") == "Chevrolet")
check("Cobalt -> Chevrolet", brandlib.detect_brand("Cobalt LT 2022") == "Chevrolet")
check("Cyrillic Хонжи -> Hongqi", brandlib.detect_brand("Хонжи 450 срочно") == "Hongqi")
check("junk -> None", brandlib.detect_brand("velosiped sotiladi") is None)
check("id round-trip", brandlib.brand_by_id(brandlib.brand_id("Tesla")) == "Tesla")

print("\n=== 2. registration ===")
botdb.init(admin_id=ADMIN)
res = botdb.upsert_user({"id": 111, "username": "alice", "first_name": "Alice",
                         "last_name": "A", "language_code": "en", "is_premium": True})
check("new user flagged new", res["is_new"] is True)
check("state starts as new", res["user"]["state"] == "new")
check("not blocked initially", res["user"]["blocked"] == 0)
again = botdb.upsert_user({"id": 111, "username": "alice2", "first_name": "Alice"})
check("second upsert not new", again["is_new"] is False)
check("username refreshed", botdb.get_user(111)["username"] == "alice2")

botdb.set_user_field(111, "phone", "+998901234567")
botdb.set_user_field(111, "state", "active")
check("phone stored", botdb.get_user(111)["phone"] == "+998901234567")
check("appears in active_users", any(u["tg_id"] == 111 for u in botdb.active_users()))

print("\n=== 3. blocking ===")
botdb.set_user_field(111, "blocked", 1)
check("blocked user leaves active list",
      all(u["tg_id"] != 111 for u in botdb.active_users()))
botdb.set_user_field(111, "blocked", 0)
check("unblock restores", any(u["tg_id"] == 111 for u in botdb.active_users()))
try:
    botdb.set_user_field(111, "tg_id; DROP TABLE users", 1)
    check("rejects unknown column", False, "no error raised")
except ValueError:
    check("rejects unknown column", True)

print("\n=== 4. brand subscriptions ===")
check("starts empty", botdb.get_brands(111) == set())
check("toggle on returns True", botdb.toggle_brand(111, "BYD") is True)
check("toggle off returns False", botdb.toggle_brand(111, "BYD") is False)
botdb.set_brands(111, ["BYD", "Chevrolet"])
check("set_brands stored", botdb.get_brands(111) == {"BYD", "Chevrolet"})


class FakeListing:
    def __init__(self, key, title, price, brandhint=""):
        self.key = key
        self.source = "OLX"
        self.ad_id = key.split(":")[1]
        self.url = f"https://olx.uz/{self.ad_id}"
        self.title = title
        self.price_usd = price
        self.year = 2024
        self.mileage_km = 10000
        self.city = "Tashkent"
        self.fuel = "electric"
        self.owners = 1
        self.posted_at = None
        self.blob = (title + " " + brandhint).lower()


print("\n=== 5. catalogue and per-user delivery ===")
l1 = FakeListing("OLX:1", "BYD Seagull 2024", 13000)
l2 = FakeListing("OLX:2", "Chevrolet Onix 2023", 12000)
l3 = FakeListing("OLX:3", "Tesla Model 3", 30000)
check("first insert is new", botdb.upsert_listing(l1, "BYD", "top") is True)
check("re-insert is not new", botdb.upsert_listing(l1, "BYD", "top") is False)
botdb.upsert_listing(l2, "Chevrolet", "top")
botdb.upsert_listing(l3, "Tesla", "top")

rows = botdb.undelivered_for(111, {"BYD", "Chevrolet"}, 10)
check("brand filter applied", {r["key"] for r in rows} == {"OLX:1", "OLX:2"},
      [r["key"] for r in rows])
check("Tesla excluded by filter", all(r["key"] != "OLX:3" for r in rows))

botdb.mark_sent(111, ["OLX:1"])
rows2 = botdb.undelivered_for(111, {"BYD", "Chevrolet"}, 10)
check("delivered one is not repeated", {r["key"] for r in rows2} == {"OLX:2"})

everything = botdb.undelivered_for(222, None, 10)
check("no brand filter means everything", len(everything) == 3, len(everything))

print("\n=== 6. message rendering ===")
row = dict(botdb.latest_for(111, {"BYD"}, 1)[0])
text = botmod.render_listing(row, 1)
check("listing has link", "<a href=" in text)
check("listing shows price", "$13 000" in text, text)
check("listing mileage in Uzbek", "км" in text, text)
check("listing shows brand", "BYD" in text)

botdb.set_user_field(111, "phone", "+998901234567")
card = botmod.render_user_card(botdb.get_user(111), "New user joined")
check("card shows phone", "+998901234567" in card)
check("card shows telegram id", "111" in card)
check("card shows status", "фаол" in card or "БЛОКЛАНГАН" in card)
check("html escaped in card",
      "&lt;" in botmod.render_user_card({"tg_id": 5, "first_name": "<b>x</b>"}))

print("\n=== 7. keyboards ===")
kb = botmod.brand_keyboard(111, 0)
rows_kb = kb["inline_keyboard"]
check("keyboard has rows", len(rows_kb) > 3)
check("selected brand ticked",
      any("✅" in b["text"] for r in rows_kb for b in r if "BYD" in b["text"]))
check("has Done button",
      any(b.get("callback_data") == "done" for r in rows_kb for b in r))
check("callback data within telegram 64-byte limit",
      all(len(b.get("callback_data", "").encode()) <= 64 for r in rows_kb for b in r))
last_page = (len(brandlib.BRAND_NAMES) - 1) // botmod.BRANDS_PER_PAGE
kb_last = botmod.brand_keyboard(111, last_page)
check("last page renders", len(kb_last["inline_keyboard"]) > 1)
kb_over = botmod.brand_keyboard(111, 9999)
check("page clamped, no crash", len(kb_over["inline_keyboard"]) > 1)

ck = botmod.contact_keyboard()
check("contact button requests contact",
      ck["keyboard"][0][0].get("request_contact") is True)
ak = botmod.admin_keyboard(111, False)
check("admin shows Block when active", "Блоклаш" in ak["inline_keyboard"][0][0]["text"])
ak2 = botmod.admin_keyboard(111, True)
check("admin shows Unblock when blocked", "Блокдан" in ak2["inline_keyboard"][0][0]["text"])

print("\n=== 8. everything user-facing is Uzbek Cyrillic ===")
import re as _re  # noqa: E402

CYR = _re.compile(r"[Ѐ-ӿ]")
LATIN = _re.compile(r"[A-Za-z]{3,}")
# Proper nouns and command names are expected to stay Latin.
ALLOWED = {"EV", "Hunter", "olx", "avtoelon", "avto", "uz", "brands", "latest",
           "stop", "start", "help", "code", "scope", "name"}

not_translated = []
for key, val in botmod.T.items():
    if not isinstance(val, str) or not val.strip():
        continue
    bare = _re.sub(r"<[^>]+>", " ", val)          # strip HTML tags
    bare = _re.sub(r"\{\w+\}", " ", bare)         # strip format placeholders
    bare = _re.sub(r"/\w+", " ", bare)            # strip /commands
    leftovers = [w for w in LATIN.findall(bare) if w not in ALLOWED]
    if leftovers and not CYR.search(bare):
        not_translated.append((key, leftovers))
check("every T[] string is Cyrillic", not not_translated, not_translated)
check("command menu is Cyrillic",
      all(CYR.search(c["description"]) for c in botmod.BOT_COMMANDS))
check("welcome is Cyrillic", CYR.search(botmod.T["welcome"]) is not None)
check("phone button is Cyrillic",
      CYR.search(botmod.contact_keyboard()["keyboard"][0][0]["text"]) is not None)
_kb = botmod.brand_keyboard(111, 0)["inline_keyboard"]
check("All/Clear/Done buttons are Cyrillic",
      all(CYR.search(b["text"]) for r in _kb[-2:] for b in r))
check("user card labels are Cyrillic",
      "Телефон" in card and "Ҳолат" in card)
check("no leftover English in the paused/help text",
      CYR.search(botmod.T["paused"]) and CYR.search(botmod.T["help"]))

print("\n=== 9. stats ===")
s = botdb.stats()
check("counts users", s["users"] >= 1)
check("counts listings", s["listings"] == 3, s["listings"])

print("\n" + "=" * 46)
print(f"  {PASS} passed, {FAIL} failed")
print("=" * 46)
sys.exit(1 if FAIL else 0)
