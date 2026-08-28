#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location buckets.

OLX writes the location as "<City> Ташкентская область" — the city first, then the
oblast — so the city is what carries the information. The list below is ordered by how
often each place actually appears in the catalogue, which puts the common choices on
the first page of the picker and keeps the number of taps down.
"""

from __future__ import annotations

import re

from brands import _norm

# key, Uzbek Cyrillic label, aliases matched against the listing's location text
LOCATIONS: list[tuple[str, str, tuple[str, ...]]] = [
    ("tashkent",   "Тошкент шаҳри",   ("ташкент", "toshkent", "tashkent", "тошкент")),
    ("chirchiq",   "Чирчиқ",          ("чирчик", "chirchik", "chirchiq")),
    ("keles",      "Келес",           ("келес", "keles")),
    ("eshonguzar", "Эшонгузар",       ("эшангузар", "эшонгузар", "eshonguzar")),
    ("mirobod",    "Миробод",         ("мирабад", "мирободcity", "mirobod")),
    ("qibray",     "Қибрай",          ("кибрай", "qibray", "қибрай")),
    ("zangiota",   "Зангиота",        ("зангиата", "зангиота", "zangiota")),
    ("yangiyol",   "Янгийўл",         ("янгиюль", "yangiyol", "янгийул")),
    ("olmaliq",    "Олмалиқ",         ("алмалык", "olmaliq", "олмалик")),
    ("nazarbek",   "Назарбек",        ("назарбек", "nazarbek")),
    ("angren",     "Ангрен",          ("ангрен", "angren")),
    ("nurafshon",  "Нурафшон",        ("нурафшан", "нурафшон", "тойтепа", "nurafshon",
                                       "toytepa")),
    ("koksaroy",   "Кўксарой",        ("коксарай", "koksaroy")),
    ("parkent",    "Паркент",         ("паркент", "parkent")),
    ("ohangaron",  "Оҳангарон",       ("ахангаран", "ohangaron", "оҳангарон")),
    ("yangibozor", "Янгибозор",       ("янгибазар", "yangibozor")),
    ("urtachirchiq", "Ўрта Чирчиқ",   ("уртааул", "urtachirchik", "урта чирчик")),
    ("chorvoq",    "Чорвоқ",          ("чарвак", "chorvoq", "чорвок")),
    ("pskent",     "Пискент",         ("пскент", "pskent", "пискент")),
    ("gazalkent",  "Ғазалкент",       ("газалкент", "gazalkent")),
    ("dustobod",   "Дўстобод",        ("дустабад", "dustobod")),
    ("chinoz",     "Чиноз",           ("чиназ", "chinoz")),
    ("bekobod",    "Бекобод",         ("бекабад", "bekobod", "бекобод")),
    ("iskandar",   "Искандар",        ("искандар", "iskandar")),
    ("buka",       "Бўка",            ("бука", "buka", "бўка")),
    ("boshqa_tosh", "Тошкент вилояти (бошқа)",
     ("ташкентская область", "тошкент вилояти", "toshkent viloyati")),
    ("boshqa_viloyat", "Бошқа вилоятлар",
     ("самарканд", "samarkand", "самарқанд", "бухар", "buxoro", "bukhara",
      "андижан", "andijon", "фергана", "фарғона", "fargona", "наманган", "namangan",
      "кашкадар", "qashqadaryo", "сурхандар", "surxondaryo", "навои", "navoiy",
      "джизак", "dzhizak", "jizzax", "сырдар", "sirdaryo", "хорезм", "xorazm",
      "ургенч", "urganch", "нукус", "nukus", "каракалпак", "qoraqalpog",
      "термез", "termiz", "коканд", "qoqon")),
    ("unknown",    "Кўрсатилмаган",   ()),
]

LOCATION_KEYS = tuple(k for k, _, _ in LOCATIONS)
LOCATION_LABELS = {k: label for k, label, _ in LOCATIONS}

# Longest alias first so "ташкентская область" cannot be claimed by a shorter token.
_ALIASES: list[tuple[str, str]] = sorted(
    ((_norm(a), key) for key, _, aliases in LOCATIONS for a in aliases),
    key=lambda pair: -len(pair[0]),
)

# The oblast suffix repeats on nearly every row and would otherwise swamp the city.
_OBLAST = re.compile(r"(ташкентская\s+область|тошкент\s+вилояти|toshkent\s+viloyati"
                     r"|ташкентскаяобласть)")


def detect_location(*texts) -> str:
    """Bucket for a listing's location text.

    The city is matched first, with the oblast suffix stripped, because
    "Келес Ташкентская область" is Keles and not simply "somewhere in the region".
    """
    raw = _norm(" ".join(str(t or "") for t in texts))
    if not raw:
        return "unknown"

    city_part = _OBLAST.sub(" ", raw).strip()
    if city_part:
        for alias, key in _ALIASES:
            if key in ("boshqa_tosh", "unknown") or not alias:
                continue
            if re.search(r"(?<![a-z0-9Ѐ-ӿ])" + re.escape(alias) + r"(?![a-z0-9Ѐ-ӿ])",
                         city_part):
                return key

    # No recognisable city: fall back to whatever oblast is named.
    for alias, key in _ALIASES:
        if alias and alias in raw:
            return key
    return "unknown"


def location_sql(keys, column: str) -> str:
    chosen = [k for k in LOCATION_KEYS if k in set(keys)]
    if not chosen or len(chosen) == len(LOCATION_KEYS):
        return ""
    parts = []
    for key in chosen:
        if key == "unknown":
            parts.append(f"({column} IS NULL OR {column} = 'unknown')")
        else:
            parts.append(f"({column} = '{key}')")
    return " AND (" + " OR ".join(parts) + ") "
