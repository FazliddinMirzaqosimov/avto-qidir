#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Mileage and year buckets — the single definition used everywhere.

The filter (SQL), the Telegram picker (labels) and the message grouping (headings) all
read these tables, so a bucket cannot mean one thing in the query and another in the
message. Keys are code constants and are validated on write, which is what makes it safe
to interpolate the generated SQL.

Each bucket is a half-open range [lo, hi): lo=None means "no lower bound", hi=None means
"no upper bound", and both None means the value is missing on the listing.
"""

from __future__ import annotations

# key, Uzbek Cyrillic label, lo (inclusive), hi (exclusive)
MILEAGE_BANDS: list[tuple[str, str, int | None, int | None]] = [
    ("km0_10",     "0 – 10 000 км",         0,       10_000),
    ("km10_20",    "10 000 – 20 000 км",    10_000,  20_000),
    ("km20_30",    "20 000 – 30 000 км",    20_000,  30_000),
    ("km30_40",    "30 000 – 40 000 км",    30_000,  40_000),
    ("km40_50",    "40 000 – 50 000 км",    40_000,  50_000),
    ("km50_70",    "50 000 – 70 000 км",    50_000,  70_000),
    ("km70_100",   "70 000 – 100 000 км",   70_000,  100_000),
    ("km100_150",  "100 000 – 150 000 км",  100_000, 150_000),
    ("km150_200",  "150 000 – 200 000 км",  150_000, 200_000),
    ("km200_plus", "200 000+ км",           200_000, None),
    # Not one of the ten ranges, but without it a subscriber who sets any mileage filter
    # could never reach an ad that simply omits its odometer reading.
    ("km_unknown", "Кўрсатилмаган",         None,    None),
]

# key, label, lo (inclusive), hi (inclusive - years read more naturally closed)
YEAR_BANDS: list[tuple[str, str, int | None, int | None]] = [
    ("y2026",      "2026",                  2026, 2026),
    ("y2025",      "2025",                  2025, 2025),
    ("y2024",      "2024",                  2024, 2024),
    ("y2023",      "2023",                  2023, 2023),
    ("y2022",      "2022",                  2022, 2022),
    ("y2020_2021", "2020 – 2021",           2020, 2021),
    ("y2018_2019", "2018 – 2019",           2018, 2019),
    ("y2015_2017", "2015 – 2017",           2015, 2017),
    ("y2010_2014", "2010 – 2014",           2010, 2014),
    ("y_older",    "2009 ва ундан олдин",   None, 2009),
    ("y_unknown",  "Кўрсатилмаган",         None, None),
]

MILEAGE_KEYS = tuple(k for k, _, _, _ in MILEAGE_BANDS)
YEAR_KEYS = tuple(k for k, _, _, _ in YEAR_BANDS)

MILEAGE_LABELS = {k: label for k, label, _, _ in MILEAGE_BANDS}
YEAR_LABELS = {k: label for k, label, _, _ in YEAR_BANDS}

_MILEAGE = {k: (lo, hi) for k, _, lo, hi in MILEAGE_BANDS}
_YEAR = {k: (lo, hi) for k, _, lo, hi in YEAR_BANDS}


# ------------------------------------------------------------------ classification ---

def mileage_band(km: int | None) -> str:
    if km is None:
        return "km_unknown"
    for key, _, lo, hi in MILEAGE_BANDS:
        if lo is None:
            continue
        if km >= lo and (hi is None or km < hi):
            return key
    return "km_unknown"


def year_band(year: int | None) -> str:
    if year is None:
        return "y_unknown"
    for key, _, lo, hi in YEAR_BANDS:
        if lo is None and hi is None:
            continue
        if (lo is None or year >= lo) and (hi is None or year <= hi):
            return key
    return "y_unknown"


# --------------------------------------------------------------------------- SQL ---

def mileage_sql(keys, column: str) -> str:
    """OR-ed range conditions for the chosen mileage buckets ('' means no restriction)."""
    chosen = [k for k in MILEAGE_KEYS if k in set(keys)]
    if not chosen or len(chosen) == len(MILEAGE_KEYS):
        return ""
    parts = []
    for key in chosen:
        lo, hi = _MILEAGE[key]
        if lo is None and hi is None:
            parts.append(f"({column} IS NULL)")
        elif hi is None:
            parts.append(f"({column} IS NOT NULL AND {column} >= {int(lo)})")
        else:
            parts.append(f"({column} IS NOT NULL AND {column} >= {int(lo)} "
                         f"AND {column} < {int(hi)})")
    return " AND (" + " OR ".join(parts) + ") "


def year_sql(keys, column: str) -> str:
    chosen = [k for k in YEAR_KEYS if k in set(keys)]
    if not chosen or len(chosen) == len(YEAR_KEYS):
        return ""
    parts = []
    for key in chosen:
        lo, hi = _YEAR[key]
        if lo is None and hi is None:
            parts.append(f"({column} IS NULL)")
        elif lo is None:
            parts.append(f"({column} IS NOT NULL AND {column} <= {int(hi)})")
        elif hi is None:
            parts.append(f"({column} IS NOT NULL AND {column} >= {int(lo)})")
        else:
            parts.append(f"({column} IS NOT NULL AND {column} >= {int(lo)} "
                         f"AND {column} <= {int(hi)})")
    return " AND (" + " OR ".join(parts) + ") "


# The four coarse bands this replaced, so existing subscriptions survive the upgrade.
LEGACY_MILEAGE = {
    "under50":  ["km0_10", "km10_20", "km20_30", "km30_40", "km40_50"],
    "under100": ["km50_70", "km70_100"],
    "under150": ["km100_150"],
    "unknown":  ["km_unknown"],
}
