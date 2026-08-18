#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline self-test: proves filtering, dedup, catch-up windows and message rendering
work correctly without touching the network."""

import io
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ev_hunter as ev  # noqa: E402

PASS, FAIL = 0, 0


def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name} {detail}")


def L(title, **kw):
    kw.setdefault("posted_at", datetime.now(ev.TASHKENT_TZ))
    ad_id = kw.pop("ad_id", str(abs(hash(title)) % 10**8))
    src = kw.pop("source", "OLX")
    url = kw.pop("url", f"https://www.olx.uz/d/obyavlenie/{ad_id}.html")
    return ev.Listing(src, ad_id, url, title, **kw)


print("\n=== 1. value parsers ===")
check("price '13 900 $' -> 13900 USD", ev.parse_price("13 900 $") == (13900, "USD"))
check("price '175 000 000 сум' -> UZS", ev.parse_price("175 000 000 сум") == (175000000, "UZS"))
check("bare big number assumed UZS", ev.parse_price("180000000")[1] == "UZS")
check("UZS -> USD conversion", ev.to_usd(175_000_000, "UZS", 12800) == 13672,
      ev.to_usd(175_000_000, "UZS", 12800))
check("mileage '45 000 км' -> 45000", ev.parse_mileage_km("45 000 км") == 45000)
check("mileage '32,500 km' -> 32500", ev.parse_mileage_km("32,500 km") == 32500)
check("mileage '18 тыс. км' -> 18000", ev.parse_mileage_km("18 тыс. км") == 18000)
check("mileage bare 45 -> 45000", ev.parse_mileage_km(45) == 45000)
check("year from '2024 г.'", ev.parse_year("2024 г.") == 2024)
check("money format", ev.fmt_money(13900) == "$13 900")

print("\n=== 2. date parsing ===")
now = datetime.now(ev.TASHKENT_TZ)
check("ISO with Z", ev.parse_datetime("2026-08-15T09:30:00Z") is not None)
check("epoch ms", ev.parse_datetime(1755250000000) is not None)
check("'2 soat oldin' ~2h ago",
      abs((now - ev.parse_datetime("2 soat oldin")).total_seconds() - 7200) < 120)
check("'сегодня 14:30' is today",
      ev.parse_datetime("сегодня 14:30").date() == now.date())
check("'вчера 10:00' is yesterday",
      ev.parse_datetime("вчера 10:00").date() == (now - timedelta(days=1)).date())
check("garbage -> None", ev.parse_datetime("qwerty") is None)

print("\n=== 3. powertrain classification ===")
check("BYD Chazor DM-i -> PHEV",
      ev.classify_powertrain(L("BYD Chazor DM-i 2024")) == "PHEV")
check("BYD Yuan Up -> EV", ev.classify_powertrain(L("BYD Yuan Up Flagship 2024")) == "EV")
check("Leapmotor C11 -> EV", ev.classify_powertrain(L("Leapmotor C11 2023")) == "EV")
check("BYD e2 -> EV", ev.classify_powertrain(L("BYD e2 2022")) == "EV")
check("Petrol Cobalt -> None",
      ev.classify_powertrain(L("Chevrolet Cobalt 2022", fuel="бензин")) is None)
check("Malibu with 'benzin' -> None",
      ev.classify_powertrain(L("Malibu 2 2023 benzin avtomat")) is None)
check("explicit electric fuel field -> EV",
      ev.classify_powertrain(L("Some Car 2023", fuel="Электро")) == "EV")

print("\n=== 4. filter rules ===")
# Prefer a live config if one sits next to the code; in a clean checkout (and inside the
# container, where the live config lives on the volume) fall back to the shipped default.
_HERE = os.path.dirname(os.path.abspath(__file__))
_cfg_path = next((p for p in (os.path.join(_HERE, "config.json"),
                              os.path.join(_HERE, "config.default.json"))
                  if os.path.exists(p)), None)
cfg = ev.deep_merge(ev.DEFAULT_CONFIG,
                    json.load(io.open(_cfg_path, encoding="utf-8")) if _cfg_path else {})

cases = [
    ("perfect match kept",
     L("BYD Yuan Up 2024", price_usd=13900, year=2024, mileage_km=12000, city="Tashkent"),
     True, "under50"),
    ("55k km -> under100 band",
     L("BYD Dolphin 2023", price_usd=12500, year=2023, mileage_km=55000, city="Toshkent"),
     True, "under100"),
    ("120k km -> under150 band (was dropped before)",
     L("BYD e2 2022", price_usd=9000, year=2022, mileage_km=120000, city="Tashkent"),
     True, "under150"),
    ("160k km still dropped",
     L("BYD e2 2022", price_usd=9000, year=2022, mileage_km=160000, city="Tashkent"),
     False, ""),
    ("petrol Chevrolet now KEPT (all fuel types)",
     L("Chevrolet Onix 2023 benzin", price_usd=13000, year=2023, mileage_km=30000,
       city="Tashkent"), True, "under50"),
    ("diesel car kept",
     L("Hyundai Santa Fe 2022 dizel", price_usd=16000, year=2022, mileage_km=80000,
       city="Tashkent"), True, "under100"),
    ("2019 dropped",
     L("Tesla Model 3 2019", price_usd=14000, year=2019, mileage_km=40000, city="Tashkent"),
     False, ""),
    ("$21k dropped",
     L("BYD Seal 2024", price_usd=21000, year=2024, mileage_km=10000, city="Tashkent"),
     False, ""),
    ("Samarkand dropped",
     L("BYD Yuan Plus 2023", price_usd=14000, year=2023, mileage_km=20000, city="Samarqand"),
     False, ""),
    ("Seagull KEPT (small EVs are wanted)",
     L("BYD Seagull 2024", price_usd=9000, year=2024, mileage_km=5000, city="Tashkent"),
     True, "under50"),
    ("Changan Ben Ben excluded",
     L("Changan Ben Ben EV 2023", price_usd=9500, year=2023, mileage_km=8000, city="Tashkent"),
     False, ""),
    ("Benni spelling excluded",
     L("Changan Benni E-Star 2024", price_usd=9000, year=2024, mileage_km=4000,
       city="Tashkent"), False, ""),
    ("petrol Malibu kept",
     L("Chevrolet Malibu 2023 benzin", price_usd=14000, year=2023, mileage_km=20000,
       city="Tashkent"), True, "under50"),
    ("charger listing dropped",
     L("Зарядное устройство для электромобиля BYD", price_usd=2000, year=2024, city="Tashkent"),
     False, ""),
    ("Chirchiq (Tashkent region) kept",
     L("Leapmotor T03 2023", price_usd=11000, year=2023, mileage_km=18000, city="Chirchiq"),
     True, "under50"),
    ("unknown location kept",
     L("BYD Chazor DM-i 2024", price_usd=14500, year=2024, mileage_km=8000, city=""),
     True, "under50"),
    ("0 km listing kept now that min_mileage_km is 0",
     L("BYD Yuan Up 2026", price_usd=14000, year=2026, mileage_km=0, city="Tashkent"),
     True, "under50"),
    ("1 200 km listing still kept",
     L("BYD Dolphin 2024", price_usd=14000, year=2024, mileage_km=1200, city="Tashkent"),
     True, "under50"),
    ("missing price still grouped by mileage",
     L("BYD Song Plus EV 2023", year=2023, mileage_km=30000, city="Tashkent"),
     True, "under50"),
    ("unknown mileage -> unknown band",
     L("BYD Song Plus EV 2023", price_usd=12000, year=2023, city="Tashkent"),
     True, "unknown"),
]
for name, listing, want_keep, want_tier in cases:
    keep, tier, reason = ev.evaluate(listing, cfg)
    ok = keep == want_keep and (not want_keep or tier == want_tier)
    check(name, ok, f"-> keep={keep} tier={tier} reason={reason}")

print("\n=== 5. dedup + catch-up window ===")
tmpdb = os.path.join(tempfile.mkdtemp(), "t.db")
state = ev.State(tmpdb)
check("first run has no last_run", state.last_run() is None)
a = L("BYD Yuan Up 2024", ad_id="111", price_usd=13900, year=2024, mileage_km=12000, city="Tashkent")
state.mark_seen(a)
state.commit()
check("ad remembered after mark_seen", state.is_seen("OLX:111"))
check("different ad not seen", not state.is_seen("OLX:222"))
state.set_meta("last_run", (now - timedelta(hours=9)).isoformat())
gap = (now - state.last_run()).total_seconds() / 3600
check("last_run round-trips (9h gap)", 8.9 < gap < 9.1, f"gap={gap:.2f}h")

print("\n=== 6. message rendering ===")
top = [L("BYD Yuan Up Flagship 2024", ad_id="1", price_usd=13900, year=2024,
         mileage_km=12000, city="Tashkent, Yunusobod", owners=1),
       L("Leapmotor T03 2023", ad_id="2", source="Avtoelon", price_usd=10500, year=2023,
         mileage_km=21000, city="Toshkent")]
stretch = [L("BYD Chazor DM-i 2023", ad_id="3", source="Uzum Avto", price_usd=14800, year=2023,
             mileage_km=68000, city="Chirchiq")]
pairs = ev.build_messages(top, stretch, cfg, "since 15 Aug 09:00")
msgs = [m for m, _ in pairs]
check("every listing is attached to a message",
      sum(len(x) for _, x in pairs) == 3, sum(len(x) for _, x in pairs))
body = "\n".join(msgs)
check("one message for 3 items", len(msgs) == 1, f"got {len(msgs)}")
check("title is a hyperlink", '<a href="https://www.olx.uz/d/obyavlenie/1.html">' in body)
check("price shown", "$13 900" in body)
check("mileage shown", "12 000 km" in body)
check("stretch section present", "ALSO WORTH A LOOK" in body)
check("numbering continues into stretch", "<b>3.</b>" in body)
check("under Telegram 4096 limit", all(len(m) <= 4096 for m in msgs))
check("no unescaped stray tags", body.count("<a href=") == 3)

many = [L(f"BYD Yuan Up {i}", ad_id=str(100 + i), price_usd=13000 + i, year=2024,
          mileage_km=10000 + i, city="Tashkent") for i in range(25)]
pairs2 = ev.build_messages(many, [], cfg, "bulk test")
msgs2 = [m for m, _ in pairs2]
check("bulk: all 25 attached exactly once",
      sum(len(x) for _, x in pairs2) == 25, sum(len(x) for _, x in pairs2))
check("25 items split into several messages", len(msgs2) >= 3, f"got {len(msgs2)}")
check("all bulk messages under limit", all(len(m) <= 4096 for m in msgs2),
      f"max={max(len(m) for m in msgs2)}")
check("every ad appears exactly once",
      all(("/" + str(100 + i) + ".html") in "\n".join(msgs2) for i in range(25)))

print("\n=== 7. html escaping ===")
evil = L('BYD <script>alert(1)</script> & "quotes" 2024', ad_id="9", price_usd=13000,
         year=2024, mileage_km=1000, city="Tashkent")
rendered = ev.render_listing(evil, 1, "top")
check("script tag escaped", "<script>" not in rendered)
check("ampersand escaped", "&amp;" in rendered)

print("\n=== 8. extractors ===")
html = '<html><script id="__NEXT_DATA__">{"props":{"ads":[{"id":7,"title":"BYD","url":"/a/7"}]}}</script></html>'
data = ev.extract_script_json(html, "__NEXT_DATA__")
check("__NEXT_DATA__ parsed", data and data["props"]["ads"][0]["id"] == 7)
check("walk() finds nested ad", len(list(ev.walk(data, ("id", "title", "url")))) == 1)
html2 = 'x<script>window.__PRERENDERED_STATE__ = {"a":{"id":1,"title":"t","url":"/u"}};</script>'
check("assigned state blob parsed",
      ev.extract_assigned_json(html2, ["window.__PRERENDERED_STATE__"]) is not None)
html3 = r'<script>window.__PRERENDERED_STATE__ = "{\"a\":{\"id\":2}}";</script>'
check("escaped-string state blob parsed",
      (ev.extract_assigned_json(html3, ["window.__PRERENDERED_STATE__"]) or {}).get("a", {}).get("id") == 2)

print("\n=== 9. OLX offer parser (real API shape) ===")
offer = {
    "id": 987654, "title": "BYD Yuan Up 2024 Flagship",
    "url": "https://www.olx.uz/d/obyavlenie/byd-yuan-up-IDabc.html",
    "created_time": "2026-08-15T09:12:00+05:00",
    "location": {"city": {"name": "Ташкент"}, "region": {"name": "Ташкент"}},
    "params": [
        {"key": "price", "name": "Цена", "value": {"value": 175000000, "currency": "UZS",
                                                   "converted_value": 13672,
                                                   "converted_currency": "USD",
                                                   "label": "175 000 000 сум"}},
        {"key": "motor_year", "value": {"key": "2024", "label": "2024"}},
        {"key": "motor_mileage", "value": {"key": "12000", "label": "12 000"}},
        {"key": "petrol", "value": {"key": "electric", "label": "Электро"}},
    ],
}
parsed = ev.parse_olx_offer(offer, 12800)
check("OLX id", parsed.ad_id == "987654")
check("OLX price uses converted USD", parsed.price_usd == 13672, parsed.price_usd)
check("OLX year", parsed.year == 2024)
check("OLX mileage", parsed.mileage_km == 12000, parsed.mileage_km)
check("OLX city", "ташкент" in ev.norm(parsed.city))
check("OLX classified EV", ev.classify_powertrain(parsed) == "EV")
keep, tier, _ = ev.evaluate(parsed, cfg)
check("OLX offer passes filters in the under50 band", keep and tier == "under50",
      f"keep={keep} tier={tier}")

print("\n=== 10. generic anchor harvester ===")
page = """<html><body>
<a href="/avto/byd-yuan-up-123456"><img alt="BYD Yuan Up"/>BYD Yuan Up 2024 13 900 $ 12 000 км</a>
<a href="/about">About us</a>
</body></html>"""
found = ev.listings_from_html_anchors(page, "Avtoelon", "https://avtoelon.uz", 12800,
                                      re.compile(r"/avto/.+\d"))
check("one listing harvested", len(found) == 1, f"got {len(found)}")
if found:
    check("harvested price", found[0].price_usd == 13900, found[0].price_usd)
    check("harvested year", found[0].year == 2024)
    check("harvested mileage", found[0].mileage_km == 12000, found[0].mileage_km)
    check("harvested absolute url", found[0].url.startswith("https://avtoelon.uz/avto/"))


print("\n=== 11. regression: uuid / substring false positives ===")
noise = ("https://media.auto.uz/announcement-image/060540ea-98c6-4b35-9771-c66aaa3509f2_small.webp "
         "/cars/used/chevrolet/chevrolet-nexia/o_709")
for name in ("Chevrolet Nexia 2017", "Daewoo Tico 2001", "Ravon Gentra 2017",
             "Chevrolet Cobalt 2025", "Chevrolet Tracker 2023", "Chevrolet Spark 2021"):
    car = L(name, price_usd=9000, year=2023, mileage_km=20000, city="Tashkent", raw_text=noise)
    check(f"{name} is NOT electric", ev.classify_powertrain(car) is None,
          f"-> {ev.classify_powertrain(car)}")
check("'chevrolet' does not trigger the bare 'ev' token",
      ev.classify_powertrain(L("Chevrolet Malibu 2023", fuel="Chevrolet")) is None)
check("real BYD e2 still detected", ev.classify_powertrain(L("BYD e2 2024")) == "EV")
check("real Leapmotor C11 still detected", ev.classify_powertrain(L("Leapmotor C11 2023")) == "EV")
check("blob strips urls", "media" not in ev._clean_blob("see https://media.auto.uz/x.webp now"))
check("blob strips hex ids", "060540ea" not in ev._clean_blob("id 060540ea-98c6 car"))

print("\n=== 12. new site parsers ===")
ael = """<script>listing.items.push({"city":"gorod-tashkent","attributes":{"model":"Yuan UP","brand":"BYD"},
"lastUpdate":"2026-08-15T15:55:39+05:00","unitPrice":14500,"url":"https:\\/\\/avtoelon.uz\\/a\\/show\\/123"});</script>
<div id="advert-123"><div>BYD Yuan UP</div><div>2024&nbsp;г.,</div><div>Электричество, 25 000 км</div></div>"""
got = ev.parse_avtoelon_html(ael, 12800)
check("avtoelon: one ad parsed", len(got) == 1, f"got {len(got)}")
if got:
    a = got[0]
    check("avtoelon price (y.e. = USD)", a.price_usd == 14500, a.price_usd)
    check("avtoelon year", a.year == 2024, a.year)
    check("avtoelon mileage", a.mileage_km == 25000, a.mileage_km)
    check("avtoelon city", "tashkent" in ev.norm(a.city), a.city)
    check("avtoelon url", a.url.endswith("/a/show/123"), a.url)
    check("avtoelon detected as EV", ev.classify_powertrain(a) == "EV")
    check("avtoelon passes filters", ev.evaluate(a, cfg)[0])

ld = """<script type="application/ld+json">{"@context":"https://schema.org","@type":"ItemList",
"itemListElement":[{"@type":"ListItem","item":{"@type":"Vehicle",
"url":"https://auto.uz/cars/used/byd/byd-yuan-plus/o_555","name":"BYD Yuan Plus 2023",
"vehicleModelDate":"2023","mileageFromOdometer":{"@type":"QuantitativeValue","value":31000,"unitCode":"KMT"},
"offers":{"@type":"Offer","price":179000000,"priceCurrency":"UZS"}}}]}</script>"""
got2 = ev.parse_autouz_jsonld(ld, "Avto.uz", "https://avto.uz", 12800)
check("auto.uz: one vehicle parsed", len(got2) == 1, f"got {len(got2)}")
if got2:
    v = got2[0]
    check("auto.uz id from o_NNN", v.ad_id == "555", v.ad_id)
    check("auto.uz UZS converted to USD", v.price_usd == 13984, v.price_usd)
    check("auto.uz year", v.year == 2023)
    check("auto.uz mileage", v.mileage_km == 31000)
    check("auto.uz detected as EV", ev.classify_powertrain(v) == "EV")

print(f"\n{'=' * 46}\n  {PASS} passed, {FAIL} failed\n{'=' * 46}\n")
sys.exit(1 if FAIL else 0)
