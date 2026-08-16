# -*- coding: utf-8 -*-
"""Replays the saved debug/ dumps through the real parsers and explains every rejection."""
import io, os, re, json, collections
import ev_hunter as ev

cfg = ev.deep_merge(ev.DEFAULT_CONFIG, json.load(io.open("config.json", encoding="utf-8")))
RATE = 12800.0

PATTERNS = {
    "avtoelon": (r"/avto/.+\d", "Avtoelon", "https://avtoelon.uz"),
    "mashina":  (r"/(car|cars|ad|e?lon)/", "Mashina.uz", "https://mashina.uz"),
    "avto.uz":  (r"/cars?/", "Avto.uz", "https://avto.uz"),
    "uzum":     (r"/(car|cars|auto|ad)/", "Uzum Avto", "https://uzumavto.uz"),
}

all_listings, by_source = [], collections.Counter()
for fn in sorted(os.listdir("debug")):
    if not fn.endswith(".txt"):
        continue
    body = io.open(os.path.join("debug", fn), encoding="utf-8", errors="replace").read()
    body = body.split("=" * 80, 1)[-1].lstrip("\n")
    got = []
    if fn.startswith("olx_api") and "error" not in fn:
        try:
            data = json.loads(body)
            for off in data.get("data", []):
                p = ev.parse_olx_offer(off, RATE)
                if p: got.append(p)
        except Exception as e:
            print("  ! could not parse", fn, e)
    else:
        for key, (pat, name, base) in PATTERNS.items():
            if fn.startswith(key):
                got = ev.listings_from_json_state(body, name, base, RATE) or \
                      ev.listings_from_html_anchors(body, name, base, RATE, re.compile(pat))
                break
    for g in got:
        by_source[g.source] += 1
    all_listings.extend(got)

uniq = {l.key: l for l in all_listings}
print(f"\nParsed {len(all_listings)} rows ({len(uniq)} unique) from the saved dumps")
for s, n in by_source.most_common():
    print(f"   {s:<12} {n}")

reasons = collections.Counter()
evs, kept = [], []
for l in uniq.values():
    pt = ev.classify_powertrain(l)
    keep, tier, reason = ev.evaluate(l, cfg)
    r = re.sub(r"\$?\d[\d\s,]*", "N", reason)
    if keep:
        kept.append((tier, l)); reasons["KEPT"] += 1
    else:
        reasons[r] += 1
    if pt: evs.append((pt, keep, reason, l))

print("\n--- verdicts ---")
for r, n in reasons.most_common():
    print(f"   {n:>4}  {r}")

print(f"\n--- every electric/PHEV the parsers recognised ({len(evs)}) ---")
for pt, keep, reason, l in sorted(evs, key=lambda x: (not x[1], x[3].price_usd or 0)):
    flag = "KEEP" if keep else "drop"
    print(f"  [{flag}] {pt:<4} {ev.fmt_money(l.price_usd):>9} | {str(l.year or '?'):>4} | "
          f"{ev.fmt_km(l.mileage_km):>12} | {l.source:<10} | {l.title[:48]}")
    if not keep:
        print(f"           reason: {reason}")
