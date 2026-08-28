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
from ev_hunter import mileage_tier as ev_tier  # noqa: E402

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

# A row migrated from the old `seen` table arrives with no brand/year/mileage. Re-seeing
# the same ad must fill those in, otherwise no brand filter can ever match it.
_c = botdb.connect()
_c.execute("INSERT OR REPLACE INTO listings(key,source,ad_id,url,title,price_usd,first_seen)"
           " VALUES('OLX:9','OLX','9','https://olx.uz/9','BYD Dolphin 2024',12000,'2026-01-01')")
_c.commit()
_c.close()
check("migrated row starts brandless",
      all(r["key"] != "OLX:9" for r in botdb.undelivered_for(333, {"BYD"}, 10)))
l9 = FakeListing("OLX:9", "BYD Dolphin 2024", 12000)
botdb.upsert_listing(l9, "BYD", "top")
back = botdb.undelivered_for(333, {"BYD"}, 10)
check("brand backfilled on re-scan", any(r["key"] == "OLX:9" for r in back),
      [r["key"] for r in back])
row9 = [r for r in back if r["key"] == "OLX:9"]
check("mileage backfilled too", row9 and row9[0]["mileage_km"] == 10000,
      row9[0]["mileage_km"] if row9 else None)

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
check("counts listings", s["listings"] == 4, s["listings"])


print("\n=== 10. unreachable chats are parked, not retried forever ===")


class FakeTG:
    """Stands in for the Telegram client; records what was attempted."""

    def __init__(self, error=None):
        self.error = error
        self.sent = 0

    def send_checked(self, chat_id, text, reply_markup=None, preview=False):
        if self.error:
            return None, self.error
        self.sent += 1
        return {"message_id": self.sent}, None

    def send(self, *a, **k):
        return self.send_checked(*a, **k)[0]


class FakeCfg(dict):
    pass


_cfg = {"telegram": {"bot_token": "x", "chat_id": "5520661044",
                     "admin_chat_id": "5520661044"},
        "runtime": {"max_items_per_message": 2}}
_b = botmod.Bot(_cfg, lambda *a, **k: None)

botdb.upsert_user({"id": 444, "first_name": "Stale"})
botdb.set_user_field(444, "phone", "+998900000000")
botdb.set_user_field(444, "state", "active")
_rows = botdb.latest_for(444, None, 2)

_b.tg = FakeTG(error=400)                      # chat not found
got = _b.send_listings(444, _rows, "hdr")
check("400 delivers nothing", got == [], got)
check("400 parks the subscriber", botdb.get_user(444)["state"] == "new",
      botdb.get_user(444)["state"])

botdb.set_user_field(444, "state", "active")
_b.tg = FakeTG(error=403)                      # user blocked the bot
_b.send_listings(444, _rows, "hdr")
check("403 parks the subscriber too", botdb.get_user(444)["state"] == "new")

botdb.set_user_field(444, "state", "active")
_b.tg = FakeTG(error=500)                      # transient server-side failure
_b.send_listings(444, _rows, "hdr")
check("500 leaves them active for a retry",
      botdb.get_user(444)["state"] == "active", botdb.get_user(444)["state"])

_b.tg = FakeTG()
ok = _b.send_listings(444, _rows, "hdr")
check("happy path returns delivered keys", len(ok) == len(_rows), ok)

print("\n=== 11. mileage-band grouping in the message ===")


class CaptureTG:
    def __init__(self):
        self.msgs = []

    def send_checked(self, chat_id, text, reply_markup=None, preview=False):
        self.msgs.append(text)
        return {"message_id": len(self.msgs)}, None

    def send(self, *a, **k):
        return self.send_checked(*a, **k)[0]


check("band_of 12k", botmod.band_of({"mileage_km": 12000}) == "km10_20")
check("band_of 50k boundary", botmod.band_of({"mileage_km": 50000}) == "km50_70")
check("band_of 100k boundary", botmod.band_of({"mileage_km": 100000}) == "km100_150")
check("band_of none", botmod.band_of({"mileage_km": None}) == "km_unknown")
check("legacy tier row grouped by km, not by stored tier",
      botmod.band_of({"mileage_km": 70000, "tier": "stretch"}) == "km70_100")

_cfg2 = {"telegram": {"bot_token": "x", "chat_id": "1", "admin_chat_id": "1"},
         "runtime": {"max_items_per_message": 50}}
