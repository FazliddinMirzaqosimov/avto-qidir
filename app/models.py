#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Per-brand model catalogue and model matching.

Subscribers can narrow a brand down to specific models. A brand with no entry here
simply offers no drill-down and keeps matching on the brand alone, so the catalogue
can grow one brand at a time without breaking anything.
"""

from __future__ import annotations

import re

from brands import _BOUNDARY, _norm

MODELS: dict[str, list[tuple[str, tuple[str, ...]]]] = {
    "BYD": [
        ("Seagull", ("seagull", "seagul", "segull", "сигал", "чайка")),
        ("Dolphin", ("dolphin", "долфин", "дельфин")),
        ("e2", ("e2", "е2")),
        ("e3", ("e3", "е3")),
        ("e6", ("e6", "е6")),
        ("Yuan Up", ("yuan up", "yuanup", "юан ап")),
        ("Yuan Plus / Atto 3", ("yuan plus", "atto 3", "atto3", "атто")),
        ("Chazor", ("chazor", "чазор")),
        ("Song", ("song plus", "song pro", "song l", "сонг")),
        ("Qin", ("qin plus", "qin pro", "qin l", "цинь")),
        ("Han", ("han ev", "han dm", "хан")),
        ("Tang", ("tang ev", "tang dm", "танг")),
        ("Seal", ("seal 05", "seal 06", "seal u", "seal", "сеал")),
        ("Sealion", ("sealion", "sea lion", "сеалион")),
        ("Destroyer", ("destroyer", "дестроер")),
        ("Frigate", ("frigate", "фрегат")),
    ],
    "Chevrolet": [
        ("Onix", ("onix", "оникс")),
        ("Cobalt", ("cobalt", "кобальт")),
        ("Gentra", ("gentra", "джентра", "гентра")),
        ("Nexia", ("nexia", "нексия")),
        ("Malibu", ("malibu", "малибу")),
        ("Tracker", ("tracker", "трекер")),
        ("Captiva", ("captiva", "каптива")),
        ("Equinox", ("equinox", "эквинокс")),
        ("Traverse", ("traverse", "траверс")),
        ("Tahoe", ("tahoe", "тахо")),
        ("Spark", ("spark", "спарк")),
        ("Damas", ("damas", "дамас")),
        ("Labo", ("labo", "лабо")),
        ("Matiz", ("matiz", "матиз")),
        ("Monza", ("monza", "монза")),
        ("Menlo", ("menlo", "менло")),
    ],
    "Daewoo": [
        ("Nexia", ("nexia", "нексия")),
        ("Matiz", ("matiz", "матиз")),
        ("Tico", ("tico", "тико")),
        ("Lacetti", ("lacetti", "лачетти")),
        ("Damas", ("damas", "дамас")),
    ],
    "Dongfeng": [
        ("Nano / EX1", ("nano", "ex1", "нано")),
        ("Forthing", ("forthing", "фортинг")),
        ("Aeolus", ("aeolus", "аеолус")),
        ("Rich", ("rich 6", "рич")),
        ("Glory", ("glory", "глори")),
        ("Shine", ("shine max", "shine", "шайн")),
    ],
    "Hongqi": [
        ("E-QM5", ("e-qm5", "eqm5", "qm5")),
        ("EHS3", ("ehs3",)),
        ("EHS9", ("ehs9",)),
        ("H5", ("h5",)),
        ("HS5", ("hs5",)),
        ("450", ("450",)),
    ],
    "Nammi": [
        ("Nammi 01", ("nammi 01", "nammi01")),
        ("Nammi 06", ("nammi 06", "nammi06")),
        ("Box", ("nammi box",)),
    ],
    "Chery": [
        ("Tiggo 2", ("tiggo 2", "tiggo2")),
        ("Tiggo 4", ("tiggo 4", "tiggo4")),
        ("Tiggo 7", ("tiggo 7", "tiggo7")),
        ("Tiggo 8", ("tiggo 8", "tiggo8")),
        ("Arrizo", ("arrizo", "арризо")),
        ("QQ", ("chery qq", "qq ice")),
    ],
    "Lada": [
        ("Niva", ("niva", "нива")),
        ("Granta", ("granta", "гранта")),
        ("Vesta", ("vesta", "веста")),
        ("Priora", ("priora", "приора")),
        ("Largus", ("largus", "ларгус")),
    ],
    "Kia": [
        ("Sportage", ("sportage", "спортейдж")),
        ("Sorento", ("sorento", "соренто")),
        ("Seltos", ("seltos", "селтос")),
        ("Rio", ("kia rio", "рио")),
        ("K5", ("k5",)),
        ("Carnival", ("carnival", "карнивал")),
        ("EV6", ("ev6",)),
        ("Niro", ("niro", "ниро")),
    ],
    "Hyundai": [
        ("Sonata", ("sonata", "соната")),
        ("Elantra", ("elantra", "элантра")),
        ("Tucson", ("tucson", "туксон")),
        ("Santa Fe", ("santa fe", "santafe", "санта фе")),
        ("Accent", ("accent", "акцент")),
        ("Creta", ("creta", "крета")),
        ("Ioniq", ("ioniq", "ионик")),
        ("Kona", ("kona", "кона")),
    ],
    "Toyota": [
        ("Camry", ("camry", "камри")),
        ("Corolla", ("corolla", "королла")),
        ("RAV4", ("rav4", "rav 4", "рав4")),
        ("Land Cruiser", ("land cruiser", "ленд крузер", "prado", "прадо")),
        ("Prius", ("prius", "приус")),
        ("Highlander", ("highlander", "хайлендер")),
    ],
    "Leapmotor": [
        ("T03", ("t03",)),
        ("C01", ("c01",)),
        ("C10", ("c10",)),
        ("C11", ("c11",)),
        ("A11", ("a11", "a12")),
        ("B10", ("b10",)),
    ],
    "Changan": [
        ("Eado", ("eado", "эадо")),
        ("CS35", ("cs35",)),
        ("CS55", ("cs55",)),
        ("CS75", ("cs75",)),
        ("UNI-T", ("uni-t", "unit")),
        ("UNI-K", ("uni-k", "unik")),
        ("Lumin", ("lumin", "люмин")),
        ("Hunter", ("hunter", "хантер")),
    ],
    "Geely": [
        ("Coolray", ("coolray", "кулрей")),
        ("Atlas", ("atlas", "атлас")),
        ("Emgrand", ("emgrand", "эмгранд")),
        ("Monjaro", ("monjaro", "монжаро")),
        ("Tugella", ("tugella",)),
    ],
    "Haval": [
        ("Jolion", ("jolion", "джолион")),
        ("Dargo", ("dargo", "дарго")),
        ("H6", ("h6",)),
        ("F7", ("f7",)),
    ],
    "GAC": [
        ("Aion S", ("aion s",)),
        ("Aion Y", ("aion y",)),
        ("Aion V", ("aion v",)),
        ("Aion UT", ("aion ut",)),
        ("Trumpchi", ("trumpchi", "трумпчи")),
    ],
    "Jetour": [
        ("Dashing", ("dashing", "дашинг")),
        ("X70", ("x70",)),
        ("X90", ("x90",)),
        ("T2", ("jetour t2",)),
    ],
    "Zeekr": [
        ("001", ("zeekr 001",)),
        ("007", ("zeekr 007",)),
        ("X", ("zeekr x",)),
    ],
    "Tesla": [
        ("Model 3", ("model 3", "model3")),
        ("Model Y", ("model y", "modely")),
        ("Model S", ("model s",)),
        ("Model X", ("model x",)),
    ],
    "Neta": [
        ("Neta V", ("neta v",)),
        ("Neta U", ("neta u",)),
        ("Neta X", ("neta x",)),
    ],
    "Ravon": [
        ("R2", ("ravon r2",)),
        ("R3 Nexia", ("ravon r3",)),
        ("R4", ("ravon r4",)),
        ("Gentra", ("ravon gentra",)),
    ],
    "Nissan": [
        ("Leaf", ("leaf", "лиф")),
        ("Qashqai", ("qashqai", "кашкай")),
        ("X-Trail", ("x-trail", "xtrail", "икстрейл")),
        ("Juke", ("juke", "джук")),
    ],
    "Volkswagen": [
        ("Passat", ("passat", "пассат")),
        ("Tiguan", ("tiguan", "тигуан")),
        ("Polo", ("polo", "поло")),
        ("ID.4", ("id.4", "id4")),
        ("ID.6", ("id.6", "id6")),
    ],
    "BMW": [
        ("3 Series", ("320", "328", "330")),
        ("5 Series", ("520", "528", "530")),
        ("X5", ("x5",)),
        ("i3", ("bmw i3",)),
        ("iX3", ("ix3",)),
    ],
    "Mercedes-Benz": [
        ("C-Class", ("c-class", "c class", "c180", "c200", "c220")),
        ("E-Class", ("e-class", "e class", "e200", "e220", "e300")),
        ("S-Class", ("s-class", "s class", "s500")),
        ("GLE", ("gle",)),
        ("EQE", ("eqe",)),
    ],
}


def models_for(brand: str) -> list[str]:
    """Model names offered for a brand; empty when the brand has no drill-down."""
    return [name for name, _ in MODELS.get(brand, [])]


def has_models(brand: str) -> bool:
    return bool(MODELS.get(brand))


# Longest alias first, so "yuan plus" wins before "yuan up" can claim the text.
_ALIASES: dict[str, list[tuple[str, str]]] = {
    brand: sorted(((_norm(alias), name) for name, aliases in entries for alias in aliases),
                  key=lambda pair: -len(pair[0]))
    for brand, entries in MODELS.items()
}


def detect_model(brand: str | None, *texts) -> str | None:
    """Return the model within `brand` that the ad names, or None."""
    if not brand or brand not in _ALIASES:
        return None
    haystack = _norm(" ".join(str(t or "") for t in texts))
    if not haystack:
        return None
    for alias, name in _ALIASES[brand]:
        if not alias or alias not in haystack:
            continue
        if re.search(r"(?<!" + _BOUNDARY + r")" + re.escape(alias)
                     + r"(?!" + _BOUNDARY + r")", haystack):
            return name
    return None


def model_index(brand: str, name: str) -> int | None:
    names = models_for(brand)
    return names.index(name) if name in names else None


def model_by_index(brand: str, idx: int) -> str | None:
    names = models_for(brand)
    return names[idx] if 0 <= idx < len(names) else None
