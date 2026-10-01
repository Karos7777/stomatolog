"""Проверка заявлений о квалификации врача.

Отвечает на три вопроса:
1. Что это за документ и что он на самом деле доказывает (курс на 2 дня ≠ специализация).
2. Где и как его можно сверить с эмитентом.
3. Есть ли внутренние противоречия (даты, стаж, «звания» от коммерческих курсов).
"""
import re
from datetime import date
from typing import Dict, List, Optional, Tuple

from app.models import EVIDENCE_LEVELS, CredentialCheckRequest, CredentialVerdict
from app.verification.issuers import VERIFY_LINKS, find_issuer

CLAIM_TYPES: Dict[str, Dict] = {
    "clinic_license": {
        "label": "Лицензия МЗ КР на медицинскую деятельность",
        "proves": "Клиника имеет право оказывать перечисленные в лицензии виды медицинской помощи.",
        "does_not_prove": "Квалификацию конкретного врача. Лицензия может покрывать не все кабинеты и не все услуги (например, наркоз).",
        "weight": 1.0,
    },
    "state_diploma": {
        "label": "Диплом о высшем медицинском (стоматологическом) образовании",
        "proves": "Врач окончил стоматологический факультет и имеет базовую квалификацию.",
        "does_not_prove": "Узкую специализацию (имплантолог, ортодонт, хирург) и актуальность навыков.",
        "weight": 0.6,
    },
    "postgrad": {
        "label": "Ординатура / интернатура",
        "proves": "1–3 года подготовки по конкретной специальности под контролем вуза — это и есть настоящая специализация.",
        "does_not_prove": "Качество работы сегодня; нужно смотреть стаж и отзывы по этой специальности.",
        "weight": 0.8,
    },
    "specialist_cert": {
        "label": "Сертификат специалиста / аттестация",
        "proves": "Государственный допуск к работе по специальности.",
        "does_not_prove": "Опыт в сложных случаях; сертификат нужно периодически подтверждать.",
        "weight": 0.7,
    },
    "category": {
        "label": "Квалификационная категория",
        "proves": "Врач прошёл аттестацию по стажу и знаниям (вторая → первая → высшая).",
        "does_not_prove": "Навыки в конкретной процедуре; категория во многом отражает стаж.",
        "weight": 0.4,
    },
    "academic_degree": {
        "label": "Учёная степень (к.м.н., д.м.н., PhD)",
        "proves": "Врач защитил научную работу; в КР степени присуждает Национальная аттестационная комиссия.",
        "does_not_prove": "Практический навык: учёный и лучший практик — не всегда один человек.",
        "weight": 0.6,
    },
    "vendor_provider_status": {
        "label": "Статус провайдера производителя",
        "proves": "Врач зарегистрирован у производителя и (для Invisalign) ведёт пациентов этой системой.",
        "does_not_prove": "Специализацию ортодонта: провайдером может быть и терапевт.",
        "weight": 0.25,
    },
    "vendor_course": {
        "label": "Курс производителя (импланты, брекеты, оборудование, материалы)",
        "proves": "Врач посетил обучение по работе с конкретной системой — обычно 1–5 дней. Производители часто требуют такой курс перед продажей своей системы.",
        "does_not_prove": "Специализацию, опыт операций и качество работы. Это не диплом, не лицензия и не учёная степень.",
        "weight": 0.15,
    },
    "private_course": {
        "label": "Частный/авторский курс, мастер-класс, «академия»",
        "proves": "Врач оплатил и посетил обучение у частного лектора или школы.",
        "does_not_prove": "Специализацию. Качество таких курсов сильно различается, государственной аккредитации обычно нет.",
        "weight": 0.1,
    },
    "conference": {
        "label": "Участие в конгрессе/конференции/вебинаре",
        "proves": "Врач присутствовал на мероприятии.",
        "does_not_prove": "Ни навыков, ни квалификации: сертификат участника выдают всем слушателям.",
        "weight": 0.05,
    },
    "membership": {
        "label": "Членство в профессиональном обществе",
        "proves": "Врач состоит в обществе (часто — по членскому взносу).",
        "does_not_prove": "Квалификацию, если членство не требует отбора (исключение — например, Fellow ITI).",
        "weight": 0.1,
    },
    "declared_specialty": {
        "label": "Заявленная специализация (без документа)",
        "proves": "Так врача представляет клиника, агрегатор или СМИ.",
        "does_not_prove": "Ничего, пока не показан документ: диплом ординатуры или сертификат специалиста по этой специальности.",
        "weight": 0.1,
    },
    "award": {
        "label": "Награда, «лучший врач», рейтинг, номинация",
        "proves": "Ничего проверяемого о квалификации.",
        "does_not_prove": "Квалификацию: многие «премии» и «топ-рейтинги» продаются за участие.",
        "weight": 0.0,
    },
    "unknown": {
        "label": "Тип документа не распознан",
        "proves": "Неизвестно.",
        "does_not_prove": "Пока эмитент и тип документа не установлены — ничего.",
        "weight": 0.05,
    },
}

