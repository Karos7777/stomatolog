"""Анализ врача: где учился (в т.ч. за рубежом), что подтверждено документами, нет ли нестыковок.

Источник — публичная анкета YDoc. «Документы проверены» на YDoc означает, что площадка
сверила скан документа с ФИО врача, и анкета перечисляет, какие именно документы сверены
(«Диплом о медицинском образовании», «Свидетельство об ординатуре»…). Проверенным считаем
только строку образования, для которой есть такой документ. Это сильнее слов клиники, но слабее
ответа самого вуза, поэтому такой документ получает уровень доказанности 2 из 4.
"""
import re
from datetime import date
from typing import Dict, List, Optional, Tuple

from app.models import CredentialCheckRequest
from app.verification.credentials import CLAIM_TYPES, check_credential

# (код, название, шаблоны). Порядок важен: Кыргызстан проверяем первым — «Кыргызско-Российский» это КРСУ в Бишкеке.
COUNTRIES: List[Tuple[str, str, Tuple[str, ...]]] = [
    ("KG", "Кыргызстан", ("кыргыз", "киргиз", "бишкек", "кгма", "крсу", "ошск", "ошгу", "ош ", "джалал", "жалал",
                          "иссык", "нарын", "талас", "международная высшая школа медицины", "мвшм", "кгмипипк",
                          "даниярова", "ахунбаева", "азиатский медицинский", "салымбеков", "мук ", "манас",
                          "медицинский институт им. с. тентишева", "кгму", "kyrgyz", "bishkek", "krsu")),
    ("RU", "Россия", ("россий", "москов", "москв", "санкт", "петербург", "казан", "новосибир", "омск", "томск",
                      "красноярск", "екатеринбург", "уральск", "самар", "волгоград", "ставропол", "сеченов",
                      "пирогов", "мгмсу", "евдокимов", "рудн", "первый мгму", "башкир", "дагестан", "тверск",
                      "смоленск", "воронеж", "ростов", "кубан", "алтайск", "иркутск", "оренбург", "челябин",
                      "тюмен", "пермск", "нижегород", "приволж", "кировск", "курск", "саратов", "рязан", "ярослав",
                      "ивановск", "северо-западн", "мечников", "павлова", "russia", "moscow")),
    ("KZ", "Казахстан", ("казахстан", "казнму", "асфендиярова", "алмат", "астан", "караганд", "семей", "актобе",
                         "южно-казахстан", "шымкент", "kazakh", "almaty")),
    ("UZ", "Узбекистан", ("узбек", "ташкент", "самарканд", "андижан", "бухар", "uzbek", "tashkent")),
    ("TJ", "Таджикистан", ("таджик", "душанбе", "абуали", "tajik")),
    ("TR", "Турция", ("турц", "турец", "turkey", "türkiye", "hacettepe", "ankara", "istanbul", "стамбул", "анкар",
                      "üniversitesi", "universitesi", "izmir", "измир", "gazi", "marmara")),
    ("KR", "Южная Корея", ("коре", "korea", "seoul", "сеул", "yonsei", "kyung hee", "кёнхи", "osstem academy")),
    ("CN", "Китай", ("китай", "китая", "china", "пекин", "beijing", "shanghai", "шанхай", "wuhan", "ухань", "harbin")),
    ("DE", "Германия", ("герман", "germany", "deutsch", "universität", "berlin", "берлин", "münchen", "мюнхен",
                        "heidelberg", "гейдельберг")),
    ("IT", "Италия", ("итали", "italy", "milan", "милан", "roma", "рим ")),
    ("CH", "Швейцария", ("швейцар", "switzerland", "basel", "базель", "zürich", "цюрих", "bern")),
    ("US", "США", ("сша", "usa", "united states", "harvard", "гарвард", "new york", "нью-йорк", "california")),
    ("IL", "Израиль", ("израил", "israel", "тель-авив", "tel aviv")),
    ("UA", "Украина", ("украин", "киев", "харьков", "одесс", "львов", "днепр", "ukrain", "kyiv")),
    ("BY", "Беларусь", ("беларус", "белорус", "минск", "belarus")),
    ("AM", "Армения", ("армен", "ереван")),
    ("AZ", "Азербайджан", ("азербайдж", "баку")),
    ("IN", "Индия", ("india", "индия", "индии")),
    ("PK", "Пакистан", ("pakistan", "пакистан")),
    ("AE", "ОАЭ", ("оаэ", "uae", "dubai", "дубай")),
]