_b2 = botmod.Bot(_cfg2, lambda *a, **k: None)
_b2.tg = CaptureTG()
mixed = [
    {"key": "a", "title": "High km", "url": "u", "price_usd": 9000, "year": 2022,
     "mileage_km": 120000, "brand": "Chevrolet", "source": "OLX", "fuel": "benzin"},
    {"key": "b", "title": "Low km", "url": "u", "price_usd": 14000, "year": 2025,
     "mileage_km": 9000, "brand": "BYD", "source": "OLX", "fuel": "EV"},
    {"key": "c", "title": "No km", "url": "u", "price_usd": 11000, "year": 2023,
     "mileage_km": None, "brand": "Kia", "source": "OLX", "fuel": "benzin"},
    {"key": "d", "title": "Mid km", "url": "u", "price_usd": 12000, "year": 2024,
     "mileage_km": 70000, "brand": "Chery", "source": "OLX", "fuel": "benzin"},
]
sent = _b2.send_listings(1, mixed, "HDR")
body = _b2.tg.msgs[0]
check("all four delivered", len(sent) == 4, sent)
check("all band headings present",
      all(botmod.BAND_TITLES[k] in body for k in
          ("km0_10", "km70_100", "km100_150", "km_unknown")))
order = [body.index(botmod.BAND_TITLES[k]) for k in
         ("km0_10", "km70_100", "km100_150", "km_unknown")]
check("bands ordered best mileage first", order == sorted(order), order)
check("petrol listing shows fuel-pump icon", "\u26fd" in body)
check("electric listing shows battery icon", "\U0001f50b" in body)
check("numbering continuous 1..4",
      all(f"<b>{i}.</b>" in body for i in (1, 2, 3, 4)))

_b2.tg = CaptureTG()
_b2.max_per_push = 2
_b2.send_listings(1, mixed, "HDR")
check("splits into two messages", len(_b2.tg.msgs) == 2, len(_b2.tg.msgs))
check("continuation repeats a heading for context",
      any(h in _b2.tg.msgs[1] for h in botmod.BAND_TITLES.values()))

print("\n=== 12. model catalogue and detection ===")
import models as modellib  # noqa: E402

check("catalogue covers many brands", len(modellib.MODELS) >= 20, len(modellib.MODELS))
check("BYD has models", modellib.has_models("BYD"))
check("brand without models is honest", not modellib.has_models("Rivian"))
check("Seagull detected", modellib.detect_model("BYD", "BYD Seagull 2026 full") == "Seagull")
check("Onix detected", modellib.detect_model("Chevrolet", "Chevrolet Onix 2023") == "Onix")
check("Cobalt detected", modellib.detect_model("Chevrolet", "Cobalt LT 2022") == "Cobalt")
check("longest alias wins (Yuan Plus over Yuan Up)",
      modellib.detect_model("BYD", "Byd Yuan Plus 2024") == "Yuan Plus / Atto 3")
check("wrong brand yields nothing",
      modellib.detect_model("Chevrolet", "BYD Seagull 2026") is None)
check("unknown brand yields nothing", modellib.detect_model(None, "Onix") is None)
check("model index round-trip",
      modellib.model_by_index("BYD", modellib.model_index("BYD", "Dolphin")) == "Dolphin")

print("\n=== 13. model subscriptions filter delivery ===")
botdb.set_brands(777, ["BYD", "Chevrolet"])
m1 = FakeListing("OLX:m1", "BYD Seagull 2026", 13000)
m2 = FakeListing("OLX:m2", "BYD Dolphin 2024", 14000)
m3 = FakeListing("OLX:m3", "Chevrolet Onix 2023", 12000)
botdb.upsert_listing(m1, "BYD", "under50", "Seagull")
botdb.upsert_listing(m2, "BYD", "under50", "Dolphin")
botdb.upsert_listing(m3, "Chevrolet", "under50", "Onix")

allrows = {r["key"] for r in botdb.undelivered_for(777, {"BYD", "Chevrolet"}, 20)}
check("no narrowing means every model of the chosen brands",
      {"OLX:m1", "OLX:m2", "OLX:m3"} <= allrows, sorted(allrows))

check("toggle_model returns True when selected",
      botdb.toggle_model(777, "BYD", "Seagull") is True)
narrowed = {r["key"] for r in botdb.undelivered_for(777, {"BYD", "Chevrolet"}, 20)}
check("narrowed brand keeps only the chosen model", "OLX:m1" in narrowed)
check("other model of the narrowed brand drops out", "OLX:m2" not in narrowed)
check("un-narrowed brand is unaffected", "OLX:m3" in narrowed)

check("toggle off returns False", botdb.toggle_model(777, "BYD", "Seagull") is False)
check("clearing restores every model",
      "OLX:m2" in {r["key"] for r in botdb.undelivered_for(777, {"BYD", "Chevrolet"}, 20)})

