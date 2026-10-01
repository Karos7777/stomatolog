"""Сверка клиник с официальным реестром лицензий Минздрава КР.

Лицензия выдаётся юрлицу (ОсОО «…» или ИП) на конкретный адрес, а в 2ГИС клиника
известна под брендом. Поэтому сопоставляем двумя путями — по адресу (улица + дом)
и по названию (с транслитерацией латиницы) — и честно говорим, насколько уверены.
"""
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REGISTRY_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "registry"

_STREET_WORDS = r"(улица|ул\.?|проспект|пр-т|пр\.?|бульвар|б-р|переулок|пер\.?|микрорайон|мкр\.?|мкрн\.?|" \
                r"жилмассив|ж/м|городок|площадь|пл\.?|шоссе|тупик|туп\.?)"
_HOUSE = re.compile(r"(\d+[а-яa-z]?(?:/\d+[а-яa-z]?)?)")
_GENERIC = {"осоо", "ип", "оф", "оао", "зао", "стоматология", "стоматологический", "стоматологическая",
            "стоматологии", "стоматологическое", "клиника", "клиники", "клиник", "центр", "медицинский",
            "медицинская", "медицинское", "семейная", "семейный", "детская", "детский", "dental", "дентал",
            "дент", "dent", "стом", "stom", "clinic", "плюс", "plus", "kg", "кг", "лтд", "ltd", "и", "доктор",
            "dr", "студия", "studio", "сервис", "service", "центра", "современной", "стоматологий", "кабинет",
            "smile", "смайл", "лечебно", "диагностический", "здоровье", "медикал", "medical", "дента", "denta",
            "стар", "star", "денталь", "имплант", "implant", "стоматолога", "стоматологов", "зубной", "врач", "стоматолог", "group", "груп", "групп", "клиникс", "медцентр"}
_TRANSLIT = [("ouse", "аус"), ("ou", "ау"), ("ai", "ай"), ("ei", "ей"), ("oi", "ой"), ("ee", "и"), ("oo", "у"), ("shch", "щ"), ("sch", "щ"), ("sh", "ш"), ("ch", "ч"), ("zh", "ж"), ("kh", "х"), ("ts", "ц"),
             ("ya", "я"), ("yu", "ю"), ("yo", "е"), ("ph", "ф"), ("th", "т"), ("ck", "к"), ("x", "кс"),
             ("a", "а"), ("b", "б"), ("c", "к"), ("d", "д"), ("e", "е"), ("f", "ф"), ("g", "г"), ("h", "х"),
             ("i", "и"), ("j", "дж"), ("k", "к"), ("l", "л"), ("m", "м"), ("n", "н"), ("o", "о"), ("p", "п"),
             ("q", "к"), ("r", "р"), ("s", "с"), ("t", "т"), ("u", "у"), ("v", "в"), ("w", "в"), ("y", "и"),
             ("z", "з")]

SCOPE_TERMS = {
    "терапия": ("терапевт",),
    "хирургия": ("хирург",),
    "ортопедия (коронки, протезы)": ("ортопед",),
    "ортодонтия (брекеты)": ("ортодонт",),
    "имплантация": ("имплант",),
    "анестезия/наркоз": ("анестез", "наркоз", "седац"),
    "рентген": ("рентген", "r-исслед"),
    "общая практика": ("общей практик",),
}
# что из услуг клиники требует какой профиль в лицензии
SERVICE_NEEDS = [
    (("имплант", "синус", "хирург", "удален", "челюстно"), "хирургия"),
    (("ортодонт", "брекет", "элайнер"), "ортодонтия (брекеты)"),
    (("седац", "наркоз", "во сне"), "анестезия/наркоз"),
    (("ортопед", "протез", "коронк", "винир"), "ортопедия (коронки, протезы)"),
]


def _norm(s: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (s or "").lower().replace("ё", "е").replace("э", "е")).strip()


def translit(s: str) -> str:
    s = _norm(s)
    for lat, cyr in _TRANSLIT:
        s = s.replace(lat, cyr)
    return s


@lru_cache(maxsize=300_000)
def _lev(a: str, b: str, limit: int = 99) -> int:
    """Расстояние Левенштейна с ранним выходом, когда оно заведомо больше limit."""
    if a == b:
        return 0
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        if min(cur) > limit:
            return limit + 1
        prev = cur
    return prev[-1]