KIND_TYPES = {
    "базовое образование": "state_diploma",
    "высшее": "state_diploma",
    "ординатура": "postgrad",
    "интернатура": "postgrad",
    "резидентура": "postgrad",
    "аспирантура": "postgrad",
    "докторантура": "postgrad",
    "магистратура": "postgrad",
    "переподготовк": "specialist_cert",
    "сертификат": "specialist_cert",
    "повышение квалификации": "private_course",
    "курсы повышения квалификации": "private_course",
    "курсы": "private_course",
    "стажировка": "private_course",
    "кандидат медицинских наук": "academic_degree",
    "доктор медицинских наук": "academic_degree",
}

# Какой проверенный YDoc документ подтверждает строку образования
CHECKED_DOCS = {
    "базовое образование": "диплом о медицинском образовании",
    "ординатура": "свидетельство об ординатуре",
    "интернатура": "свидетельство об интернатуре",
}


def _confirmed(kind: Optional[str], doc: Dict) -> bool:
    if not (doc.get("documents_verified") or {}).get("education"):
        return False
    k = (kind or "").lower()
    need = next((v for key, v in CHECKED_DOCS.items() if key in k), None)
    return bool(need and any(need in t.lower() for t in doc.get("document_types") or []))


# Какая подготовка подтверждает заявленную специальность
SPECIALTY_SUPPORT = {
    "хирург": ("хирург", "челюстно", "имплант"),
    "имплантолог": ("хирург", "имплант", "челюстно"),
    "ортодонт": ("ортодонт",),
    "ортопед": ("ортопед", "протез"),
    "детский": ("детск",),
    "пародонтолог": ("пародонт", "терапевт"),
    "эндодонтист": ("эндодонт", "терапевт"),
    "гнатолог": ("гнатолог", "ортопед", "ортодонт"),
}


# Как проверить документ страны самому (только официальные сервисы, которые работают по номеру документа)
COUNTRY_CHECK = {
    "RU": "Российский диплом проверяется по госреестру ФРДО: попросите у врача серию и номер, регистрационный номер "
          "и дату выдачи и введите их с фамилией в «Сервис поиска сведений о документах об образовании» на "
          "obrnadzor.gov.ru. Нет в реестре — ещё не подделка: старые дипломы внесены не все, тогда просите копию.",
}