EVIDENCE_MULT = {0: 0.0, 1: 0.3, 2: 0.6, 3: 0.9, 4: 1.0}

# Порядок важен: первое совпадение определяет тип.
_TYPE_RULES: List[Tuple[str, Tuple[str, ...]]] = [
    ("clinic_license", ("лиценз", "license", "licence")),
    ("award", ("лучший", "лучшая", "премия", "award", "номинант", "номинац", "топ-", "top-", "золот", "рейтинг врачей", "врач года")),
    ("academic_degree", ("кандидат медицинских наук", "к.м.н", "кмн", "доктор медицинских наук", "д.м.н", "дмн", "phd", "ph.d")),
    ("postgrad", ("ординатур", "интернатур", "residency", "резидентур")),
    ("specialist_cert", ("сертификат специалиста", "аттестац", "допуск к", "specialist certificate")),
    ("category", ("категори",)),
    ("vendor_provider_status", ("provider", "провайдер")),
    ("conference", ("конгресс", "конференц", "форум", "симпозиум", "вебинар", "congress", "summit", "symposium", "webinar", "участник")),
    ("membership", ("член ", "членств", "member", "fellow")),
    ("state_diploma", ("диплом", "diploma", "стоматологический факультет", "выпускник")),
]

_COURSE_WORDS = ("курс", "мастер-класс", "мастер класс", "школа", "академи", "academy", "course", "training",
                 "тренинг", "семинар", "hands-on", "workshop", "обучени", "стажировк", "program", "программа")

_TITLE_INFLATION = re.compile(
    r"\b(master|магистр|professor|профессор|академик|academician|doctor of|доктор наук|phd|ph\.d|diplomate|"
    r"specialist in|эксперт международного|international expert)\b", re.IGNORECASE)

_GRAND_NAME = re.compile(
    r"(international|междунар|world|global|european|европейск|american|американск|academy|академи|"
    r"institute|институт|university|университет|council|board|federation|федерац)", re.IGNORECASE)

_SURGICAL = ("хирург", "имплант", "чл", "челюстно", "surgeon", "implant", "пародонт")
_IMPLANT_COURSE = ("имплант", "implant", "синус", "sinus", "костн", "bone", "all-on", "графт", "graft")


def classify(title: str, issuer: Optional[str]) -> Tuple[str, Optional[Dict]]:
    hay = f"{title} {issuer or ''}".lower()
    known = find_issuer(title, issuer)
    for ctype, words in _TYPE_RULES:
        if any(w in hay for w in words):
            # «Сертификат об окончании курса Straumann» — не диплом и не допуск
            if ctype in ("state_diploma", "specialist_cert", "category") and known and known["kind"] in ("vendor", "private_school"):
                return "vendor_course" if known["kind"] == "vendor" else "private_course", known
            return ctype, known
    if known:
        kind = known["kind"]
        if kind == "vendor":
            return "vendor_course", known
        if kind == "private_school":
            return "private_course", known
        if kind == "society":
            return "membership", known
        if kind == "university":
            return "state_diploma", known
        if kind in ("state", "state_cpd"):
            return "specialist_cert", known
        if kind == "degree_body":
            return "academic_degree", known
    if any(w in hay for w in _COURSE_WORDS):
        return "private_course", None
    return "unknown", None