botdb.set_models(777, "BYD", ["Dolphin"])
only = {r["key"] for r in botdb.undelivered_for(777, {"BYD", "Chevrolet"}, 20)}
check("set_models replaces the selection", "OLX:m2" in only and "OLX:m1" not in only)
botdb.clear_models(777, "BYD")
check("clear_models widens again",
      "OLX:m1" in {r["key"] for r in botdb.undelivered_for(777, {"BYD", "Chevrolet"}, 20)})

check("selecting a model subscribes the brand too",
      (botdb.toggle_model(888, "Chevrolet", "Onix") is True)
      and "Chevrolet" in botdb.get_brands(888))
check("/latest honours the narrowing",
      all(r["model"] in (None, "Onix") or r["brand"] != "Chevrolet"
          for r in botdb.latest_for(888, {"Chevrolet"}, 20)))

print("\n=== 14. model picker keyboards ===")
botdb.set_brands(999, ["BYD", "Rivian"])
row = botmod.models_button_row(999)
check("Models button appears when a brand has models",
      row and row[0]["callback_data"] == "mods")
botdb.set_brands(999, ["Rivian"])
check("Models button hidden when no brand has models", botmod.models_button_row(999) == [])

botdb.set_brands(999, ["BYD", "Chevrolet"])
mbk = botmod.model_brand_keyboard(999)["inline_keyboard"]
check("brand chooser lists both brands",
      sum(1 for r in mbk for b in r if b["callback_data"].startswith("mb:")) == 2)
check("brand chooser has a back button",
      any(b["callback_data"] == "p:0" for r in mbk for b in r))

botdb.toggle_model(999, "BYD", "Seagull")
mk = botmod.model_keyboard(999, "BYD")["inline_keyboard"]
check("selected model is ticked",
      any("✅" in b["text"] and "Seagull" in b["text"] for r in mk for b in r))
check("model callbacks fit in 64 bytes",
      all(len(b.get("callback_data", "").encode()) <= 64 for r in mk for b in r))
check("model keyboard has all-models and done",
      any(b["callback_data"].startswith("mall:") for r in mk for b in r)
      and any(b["callback_data"] == "done" for r in mk for b in r))
botdb.toggle_model(999, "BYD", "Dolphin")
mbk2 = botmod.model_brand_keyboard(999)["inline_keyboard"]
check("brand chooser shows how many models are picked",
      any("BYD (2)" in b["text"] for r in mbk2 for b in r),
      [b["text"] for r in mbk2 for b in r])

_cfg3 = {"telegram": {"bot_token": "x", "chat_id": "1", "admin_chat_id": "1"},
         "runtime": {"max_items_per_message": 5}}
_b3 = botmod.Bot(_cfg3, lambda *a, **k: None)
summary = _b3.scope_summary(999)
check("summary names the narrowed models",
      "Seagull" in summary and "Dolphin" in summary, summary)
check("scope_text is compact", "BYD" in _b3.scope_text(999, botdb.get_brands(999)))

print("\n=== 15. the announcement is Uzbek Cyrillic ===")
check("announce is Cyrillic", CYR.search(botmod.T["announce"]) is not None)
check("announce mentions models", "модел" in botmod.T["announce"].lower())
check("announce points at /brands", "/brands" in botmod.T["announce"])

print("\n=== 16. mileage buckets ===")
import carfilters as cf  # noqa: E402

check("ten ranges plus unknown", len(cf.MILEAGE_KEYS) == 11, len(cf.MILEAGE_KEYS))
edges = [(0, "km0_10"), (9999, "km0_10"), (10000, "km10_20"), (19999, "km10_20"),
         (20000, "km20_30"), (30000, "km30_40"), (40000, "km40_50"), (49999, "km40_50"),
         (50000, "km50_70"), (69999, "km50_70"), (70000, "km70_100"),
         (99999, "km70_100"), (100000, "km100_150"), (149999, "km100_150"),
         (150000, "km150_200"), (199999, "km150_200"), (200000, "km200_plus"),
         (999999, "km200_plus"), (None, "km_unknown")]
bad = [(km, want, cf.mileage_band(km)) for km, want in edges if cf.mileage_band(km) != want]
check("every boundary lands in the right bucket", not bad, bad)
check("buckets are contiguous - no km falls through",
      all(cf.mileage_band(k) != "km_unknown" for k in range(0, 300000, 997)))