def similar(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if a == b:
        return True
    limit = 1 if max(len(a), len(b)) <= 6 else 2
    return _lev(a, b, limit) <= limit


def parse_address(addr: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """'улица Исы Ахунбаева, 42а' → ('исы ахунбаева', '42а'); '8-й микрорайон, 83' → ('мкр8', '83').
    Улица — набор слов: в реестре пишут «А.Дуйшеева», в 2ГИС — «Арстанбека Дуйшеева»."""
    s = _norm(addr)
    if not s:
        return None, None
    s = re.sub(r"\(.*?\)", " ", s)
    numeric = re.search(r"(\d+)\s*-?\s*(?:го\s+)?(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|"
                        r"ноября|декабря)|(\d+)\s*-?\s*я\s+линия", s)
    if numeric:
        street = (numeric.group(2) + numeric.group(1)) if numeric.group(2) else "линия" + numeric.group(3)
        h = _HOUSE.search(s[numeric.end():])
        return street, (h.group(1) if h else None)
    mkr = re.search(r"(\d+)\s*-?\s*й?\s*(микрорайон|мкр\.?|мкрн\.?)|(микрорайон|мкр\.?|мкрн\.?)\s*(\d+)(?![\d/])", s)
    if mkr:
        street = "мкр" + (mkr.group(1) or mkr.group(4))
        rest = s[mkr.end():]
    else:
        m = re.search(r"[,\s](\d+[а-яa-z]?(?:/\d+[а-яa-z]?)?)(?![а-яa-z]{2})", s)
        street_part = s[:m.start()] if m else s
        street_part = re.sub(_STREET_WORDS, " ", street_part)
        words = [w.strip("-") for w in re.split(r"[\s,.]+", street_part)]
        words = [w for w in words if len(w) > 1 and not re.search(r"\d", w) or re.fullmatch(r"[а-я]+-\d+", w or "")]
        street = " ".join(words) if words else None
        rest = s[m.start():] if m else ""
    h = _HOUSE.search(rest)
    return street, (h.group(1) if h else None)


def street_words(street: Optional[str]) -> List[str]:
    return [w for w in (street or "").split() if len(w) >= 4 or re.search(r"\d", w)]


def same_street(a: Optional[str], b: Optional[str]) -> bool:
    if not a or not b:
        return False
    wa, wb = street_words(a), street_words(b)
    return any(x == y or (not re.search(r"\d", x + y) and similar(x, y)) for x in wa for y in wb)


def _main_number(house: Optional[str]) -> Optional[str]:
    if not house:
        return None
    m = re.match(r"\d+", house)
    return m.group() if m else None


def name_tokens(name: Optional[str], fallback: bool = False) -> List[str]:
    s = translit(re.sub(r"[«»\"“”'()]", " ", name or ""))
    toks = [t for t in re.split(r"[\s,.\-–/]+", s) if t]
    distinctive = [t for t in toks if t not in _GENERIC and len(t) >= 4]
    if distinctive or not fallback:
        return distinctive
    # «Дента kg» — все слова общие: сравниваем по ним, но только вместе с совпавшим адресом
    return [t for t in toks if len(t) >= 4 and t not in {"осоо", "клиника", "центр", "стоматология",
                                                          "стоматологический", "стоматолога", "кабинет"}]


@lru_cache(maxsize=1)
def load_registry() -> Dict:
    lic_path = REGISTRY_DIR / "medical_licenses_bishkek.json"
    un_path = REGISTRY_DIR / "unlicensed.json"
    licenses = json.loads(lic_path.read_text(encoding="utf-8")) if lic_path.exists() else {"meta": {}, "records": []}
    unlicensed = json.loads(un_path.read_text(encoding="utf-8")) if un_path.exists() else {"meta": {}, "records": []}
    street_index: Dict[str, List[Dict]] = {}
    for rec in licenses["records"]:
        rec["_street"], rec["_house"] = parse_address(rec["address"])
        rec["_tokens"] = name_tokens(rec["name"], fallback=True)
        if rec["dental"]:
            for w in street_words(rec["_street"]):
                street_index.setdefault(w, []).append(rec)
    for rec in unlicensed["records"]:
        rec["_street"], rec["_house"] = parse_address(rec["address"])
    return {"licenses": licenses, "unlicensed": unlicensed, "street_index": street_index,
            "dental": [r for r in licenses["records"] if r["dental"]]}


def _address_match(street, house, rec) -> Optional[str]:
    if not street or not house or not rec.get("_street") or not rec.get("_house"):
        return None
    if not same_street(street, rec["_street"]):
        return None
    if house == rec["_house"]:
        return "exact"
    if _main_number(house) == _main_number(rec["_house"]):
        return "same_building"
    if rec["_house"].startswith(house) and len(rec["_house"]) - len(house) <= 2:
        return "probable"   # в реестре номер дома слился с номером помещения: «10618» вместо «106, оф. 18»
    return None


_VOWELS = set("аеиоуыюяйьъ")


def _skeleton(t: str) -> str:
    return "".join(ch for ch in t if ch not in _VOWELS)


def _token_strength(a: str, b: str) -> int:
    """2 — то же слово, 1 — похоже, 0 — нет. Для названий строже, чем для улиц: «Медикон» ≠ «Медикос»."""
    if a == b or (min(len(a), len(b)) >= 8 and _lev(a, b, 1) <= 1):
        return 2
    if abs(len(a) - len(b)) > 3 and not (len(a) >= 5 and len(b) >= 5 and (a in b or b in a)):
        return 0
    if similar(a, b) or (len(a) >= 5 and len(b) >= 5 and (a in b or b in a)):
        return 1
    ska, skb = _skeleton(a), _skeleton(b)
    if len(ska) >= 3 and ska == skb:
        return 1
    return 0


def _name_strength(tokens: List[str], rec) -> int:
    return max((_token_strength(a, b) for a in tokens for b in rec["_tokens"]), default=0)


def _full_name_match(tokens: List[str], rec) -> bool:
    """Название совпадает целиком, а не одним словом: «Лайк Дент» = «Лайк-Дент», но «Улыбка» ≠ «Твоя улыбка»."""
    reg = rec["_tokens"]
    if not tokens or not reg:
        return False
    clinic_in_reg = all(any(_token_strength(a, b) == 2 for b in reg) for a in tokens)
    extra = [b for b in reg if not any(_token_strength(a, b) == 2 for a in tokens)]
    if len(tokens) == 1 and len(tokens[0]) < 6:
        return False     # «Профи», «Вита», «Семья» — слишком общие слова для вывода по одному названию
    return clinic_in_reg and (not extra or (len(tokens) >= 2 and len(extra) <= 1))


_PATRONYMIC = re.compile(r"(вич|вна|вне|вичу|овне|евне|кызы|уулу)$")


def is_person(rec) -> bool:
    name = _norm(rec["name"])
    return name.startswith("ип ") or any(_PATRONYMIC.search(t) for t in name.split())


def _person_token(a: str, b: str) -> bool:
    """Фамилии и имена в реестре стоят в разных падежах: «Абдылдаев» / «Абдылдаеву»."""
    if a == b:
        return True
    if min(len(a), len(b)) >= 5 and abs(len(a) - len(b)) <= 3:
        stem = min(len(a), len(b)) - 2
        return a[:stem] == b[:stem]
    return False


def _person_match(doctors: List[List[str]], rec) -> bool:
    """ИП на имя врача клиники: совпали и фамилия, и имя."""
    holder = rec["_tokens"]
    for doc in doctors:
        hits = sum(1 for t in doc if any(_person_token(t, h) for h in holder))
        if hits >= 2:
            return True
    return False


def scope_of(activity: str) -> List[str]:
    a = _norm(activity)
    return [label for label, terms in SCOPE_TERMS.items() if any(t in a for t in terms)]


def chairs_of(activity: str) -> Optional[int]:
    m = re.search(r"на\s*(\d+)\s*кресл", _norm(activity))
    return int(m.group(1)) if m else None


def scope_gaps(services: List[str], scopes: List[str]) -> List[str]:
    if "общая практика" in scopes:
        return []
    text = " ".join(services).lower()
    gaps = []
    for stems, need in SERVICE_NEEDS:
        if any(s in text for s in stems) and need not in scopes:
            if need == "хирургия" and "имплантация" in scopes:
                continue
            gaps.append(need)
    return gaps


def check_clinic(names: List[str], address: str, services: Optional[List[str]] = None,
                 doctors: Optional[List[str]] = None) -> Dict:
    return _check(tuple(names), address, tuple(services or ()), tuple(doctors or ()))


@lru_cache(maxsize=4096)
def _check(names: Tuple[str, ...], address: str, services: Tuple[str, ...], doctors: Tuple[str, ...]) -> Dict:
    """Сверка с реестром: статус (см. LICENSE_LABELS), найденные записи, пробелы в профилях, «без лицензии»."""
    reg = load_registry()
    street, house = parse_address(address)
    token_sets = [ts for ts in (name_tokens(n) for n in names if n) if ts]
    tokens = sorted({t for ts in token_sets for t in ts})
    weak_tokens = sorted({t for n in names if n for t in name_tokens(n, fallback=True)}) if not tokens else []
    doctor_tokens = [name_tokens(d) for d in doctors]
    words = street_words(street)
    pool = {id(r): r for key, recs in reg["street_index"].items()
            if any(w == key or (abs(len(w) - len(key)) <= 2 and not re.search(r"\d", w + key) and similar(w, key))
                   for w in words) for r in recs}
    if tokens or doctor_tokens:
        flat = {t for d in doctor_tokens for t in d}
        for rec in reg["dental"]:
            if any(_token_strength(a, b) for a in tokens for b in rec["_tokens"]) or \
                    any(_person_token(a, b) for a in flat for b in rec["_tokens"]):
                pool[id(rec)] = rec
    candidates = []
    for rec in pool.values():
        addr = _address_match(street, house, rec)
        if doctor_tokens and _person_match(doctor_tokens, rec):
            name = 2
        elif is_person(rec):
            # «Dr. Эмиль Дакенов» ≠ «Эшдолотов Эмиль»: для ИП нужно совпадение и фамилии, и имени
            name = 2 if token_sets and _person_match(token_sets, rec) else 0
        elif tokens:
            name = _name_strength(tokens, rec)
        else:
            name = _name_strength(weak_tokens, rec) if addr and weak_tokens else 0
        if not addr and (name < 2 or not (any(_full_name_match(ts, rec) for ts in token_sets) or is_person(rec))):
            continue   # совпало одно слово названия по чужому адресу — слишком слабое совпадение
        if addr or name:
            candidates.append({"record": rec, "address": addr, "name": name})

    addr_points = {"exact": 3, "same_building": 2, "probable": 1}

    def strength(c):
        return addr_points.get(c["address"], 0) + 3 * c["name"]

    candidates.sort(key=strength, reverse=True)
    best = candidates[0] if candidates else None
    at_address = {c["record"]["name"] for c in candidates if c["address"] in ("exact", "same_building")}
    if not best:
        status = "not_found"
    elif best["address"] and best["name"]:
        strong = best["address"] == "exact" or best["name"] == 2
        status = "verified" if strong else "probable"
    elif best["address"]:
        status = "ambiguous" if len(at_address) >= 3 else "address_match"
    else:
        status = "name_other_address"

    matched = [c for c in candidates if strength(c) == strength(best)] if best else []
    if status == "ambiguous":
        matched = matched[:3]
    scopes = sorted({x for c in matched for x in scope_of(c["record"]["activity"])})
    gaps = scope_gaps(list(services), scopes) if status in ("verified", "probable", "address_match") else []
    unlicensed = [{"name": r["name"], "address": r["address"]} for r in reg["unlicensed"]["records"]
                  if r["dental"] and street and house and same_street(street, r.get("_street"))
                  and house == r.get("_house")]   # для такого серьёзного флага — только точный адрес

    def view(c):
        r = c["record"]
        return {"number": r["number"], "holder": r["name"], "address": r["address"], "issued": r["issued"],
                "activity": r["activity"], "scope": scope_of(r["activity"]), "chairs": chairs_of(r["activity"]),
                "match": {"address": c["address"], "name": {0: None, 1: "похоже", 2: "совпадает"}[c["name"]]}}

    meta = reg["licenses"]["meta"]
    return {
        "status": status,
        "matches": [view(c) for c in matched[:3]],
        "other_licensees_at_address": max(0, len(at_address) - 1) if at_address else 0,
        "scope": scopes,
        "scope_gaps": gaps,
        "unlicensed_at_address": unlicensed,
        "registry": {"as_of": meta.get("as_of"), "source_file": meta.get("source_file"),
                     "source_page": meta.get("source_page"),
                     "unlicensed_file": reg["unlicensed"]["meta"].get("source_file")},
    }