def check_credential(req: CredentialCheckRequest, today: Optional[date] = None) -> CredentialVerdict:
    today = today or date.today()
    ctype, issuer = classify(req.title, req.issuer)
    if req.claim_type in CLAIM_TYPES:
        ctype = req.claim_type
    meta = CLAIM_TYPES[ctype]
    hard: List[str] = []   # противоречия, которые не могут быть у настоящего документа
    soft: List[str] = []   # признаки введения в заблуждение
    warnings: List[str] = []

    if req.year and req.year > today.year:
        hard.append(f"Год выдачи {req.year} ещё не наступил.")

    if req.holder_graduation_year:
        if req.holder_graduation_year > today.year:
            hard.append("Год окончания вуза в будущем.")
        if req.year:
            if ctype in ("postgrad", "specialist_cert", "category", "academic_degree") and req.year < req.holder_graduation_year:
                hard.append(f"Документ ({req.year}) датирован раньше окончания вуза ({req.holder_graduation_year}) — "
                            "такая последовательность невозможна.")
            elif ctype == "state_diploma" and req.year != req.holder_graduation_year:
                warnings.append(f"Год диплома ({req.year}) не совпадает с годом окончания вуза "
                                f"({req.holder_graduation_year}) — уточните, о каком документе речь.")
            elif ctype in ("vendor_course", "private_course") and req.year < req.holder_graduation_year - 1:
                warnings.append("Курс пройден задолго до окончания вуза — студентом. Как опыт врача его не засчитывают.")
        if req.holder_experience_years is not None:
            max_exp = today.year - req.holder_graduation_year + 1
            if req.holder_experience_years > max_exp:
                hard.append(f"Заявленный стаж {req.holder_experience_years} лет больше, чем прошло с окончания вуза "
                            f"({max_exp - 1}). Стаж «накручен».")

    if _TITLE_INFLATION.search(req.title) and ctype in ("vendor_course", "private_course", "conference",
                                                          "membership", "award", "unknown"):
        soft.append("Звание вида «Master/Профессор/Эксперт» выдано курсом или организацией, а не вузом и не "
                    "аттестационной комиссией. Это маркетинговое название, а не учёная степень и не специализация.")

    if not issuer and req.issuer and _GRAND_NAME.search(req.issuer):
        msg = ("Громкое название эмитента («международная академия/институт»), которого нет в нашем справочнике. "
               "Проверьте, что организация существует: сайт, юридический адрес, аккредитация, список выпускников.")
        (soft if req.evidence_level <= 1 else warnings).append(msg)
    elif not issuer and ctype not in ("award", "declared_specialty"):
        warnings.append("Эмитент не найден в справочнике — проверять придётся вручную.")

    if req.document_id and not (issuer and (issuer.get("locator") or issuer["kind"] in ("state", "degree_body"))):
        warnings.append("Номер документа нельзя проверить в открытом реестре — сам по себе он ничего не доказывает. "
                        "Важно не наличие номера, а подтверждение от эмитента.")

    if ctype == "specialist_cert" and req.year and today.year - req.year > 5:
        warnings.append("Документу больше 5 лет. Сертификаты специалистов обычно подтверждаются периодически — "
                        "спросите, когда было последнее подтверждение.")

    if (req.holder_specialty and ctype in ("vendor_course", "private_course")
            and any(k in req.title.lower() for k in _IMPLANT_COURSE)
            and not any(k in req.holder_specialty.lower() for k in _SURGICAL)):
        warnings.append("Курс по имплантации у врача без хирургической специализации. Уточните, есть ли ординатура "
                        "по хирургической стоматологии или ЧЛХ.")

    if ctype == "award":
        warnings.append("Награды и «рейтинги лучших» мы не учитываем: их нельзя проверить, многие продаются.")

    how: List[str] = []
    if issuer:
        how.append(f"{issuer['name']}: {issuer['verify']}")
    if ctype == "clinic_license":
        how.append("Найдите ИНН клиники (на договоре, чеке или в реестре юрлиц) и проверьте лицензию через Түндүк или реестр МЗ КР. "
                   "Сверьте адрес и перечень видов помощи: наркоз и седация требуют отдельного вида деятельности.")
    elif ctype in ("state_diploma", "postgrad"):
        how.append("Попросите показать оригинал документа: ФИО, вуз, год, специальность. Сфотографируйте номер и при сомнениях "
                   "отправьте запрос в вуз.")
    elif ctype == "specialist_cert":
        how.append("Спросите номер и дату сертификата/аттестации и кем он выдан. Сверьте специальность с тем, что врач будет делать.")
    elif ctype in ("vendor_course", "private_course", "conference"):
        how.append("Спросите не про сертификат, а про практику: сколько таких процедур врач сделал за последний год и можно ли "
                   "посмотреть снимки до/после (без персональных данных).")
    elif ctype == "academic_degree":
        how.append("Спросите тему диссертации и год защиты; диссертация и автореферат должны находиться в открытом доступе.")
    elif ctype == "vendor_provider_status":
        how.append("Найдите врача в официальном поиске провайдеров производителя.")
    elif ctype == "declared_specialty":
        how.append("Попросите показать диплом об ординатуре или сертификат специалиста именно по этой специальности.")

    links = list(VERIFY_LINKS.get(ctype, []))
    if issuer and issuer.get("url") and not any(l["url"] == issuer["url"] for l in links):
        links.append({"title": issuer["name"], "url": issuer["url"]})

    level = req.evidence_level
    if hard:
        verdict = "признаки подделки"
    elif ctype == "award":
        verdict = "не является квалификацией"
    elif soft:
        verdict = "сомнительно"
    elif level >= 3:
        verdict = "подтверждено"
    else:
        verdict = "правдоподобно, но не проверено"

    weight = meta["weight"] * EVIDENCE_MULT[level]
    if hard:
        weight = 0.0
    elif soft:
        weight *= 0.3

    return CredentialVerdict(
        claim_type=ctype, claim_type_label=meta["label"], issuer_known=bool(issuer),
        issuer_name=issuer["name"] if issuer else req.issuer, proves=meta["proves"],
        does_not_prove=meta["does_not_prove"], how_to_verify=how, verify_links=links,
        red_flags=hard + soft, warnings=warnings, evidence_level=level,
        evidence_label=EVIDENCE_LEVELS[level], verdict=verdict, weight=round(weight, 3),
    )