print("\n=== 17. year buckets ===")
yedges = [(2026, "y2026"), (2025, "y2025"), (2024, "y2024"), (2023, "y2023"),
          (2022, "y2022"), (2021, "y2020_2021"), (2020, "y2020_2021"),
          (2019, "y2018_2019"), (2017, "y2015_2017"), (2015, "y2015_2017"),
          (2014, "y2010_2014"), (2010, "y2010_2014"), (2009, "y_older"),
          (1995, "y_older"), (None, "y_unknown")]
ybad = [(y, w, cf.year_band(y)) for y, w in yedges if cf.year_band(y) != w]
check("every year lands in the right bucket", not ybad, ybad)

print("\n=== 18. bucket filtering ===")
botdb.set_brands(1200, [])
botdb.clear_bands(1200)
botdb.clear_years(1200)
samples = [("OLX:b1", 5000, 2026), ("OLX:b2", 15000, 2024), ("OLX:b3", 25000, 2022),
           ("OLX:b4", 65000, 2019), ("OLX:b5", 180000, 2012), ("OLX:b6", 250000, 2008),
           ("OLX:b7", None, None)]
SKEYS = {k for k, _, _ in samples}
for key, km, yr in samples:
    fl = FakeListing(key, f"Car {key}", 9000)
    fl.mileage_km, fl.year = km, yr
    botdb.upsert_listing(fl, "BYD", cf.mileage_band(km), None)


def keys_for(uid):
    return {r["key"] for r in botdb.undelivered_for(uid, None, 200)} & SKEYS


check("nothing selected means everything", keys_for(1200) == SKEYS, keys_for(1200))

botdb.set_bands(1200, ["km0_10"])
check("0-10k keeps only the 5 000 km car", keys_for(1200) == {"OLX:b1"}, keys_for(1200))
botdb.set_bands(1200, ["km200_plus"])
check("200k+ keeps only the 250 000 km car", keys_for(1200) == {"OLX:b6"})
botdb.set_bands(1200, ["km0_10", "km150_200"])
check("two distant buckets union correctly", keys_for(1200) == {"OLX:b1", "OLX:b5"})
botdb.set_bands(1200, ["km_unknown"])
check("unknown bucket matches the NULL-mileage car", keys_for(1200) == {"OLX:b7"})
botdb.set_bands(1200, list(cf.MILEAGE_KEYS))
check("all buckets behaves like no filter", keys_for(1200) == SKEYS)
botdb.clear_bands(1200)

botdb.set_years(1200, ["y2026"])
check("year 2026 alone", keys_for(1200) == {"OLX:b1"})
botdb.set_years(1200, ["y_older"])
check("2009-and-older bucket", keys_for(1200) == {"OLX:b6"})
botdb.set_years(1200, ["y_unknown"])
check("unknown year bucket", keys_for(1200) == {"OLX:b7"})
botdb.clear_years(1200)

botdb.set_bands(1200, ["km10_20", "km20_30"])
botdb.set_years(1200, ["y2024"])
check("mileage AND year combine, not OR", keys_for(1200) == {"OLX:b2"}, keys_for(1200))
botdb.clear_bands(1200)
botdb.clear_years(1200)

for bad_key, fn in (("km999", botdb.toggle_band), ("y9999", botdb.toggle_year)):
    try:
        fn(1200, bad_key)
        check(f"rejects unknown bucket {bad_key}", False, "no error raised")
    except ValueError:
        check(f"rejects unknown bucket {bad_key}", True)
try:
    botdb.set_bands(1200, ["'; DROP TABLE listings; --"])
    check("set_bands rejects injection", False, "no error raised")
except ValueError:
    check("set_bands rejects injection", True)

print("\n=== 19. legacy coarse bands migrate ===")
_c = botdb.connect()
_c.execute("DELETE FROM user_bands WHERE tg_id=1500")
for old in ("under50", "under100"):
    _c.execute("INSERT INTO user_bands(tg_id,band) VALUES(1500,?)", (old,))
_c.commit()
_c.close()
botdb.init()
migrated = botdb.get_bands(1500)
check("old under50 became the five fine buckets",
      {"km0_10", "km10_20", "km20_30", "km30_40", "km40_50"} <= migrated, migrated)
check("old under100 became 50-70 and 70-100", {"km50_70", "km70_100"} <= migrated)
check("no legacy keys survive",
      not (migrated & {"under50", "under100", "under150", "unknown"}))

print("\n=== 20. pickers ===")
botdb.set_bands(1400, ["km20_30"])
mkb = botmod.mileage_keyboard(1400)["inline_keyboard"]
check("mileage picker lists every bucket",
      sum(1 for r in mkb for b in r if b["callback_data"].startswith("km:"))
      == len(cf.MILEAGE_KEYS))
