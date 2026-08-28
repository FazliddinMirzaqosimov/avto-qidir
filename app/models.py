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


# Second wave of brands. Kept separate from the block above only for readability;
# both are merged into MODELS below.
_MORE: dict[str, list[tuple[str, tuple[str, ...]]]] = {
    "Li Auto": [
        ("L6", ("li l6", "l6")), ("L7", ("li l7", "l7")), ("L8", ("li l8", "l8")),
        ("L9", ("li l9", "l9")), ("Mega", ("li mega",)), ("i8", ("li i8",)),
    ],
    "Xpeng": [
        ("P5", ("xpeng p5", "p5")), ("P7", ("xpeng p7", "p7")),
        ("G3", ("xpeng g3", "g3")), ("G6", ("xpeng g6", "g6")),
        ("G9", ("xpeng g9", "g9")), ("X9", ("xpeng x9",)),
    ],
    "NIO": [
        ("ES6", ("es6",)), ("ES8", ("es8",)), ("ET5", ("et5",)),
        ("ET7", ("et7",)), ("EC6", ("ec6",)),
    ],
    "Voyah": [("Free", ("voyah free",)), ("Dream", ("voyah dream",)),
              ("Passion", ("voyah passion",))],
    "Avatr": [("011", ("avatr 011",)), ("11", ("avatr 11",)), ("12", ("avatr 12",))],
    "Deepal": [("S05", ("deepal s05", "s05")), ("S07", ("deepal s07", "s07")),
               ("SL03", ("sl03",)), ("L07", ("deepal l07",))],
    "Zeekr": [("001", ("zeekr 001",)), ("007", ("zeekr 007",)), ("X", ("zeekr x",)),
              ("009", ("zeekr 009",)), ("7X", ("zeekr 7x",))],
    "Ora": [("Good Cat", ("ora good cat", "good cat")), ("Funky Cat", ("funky cat",)),
            ("Lightning Cat", ("lightning cat",))],
    "Skywell": [("ET5", ("skywell et5",)), ("BE11", ("be11",))],
    "Livan": [("X3 Pro", ("livan x3",)), ("7", ("livan 7",)), ("9", ("livan 9",))],
    "Bestune": [("T77", ("t77",)), ("B70", ("b70",)), ("Pony", ("bestune pony", "pony"))],
    "Beijing": [("EU5", ("eu5",)), ("U5 Plus", ("u5 plus",)), ("X7", ("beijing x7",))],
    "Buick": [("Velite", ("velite",)), ("Excelle", ("excelle",)),
              ("Envision", ("envision",)), ("Encore", ("encore",))],
    "Great Wall": [("Poer", ("poer",)), ("Wingle", ("wingle",))],
    "JAC": [("iEV7S", ("iev7s",)), ("S3", ("jac s3",)), ("T8", ("jac t8",)),
            ("J7", ("jac j7",))],
    "Omoda": [("C5", ("omoda c5", "c5")), ("S5", ("omoda s5",)), ("E5", ("omoda e5",))],
    "Jaecoo": [("J7", ("jaecoo j7",)), ("J8", ("jaecoo j8",))],
    "Exeed": [("TXL", ("txl",)), ("VX", ("exeed vx",)), ("RX", ("exeed rx",)),
              ("LX", ("exeed lx",))],
    "Wuling": [("Hongguang Mini", ("hongguang mini", "mini ev")),
               ("Bingo", ("bingo",)), ("Air EV", ("air ev",))],
    "MG": [("MG4", ("mg4", "mg 4")), ("MG5", ("mg5", "mg 5")), ("MG6", ("mg6", "mg 6")),
           ("ZS", ("mg zs",)), ("HS", ("mg hs",))],
    "Maxus": [("Euniq", ("euniq",)), ("T60", ("t60",)), ("D60", ("d60",))],
    "Volvo": [("XC40", ("xc40",)), ("XC60", ("xc60",)), ("XC90", ("xc90",)),
              ("S60", ("volvo s60",)), ("S90", ("volvo s90",))],
    "Polestar": [("Polestar 2", ("polestar 2",)), ("Polestar 3", ("polestar 3",)),
                 ("Polestar 4", ("polestar 4",))],
    "Mitsubishi": [("Outlander", ("outlander",)), ("Pajero", ("pajero",)),
                   ("Lancer", ("lancer",)), ("ASX", ("asx",))],
    "Subaru": [("Forester", ("forester",)), ("Outback", ("outback",)),
               ("Impreza", ("impreza",)), ("XV", ("subaru xv",))],
    "Suzuki": [("Vitara", ("vitara",)), ("Swift", ("swift",)), ("Jimny", ("jimny",))],
    "Lexus": [("RX", ("lexus rx",)), ("LX", ("lexus lx",)), ("NX", ("lexus nx",)),
              ("ES", ("lexus es",)), ("GX", ("lexus gx",))],
    "Honda": [("Civic", ("civic",)), ("CR-V", ("cr-v", "crv")), ("Accord", ("accord",)),
              ("Fit", ("honda fit",)), ("e:NS1", ("ens1", "e:ns1"))],
    "Mazda": [("Mazda 3", ("mazda 3", "mazda3")), ("Mazda 6", ("mazda 6", "mazda6")),
              ("CX-5", ("cx-5", "cx5")), ("CX-9", ("cx-9", "cx9"))],
    "Ford": [("Focus", ("ford focus",)), ("Mustang", ("mustang",)),
             ("Explorer", ("explorer",)), ("Transit", ("transit",))],
    "Peugeot": [("208", ("peugeot 208", "e-208")), ("2008", ("peugeot 2008", "e-2008")),
                ("308", ("peugeot 308",)), ("3008", ("peugeot 3008",))],
    "Renault": [("Duster", ("duster",)), ("Logan", ("logan",)), ("Sandero", ("sandero",)),
                ("Zoe", ("renault zoe", "zoe")), ("Kaptur", ("kaptur",))],
    "Skoda": [("Octavia", ("octavia",)), ("Rapid", ("skoda rapid",)),
              ("Kodiaq", ("kodiaq",)), ("Karoq", ("karoq",))],
    "Opel": [("Astra", ("astra",)), ("Insignia", ("insignia",)),
             ("Mokka", ("mokka", "mokka-e")), ("Corsa", ("corsa",))],
    "UAZ": [("Patriot", ("patriot",)), ("Hunter", ("uaz hunter",)),
            ("Buhanka", ("buhanka", "буханка"))],
    "Foton": [("Tunland", ("tunland",)), ("Aumark", ("aumark",))],
    "FAW": [("Bestune T77", ("faw t77",)), ("Besturn", ("besturn",))],
    "Tank": [("Tank 300", ("tank 300",)), ("Tank 500", ("tank 500",))],
    "Denza": [("D9", ("denza d9",)), ("N7", ("denza n7",)), ("N9", ("denza n9",))],
    "Seres": [("Aito M5", ("aito m5", "m5")), ("Aito M7", ("aito m7", "m7")),
              ("Aito M9", ("aito m9", "m9"))],
    "Xiaomi": [("SU7", ("su7",)), ("YU7", ("yu7",))],
    "Vinfast": [("VF3", ("vf3",)), ("VF5", ("vf5",)), ("VF6", ("vf6",)),
                ("VF8", ("vf8",))],
    "BAIC": [("EU5", ("baic eu5",)), ("X55", ("x55",)), ("BJ40", ("bj40",))],
    "Moskvich": [("3", ("moskvich 3",)), ("6", ("moskvich 6",)), ("3e", ("moskvich 3e",))],
    "Evolute": [("i-Pro", ("i-pro",)), ("i-Joy", ("i-joy",)), ("i-Van", ("i-van",))],
    "Jetta": [("VS5", ("vs5",)), ("VS7", ("vs7",)), ("VA3", ("va3",))],
    "Kaiyi": [("X3", ("kaiyi x3",)), ("E5", ("kaiyi e5",))],
    "Forthing": [("T5 Evo", ("t5 evo",)), ("Friday", ("forthing friday",))],
}

for _brand, _entries in _MORE.items():
    MODELS.setdefault(_brand, [])
    _existing = {n for n, _ in MODELS[_brand]}
    MODELS[_brand].extend((n, a) for n, a in _entries if n not in _existing)


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
