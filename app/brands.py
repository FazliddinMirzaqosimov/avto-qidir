#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Brand catalogue and brand matching.

Users subscribe to brands, so every listing has to be mapped onto one. Matching runs
against the normalised ad text, and each brand carries the spellings actually seen in
Uzbek listings (Latin, Cyrillic and common misspellings).
"""

from __future__ import annotations

import re
import unicodedata

# (canonical name, aliases matched against the ad text)
BRANDS: list[tuple[str, tuple[str, ...]]] = [
    ("BYD", ("byd", "бид")),
    ("Chevrolet", ("chevrolet", "шевроле", "chevy", "шевролет", "cobalt", "onix", "gentra",
                   "malibu", "tracker", "captiva", "spark", "nexia", "damas", "labo",
                   "equinox", "traverse", "tahoe", "menlo")),
    ("Leapmotor", ("leapmotor", "leap motor", "липмотор")),
    ("Tesla", ("tesla", "тесла")),
    ("Zeekr", ("zeekr", "зикр", "зеекр")),
    ("Nammi", ("nammi", "намми")),
    ("Hongqi", ("hongqi", "хончи", "хонжи", "хонгци", "hong qi")),
    ("Chery", ("chery", "чери", "черри", "arrizo", "tiggo")),
    ("Changan", ("changan", "чанган", "eado", "uni-t", "uni-k", "hunter")),
    ("Haval", ("haval", "хавал", "хавейл", "jolion", "dargo")),
    ("Geely", ("geely", "джили", "жили", "coolray", "atlas", "emgrand", "monjaro")),
    ("Toyota", ("toyota", "тойота", "camry", "corolla", "rav4", "prius", "land cruiser")),
    ("Kia", ("kia", "киа", "кия", "sportage", "sorento", "seltos", "carnival")),
    ("Hyundai", ("hyundai", "хендай", "хундай", "sonata", "elantra", "tucson", "santa fe",
                 "ioniq", "kona", "creta", "accent")),
    ("Volkswagen", ("volkswagen", "фольксваген", "passat", "tiguan", "polo", "touareg")),
    ("Mercedes-Benz", ("mercedes", "мерседес", "benz", "мерс")),
    ("BMW", ("bmw", "бмв")),
    ("Audi", ("audi", "ауди")),
    ("Nissan", ("nissan", "ниссан", "qashqai", "x-trail", "leaf", "juke")),
    ("Honda", ("honda", "хонда", "civic", "cr-v", "accord")),
    ("Mazda", ("mazda", "мазда")),
    ("Lexus", ("lexus", "лексус")),
    ("Ford", ("ford", "форд", "mustang", "explorer", "focus")),
    ("Renault", ("renault", "рено", "реналт", "duster", "logan", "sandero")),
    ("Peugeot", ("peugeot", "пежо")),
    ("Skoda", ("skoda", "шкода", "octavia", "kodiaq")),
    ("Opel", ("opel", "опель", "astra", "insignia")),
    ("Daewoo", ("daewoo", "дэу", "деу", "matiz", "tico", "lacetti")),
    ("Ravon", ("ravon", "равон")),
    ("Lada", ("lada", "лада", "ваз", "niva", "granta", "vesta")),
    ("GAC", ("gac", "trumpchi", "aion", "аион")),
    ("Great Wall", ("great wall", "greatwall", "грейт вол")),
    ("Dongfeng", ("dongfeng", "dong feng", "донгфенг", "дунфэн", "nano", "forthing")),
    ("JAC", ("jac", "жак")),
    ("Jetour", ("jetour", "джетур", "жетур", "dashing", "traveller")),
    ("Exeed", ("exeed", "эксид", "txl", "vx", "rx")),
    ("Omoda", ("omoda", "омода")),
    ("Jaecoo", ("jaecoo", "жеку", "джейку")),
    ("Wuling", ("wuling", "вулинг", "hongguang", "bingo")),
    ("Baojun", ("baojun", "баоджун")),
    ("MG", ("mg4", "mg 4", "mg5", "mg 5", "mg6", "mg 6", "эмджи")),
    ("Neta", ("neta", "nezha", "нета")),
    ("Xpeng", ("xpeng", "хпенг")),
    ("NIO", ("nio", "нио")),
    ("Li Auto", ("li auto", "lixiang", "li xiang", "лисян")),
    ("Voyah", ("voyah", "воях")),
    ("Avatr", ("avatr", "аватр")),
    ("Deepal", ("deepal", "дипал")),
    ("Arcfox", ("arcfox", "аркфокс")),
    ("Ora", ("ora good", "ora cat", "ора")),
    ("Livan", ("livan", "ливан")),
    ("Bestune", ("bestune", "бестюн")),
    ("Kaiyi", ("kaiyi", "кайи")),
    ("Skywell", ("skywell", "скайвел")),
    ("Maxus", ("maxus", "максус")),
    ("Roewe", ("roewe", "роеве")),
    ("Beijing", ("beijing", "пекин", "бейджинг", "eu5")),
    ("Buick", ("buick", "бьюик", "velite", "excelle")),
    ("Cadillac", ("cadillac", "кадиллак")),
    ("Volvo", ("volvo", "вольво")),
    ("Polestar", ("polestar", "полстар")),
    ("Porsche", ("porsche", "порше", "taycan")),
    ("Land Rover", ("land rover", "landrover", "ленд ровер")),
    ("Jaguar", ("jaguar", "ягуар")),
    ("Mitsubishi", ("mitsubishi", "мицубиси", "outlander", "pajero")),
    ("Subaru", ("subaru", "субару", "forester", "outback")),
    ("Suzuki", ("suzuki", "сузуки", "vitara", "swift")),
    ("Isuzu", ("isuzu", "исузу")),
    ("Infiniti", ("infiniti", "инфинити")),
    ("Acura", ("acura", "акура")),
    ("Genesis", ("genesis", "дженезис")),
    ("Ssangyong", ("ssangyong", "сангйонг")),
    ("Fiat", ("fiat", "фиат")),
    ("Citroen", ("citroen", "ситроен")),
    ("Mini", ("mini cooper", "мини купер")),
    ("Smart", ("smart fortwo", "смарт")),
    ("Dacia", ("dacia", "дачия")),
    ("UAZ", ("uaz", "уаз")),
    ("GAZ", ("газель", "gazel")),
    ("Iran Khodro", ("iran khodro", "samand", "саманд")),
    ("Foton", ("foton", "фотон")),
    ("FAW", ("faw", "фав")),
    ("Zotye", ("zotye", "зоти")),
    ("Lifan", ("lifan", "лифан")),
    ("Brilliance", ("brilliance", "бриллианс")),
    ("Haima", ("haima", "хайма")),
    ("Soueast", ("soueast", "соуист")),
    ("Tank", ("tank 300", "tank 500", "танк")),
    ("Wey", ("wey", "вей")),
    ("Denza", ("denza", "денза")),
    ("Yangwang", ("yangwang", "янгван")),
    ("Venucia", ("venucia", "венусия")),
    ("Kandi", ("kandi", "канди")),
    ("Seres", ("seres", "серес", "aito")),
    ("Rising Auto", ("rising auto", "райзинг")),
    ("Xiaomi", ("xiaomi", "сяоми", "su7")),
    ("Huawei", ("huawei", "хуавей", "luxeed", "maextro")),
    ("Lucid", ("lucid", "люсид")),
    ("Rivian", ("rivian", "ривиан")),
    ("Fisker", ("fisker", "фискер")),
    ("Vinfast", ("vinfast", "винфаст")),
    ("Togg", ("togg", "тогг")),
    ("Mahindra", ("mahindra", "махиндра")),
    ("Proton", ("proton", "протон")),
    ("Daihatsu", ("daihatsu", "дайхатсу")),
    ("Saipa", ("saipa", "сайпа")),
    ("Karry", ("karry", "карри")),
    ("BAIC", ("baic", "баик")),
    ("Xcite", ("xcite", "иксайт")),
    ("Solaris", ("solaris", "соларис")),
    ("Moskvich", ("moskvich", "москвич")),
    ("Evolute", ("evolute", "эволют")),
    ("Sollers", ("sollers", "соллерс")),
]

BRAND_NAMES: list[str] = [name for name, _ in BRANDS]
BRAND_INDEX: dict[str, int] = {name: i for i, name in enumerate(BRAND_NAMES)}


def _norm(text) -> str:
    if text is None:
        return ""
    text = unicodedata.normalize("NFKD", str(text))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text).strip().lower()


# Longest aliases first, so "great wall" wins before a shorter alias can claim the text.
_ALIAS_TABLE: list[tuple[str, str]] = sorted(
    ((_norm(alias), name) for name, aliases in BRANDS for alias in aliases),
    key=lambda pair: -len(pair[0]),
)

_BOUNDARY = r"[a-z0-9Ѐ-ӿ]"


def detect_brand(*texts) -> str | None:
    """Return the canonical brand for an ad, or None when nothing matches."""
    haystack = _norm(" ".join(str(t or "") for t in texts))
    if not haystack:
        return None
    for alias, name in _ALIAS_TABLE:
        if not alias or alias not in haystack:
            continue
        # Token match, so "mg" cannot fire inside "mgnt" nor "byd" inside "bydlo".
        if re.search(r"(?<!" + _BOUNDARY + r")" + re.escape(alias) + r"(?!" + _BOUNDARY + r")",
                     haystack):
            return name
    return None


def brand_by_id(idx: int) -> str | None:
    return BRAND_NAMES[idx] if 0 <= idx < len(BRAND_NAMES) else None


def brand_id(name: str) -> int | None:
    return BRAND_INDEX.get(name)