check("selected bucket ticked",
      any("✅" in b["text"] and "20 000" in b["text"] for r in mkb for b in r))
ykb = botmod.year_keyboard(1400)["inline_keyboard"]
check("year picker lists every bucket",
      sum(1 for r in ykb for b in r if b["callback_data"].startswith("yr:"))
      == len(cf.YEAR_KEYS))
check("all picker callbacks fit 64 bytes",
      all(len(b.get("callback_data", "").encode()) <= 64 for r in mkb + ykb for b in r))
bkb = botmod.brand_keyboard(1400, 0)["inline_keyboard"]
check("brand keyboard offers mileage and year",
      any(b["callback_data"] == "km" for r in bkb for b in r)
      and any(b["callback_data"] == "yr" for r in bkb for b in r))

_b5 = botmod.Bot({"telegram": {"bot_token": "x", "chat_id": "1", "admin_chat_id": "1"},
                  "runtime": {"max_items_per_message": 5}}, lambda *a, **k: None)
botdb.set_years(1400, ["y2024"])
sc = _b5.scope_text(1400, botdb.get_brands(1400))
check("scope shows both mileage and year", "🛣" in sc and "📅" in sc, sc)
botdb.clear_bands(1400)
botdb.clear_years(1400)
check("scope stays clean when unrestricted",
      "🛣" not in _b5.scope_text(1400, botdb.get_brands(1400)))

check("grouping headings exist for every bucket",
      set(botmod.BAND_TITLES) == set(cf.MILEAGE_KEYS))
check("scanner and bot agree on the bucket",
      all(ev_tier(k) == botmod.band_of({"mileage_km": k})
          for k in (0, 15000, 55000, 120000, 250000, None)))
check("filters announcement is Cyrillic",
      CYR.search(botmod.T["announce_filters"]) is not None)
check("announcement mentions both new filters",
      "/mileage" in botmod.T["announce_filters"]
      and "/year" in botmod.T["announce_filters"])

print("\n=== 21. /models explains itself in all three cases ===")


class RecordTG:
    def __init__(self):
        self.msgs = []
        self.toasts = []

    def send(self, chat_id, text, reply_markup=None, preview=False):
        self.msgs.append(text)
        return {"message_id": len(self.msgs)}

    def send_checked(self, *a, **k):
        return self.send(*a, **k), None

    def answer_callback(self, cq_id, text=None, alert=False):
        self.toasts.append(text)

    def edit(self, *a, **k):
        return {}

    def edit_markup(self, *a, **k):
        return {}


_b6 = botmod.Bot({"telegram": {"bot_token": "x", "chat_id": "1", "admin_chat_id": "1"},
                  "runtime": {"max_items_per_message": 5}}, lambda *a, **k: None)

# (a) no brand at all
_b6.tg = RecordTG()
botdb.set_brands(2100, [])
_b6.open_model_picker(1, 2100)
check("no brand -> 'choose a brand first'",
      botmod.T["pick_brand_first"] in _b6.tg.msgs, _b6.tg.msgs[:1])

# (b) a brand that has no model list - the case from the screenshot
_b6.tg = RecordTG()
botdb.set_brands(2101, ["Rivian"])
_b6.open_model_picker(1, 2101)
joined = " ".join(_b6.tg.msgs)
check("brand without models does NOT say 'choose a brand first'",
      botmod.T["pick_brand_first"] not in _b6.tg.msgs, _b6.tg.msgs[:1])
check("brand without models names the brand", "Rivian" in joined, joined[:120])
check("brand without models reassures they still get listings",
      "барча" in joined.lower())

# (c) a brand that does have models
_b6.tg = RecordTG()
botdb.set_brands(2102, ["BYD"])
_b6.open_model_picker(1, 2102)
check("brand with models opens the chooser",
      botmod.T["choose_brand_for_models"] in _b6.tg.msgs)

check("Li Auto now has models", modellib.has_models("Li Auto"))
check("Li Auto L9 detected",
      modellib.detect_model("Li Auto", "Li Auto L9 2024 ideal") == "L9")
check("most brands now carry a model list",
      sum(1 for b in brandlib.BRAND_NAMES if modellib.has_models(b)) >= 60,
      sum(1 for b in brandlib.BRAND_NAMES if modellib.has_models(b)))
check("no model list is empty",
      all(modellib.models_for(b) for b in modellib.MODELS))

print("\n" + "=" * 46)
print(f"  {PASS} passed, {FAIL} failed")
print("=" * 46)
sys.exit(1 if FAIL else 0)