def detect_country(text: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    t = " " + (text or "").lower().replace("ё", "е") + " "
    for code, label, patterns in COUNTRIES:
        if any(p in t for p in patterns):
            return code, label
    return None, None


def _kind_type(kind: Optional[str], title: str) -> Optional[str]:
    k = (kind or "").lower().strip()
    for key, ctype in KIND_TYPES.items():
        if key in k:
            return ctype
    return None


def analyze_doctor(doc: Dict, today: Optional[date] = None) -> Dict:
    """Нормализованная карточка врача с проверками. doc — запись из data/ydoc_doctors.json."""
    today = today or date.today()
    edu = doc.get("education") or []
    ver = doc.get("documents_verified") or {}
    base_years = [e["year"] for e in edu if e.get("year") and _kind_type(e.get("kind"), "") == "state_diploma"]
    grad_year = min(base_years) if base_years else None
    exp = doc.get("experience_years")
    red, warn = [], []

    entries = []
    for e in edu:
        title = " ".join(x for x in (e.get("kind"), e.get("specialty")) if x) or "Образование"
        ctype = _kind_type(e.get("kind"), title)
        confirmed = _confirmed(e.get("kind"), doc)
        level = 2 if confirmed else 1
        v = check_credential(CredentialCheckRequest(
            title=title, claim_type=ctype, issuer=e.get("institution"), year=e.get("year"),
            holder_graduation_year=grad_year, holder_experience_years=None, evidence_level=level), today)
        code, label = detect_country(e.get("institution"))
        entries.append({**e, "title": title, "claim_type": v.claim_type, "claim_type_label": v.claim_type_label,
                        "country": code, "country_label": label, "foreign": bool(code and code != "KG"),
                        "how_to_verify": [COUNTRY_CHECK[code]] if code in COUNTRY_CHECK and not confirmed else [],
                        "confirmed": confirmed, "evidence_level": level, "verdict": v.verdict,
                        "proves": v.proves, "does_not_prove": v.does_not_prove,
                        "red_flags": v.red_flags, "warnings": [w for w in v.warnings if "справочнике" not in w]})
        # Красный флаг — только невозможное (даты, стаж). «Неизвестная академия» у курса — предупреждение.
        target = red if v.verdict == "признаки подделки" else warn
        target += [f"{e.get('institution')}: {f}" for f in v.red_flags]

    if grad_year and exp is not None and exp > today.year - grad_year + 1:
        red.append(f"Заявленный стаж {exp} лет больше, чем прошло с окончания вуза ({grad_year}, это "
                   f"{today.year - grad_year} лет).")
    if grad_year and grad_year > today.year:
        red.append("Год окончания вуза ещё не наступил.")

    training = " ".join(f"{e.get('kind') or ''} {e.get('specialty') or ''}".lower() for e in edu
                        if _kind_type(e.get("kind"), "") != "state_diploma")
    unsupported = []
    if edu:
        for spec in doc.get("specialties") or []:
            s = spec.lower()
            for key, needs in SPECIALTY_SUPPORT.items():
                if key in s and not any(n in training for n in needs):
                    unsupported.append(spec)
    if unsupported:
        warn.append("Заявлены специальности без отдельной подготовки в анкете: " + ", ".join(unsupported)
                    + ". Спросите диплом ординатуры или сертификат по этой специальности.")
    specs = doc.get("specialties") or []
    if exp is not None and exp <= 5 and len(specs) >= 4:
        warn.append(f"{len(specs)} специальностей при стаже {exp} лет — уточните, кто будет делать сложное лечение.")
    if not edu:
        warn.append("Образование в анкете не указано.")
    expired = [t for t in doc.get("document_types") or [] if "недействител" in t.lower()]
    if expired:
        warn.append("YDoc: " + expired[0].replace(". ", " — ") + ". Спросите действующий сертификат.")

    reviews = doc.get("reviews") or []
    rated = [r["rating"] for r in reviews if r.get("rating")]
    foreign = [e for e in entries if e["foreign"]]
    summary_parts = []
    for e in entries:
        flag = " ✓ документ проверен YDoc" if e["confirmed"] else ""
        country = f", {e['country_label']}" if e["foreign"] else ""
        summary_parts.append(f"{e.get('kind') or 'Образование'}: {e.get('institution')}{country}"
                             f"{', ' + str(e['year']) if e.get('year') else ''}"
                             f"{' — ' + e['specialty'] if e.get('specialty') else ''}{flag}")
    level = ("проверены документы" if ver.get("education") else
             "образование указано, документы не проверены" if edu else "нет данных об образовании")
    return {
        "id": re.sub(r"\D", "", doc.get("url", "").rsplit("/vrach/", 1)[-1].split("-")[0]) or doc.get("name"),
        "name": doc.get("name"),
        "url": doc.get("url"),
        "specialties": specs,
        "experience_years": exp,
        "graduation_year": grad_year,
        "documents_verified": bool(ver.get("education")),
        "checked_documents": [t for t in doc.get("document_types") or [] if ver.get("education")],
        "category_verified": bool(ver.get("category")),
        "science_verified": bool(ver.get("science")),
        "education": entries,
        "foreign": bool(foreign),
        "foreign_countries": sorted({e["country_label"] for e in foreign}),
        "foreign_verified": any(e["confirmed"] for e in foreign),
        "red_flags": red,
        "warnings": warn,
        "verification_level": level,
        "summary": summary_parts,
        "reviews": {"count": len(reviews), "verified": sum(1 for r in reviews if r.get("verified")),
                    "mean": round(sum(rated) / len(rated), 2) if rated else None,
                    "negative": sum(1 for r in rated if r <= 3),
                    "last": max((r["date"] for r in reviews if r.get("date")), default=None),
                    "total_on_profile": doc.get("rating_count")},
        "workplaces": doc.get("workplaces") or [],
        "profile_updated": doc.get("profile_updated"),
    }


# ---------------------------------------------------------------------------
# Проверка «вставьте текст»: описание врача с сайта или текст сертификата
# ---------------------------------------------------------------------------

_SPLIT = re.compile(r"[\n;•·]+|(?<=[а-яёa-z]{3}[.!?])\s+(?=[А-ЯЁA-Z])|(?<=\d{4}[.!?])\s+(?=[А-ЯЁA-Z])|(?<=\d{4}\)[.!?])\s+(?=[А-ЯЁA-Z])")
_YEAR = re.compile(r"\b(19[5-9]\d|20[0-4]\d)\b")
_EXP = re.compile(r"стаж[^\d]{0,15}(\d{1,2})|(\d{1,2})\s*(?:лет|года|год)\s+(?:стажа|опыта|практики)", re.I)
_GRAD = re.compile(r"(окончил|окончила|выпуск|диплом|университет|академи|институт|вуз)", re.I)


def check_text(text: str, today: Optional[date] = None) -> Dict:
    """Разбивает свободный текст на утверждения и проверяет каждое."""
    today = today or date.today()
    chunks = [c.strip(" -—–\t.") for c in _SPLIT.split(text or "") if c and len(c.strip()) > 3]
    exp_m = _EXP.search(text or "")
    experience = int(next(g for g in exp_m.groups() if g)) if exp_m else None
    claims = []
    for chunk in chunks:
        if _EXP.search(chunk) and len(chunk) < 30:
            continue   # «Стаж 20 лет» — не документ, учитываем отдельно
        years = [int(y) for y in _YEAR.findall(chunk)]
        claims.append({"text": chunk, "year": years[-1] if years else None})
    grad_year = None
    for c in claims:
        req = CredentialCheckRequest(title=c["text"], year=c["year"])
        v = check_credential(req, today)
        c["type"] = v.claim_type
        if v.claim_type == "state_diploma" and c["year"] and _GRAD.search(c["text"]):
            grad_year = c["year"] if grad_year is None else min(grad_year, c["year"])
    results = []
    for c in claims:
        v = check_credential(CredentialCheckRequest(
            title=c["text"], year=c["year"], holder_graduation_year=grad_year, evidence_level=1), today)
        code, label = detect_country(c["text"])
        res = {"text": c["text"], "year": c["year"], "country": label, "foreign": bool(code and code != "KG"),
               **v.model_dump()}
        if code in COUNTRY_CHECK:
            res["how_to_verify"] = [COUNTRY_CHECK[code]] + res["how_to_verify"]
        results.append(res)
    red = [f for r in results for f in r["red_flags"]]
    if grad_year and experience is not None and experience > today.year - grad_year + 1:
        red.append(f"Стаж {experience} лет больше, чем прошло с выпуска ({grad_year}).")
    strongest = max((CLAIM_TYPES[r["claim_type"]]["weight"] for r in results), default=0)
    if red:
        verdict = "Есть противоречия — так в настоящих документах не бывает"
    elif strongest >= 0.6:
        verdict = "Похоже на настоящее образование, но это слова — попросите показать документы"
    elif results:
        verdict = "Только курсы/награды/членства — специализацию это не доказывает"
    else:
        verdict = "Не нашёл в тексте утверждений об образовании"
    return {"graduation_year": grad_year, "experience": experience, "claims": results,
            "red_flags": red, "verdict": verdict}
