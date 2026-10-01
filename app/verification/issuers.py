"""Справочник эмитентов документов о квалификации и способов их проверки.

Здесь только организации, в существовании которых мы уверены, и только ссылки,
найденные в открытых источниках. Отсутствие эмитента в справочнике не значит, что
документ поддельный, — значит, что его нужно проверять вручную.
"""
import re
from typing import Dict, List, Optional

# kind:
#   university   — вуз (диплом, ординатура)
#   state        — государственный орган (лицензии, сертификаты специалиста, категории)
#   state_cpd    — госучреждение повышения квалификации
#   degree_body  — орган, присуждающий учёные степени
#   vendor       — производитель (импланты, брекеты, оборудование, материалы)
#   society      — профессиональное общество/ассоциация
ISSUERS: List[Dict] = [
    {"name": "КГМА им. И.К. Ахунбаева", "kind": "university", "country": "KG",
     "patterns": ["кгма", "ахунбаев", "kgma", "kyrgyz state medical academy"],
     "url": "https://www.kgma.kg/ru",
     "verify": "Письменный запрос в КГМА (ФИО, год выпуска, номер диплома). Врач вправе показать оригинал диплома с вкладышем."},
    {"name": "КРСУ им. Б.Н. Ельцина", "kind": "university", "country": "KG",
     "patterns": ["крсу", "кыргызско-российский славянский", "славянский университет", "krsu", "ельцин"],
     "url": "https://old.krsu.edu.kg",
     "verify": "Запрос в КРСУ (медицинский факультет) по ФИО и году выпуска."},
    {"name": "Ошский государственный университет", "kind": "university", "country": "KG",
     "patterns": ["ошгу", "ошский государственный", "osh state"],
     "url": None, "verify": "Запрос в ОшГУ по ФИО и году выпуска."},
    {"name": "КГМИПиПК им. С.Б. Даниярова", "kind": "state_cpd", "country": "KG",
     "patterns": ["кгмипипк", "даниярова", "переподготовки и повышения квалификации", "kgmipk"],
     "url": None,
     "verify": "Государственный институт переподготовки врачей: запрос о выданном сертификате/удостоверении по ФИО и номеру."},
    {"name": "Министерство здравоохранения КР", "kind": "state", "country": "KG",
     "patterns": ["министерство здравоохранения", "минздрав", "мз кр", "мз-кр", "ministry of health"],
     "url": "https://license.med.kg/ru/",
     "verify": "Лицензии клиник — в реестре МЗ КР и через Түндүк по ИНН; сертификаты об аттестации — в системе разрешительных документов."},
    {"name": "Национальная аттестационная комиссия при Президенте КР", "kind": "degree_body", "country": "KG",
     "patterns": ["национальная аттестационная", "нак кр", "вак кр", "vak kg"],
     "url": "https://vak.kg/rekvizity/",
     "verify": "Учёные степени КР присуждает НАК; запросите номер диплома кандидата/доктора наук и тему диссертации."},
    # --- производители: курсы по своим системам, а не специализация ---
    {"name": "Straumann", "kind": "vendor", "patterns": ["straumann", "штрауман"], "url": "https://www.straumann.com",
     "verify": "Курс производителя имплантов. Подтверждение — только запрос в представительство Straumann."},
    {"name": "Nobel Biocare", "kind": "vendor", "patterns": ["nobel biocare", "нобель", "nobel"], "url": "https://www.nobelbiocare.com",
     "verify": "Курс производителя имплантов. Подтверждение — запрос дистрибьютору."},
    {"name": "Osstem", "kind": "vendor", "patterns": ["osstem", "осстем", "aic osstem"], "url": "https://www.osstem.com",
     "verify": "Курс производителя имплантов (AIC — учебный центр Osstem). Подтверждение — запрос дистрибьютору."},
    {"name": "Dentium", "kind": "vendor", "patterns": ["dentium", "дентиум"], "url": None,
     "verify": "Курс производителя имплантов."},
    {"name": "MegaGen", "kind": "vendor", "patterns": ["megagen", "мегаген"], "url": None, "verify": "Курс производителя имплантов."},
    {"name": "Neodent", "kind": "vendor", "patterns": ["neodent", "неодент"], "url": None, "verify": "Курс производителя имплантов."},
    {"name": "Alpha-Bio", "kind": "vendor", "patterns": ["alpha-bio", "альфа-био", "alpha bio"], "url": None, "verify": "Курс производителя имплантов."},
    {"name": "Ormco (Damon)", "kind": "vendor", "patterns": ["ormco", "ормко", "damon", "деймон"], "url": "https://ormco.com",
     "verify": "Курс производителя брекет-систем."},
    {"name": "Align Technology (Invisalign)", "kind": "vendor", "patterns": ["invisalign", "инвизилайн", "align technology"],
     "url": "https://www.invisalign.com/find-a-doctor", "locator": True,
     "verify": "Действующих провайдеров Invisalign можно найти в официальном поиске врачей Invisalign."},
    {"name": "Ivoclar", "kind": "vendor", "patterns": ["ivoclar", "ивоклар"], "url": "https://www.ivoclar.com",
     "verify": "Курс производителя материалов (керамика, композиты)."},
    {"name": "Dentsply Sirona", "kind": "vendor", "patterns": ["dentsply", "sirona", "денстплай", "дентсплай", "cerec"],
     "url": "https://www.dentsplysirona.com", "verify": "Курс производителя оборудования/материалов."},
    {"name": "3M", "kind": "vendor", "patterns": ["3m espe", "3m oral", " 3m "], "url": None, "verify": "Курс производителя материалов."},
    {"name": "Karl Kaps", "kind": "vendor", "patterns": ["karl kaps", "карл капс", "kaps"], "url": None,
     "verify": "Курс производителя микроскопов."},
    {"name": "Carl Zeiss", "kind": "vendor", "patterns": ["zeiss", "цейс"], "url": None, "verify": "Курс производителя микроскопов."},
    {"name": "EMS (GBT, Swiss Dental Academy)", "kind": "vendor", "patterns": [" ems ", "electro medical systems", "swiss dental academy", "gbt", "air flow", "airflow"],
     "url": None, "verify": "Курс производителя оборудования для гигиены."},
    {"name": "Geistlich (Bio-Oss)", "kind": "vendor", "patterns": ["geistlich", "гайстлих", "bio-oss"], "url": None,
     "verify": "Курс производителя костных материалов."},
    {"name": "Vatech / Planmeca / Medit", "kind": "vendor", "patterns": ["vatech", "planmeca", "medit"], "url": None,
     "verify": "Курс производителя оборудования."},
    # --- профессиональные общества ---
    {"name": "ITI (International Team for Implantology)", "kind": "society", "patterns": [" iti ", "international team for implantology"],
     "url": "https://www.iti.org", "verify": "Членство или статус Fellow ITI. Fellow — по отбору; обычное членство — по взносу."},
    {"name": "EAO (European Association for Osseointegration)", "kind": "society", "patterns": ["eao", "european association for osseointegration"],
     "url": "https://eao.org", "verify": "Членство в обществе обычно оформляется по взносу."},
    {"name": "FDI World Dental Federation", "kind": "society", "patterns": ["fdi world dental", " fdi "], "url": None,
     "verify": "Членами FDI являются национальные ассоциации, а не отдельные врачи."},
    {"name": "Стоматологическая ассоциация России (СтАР)", "kind": "society", "patterns": [" стар ", "стоматологическая ассоциация россии"],
     "url": None, "verify": "Членство по взносу."},
    {"name": "Style Italiano", "kind": "private_school", "patterns": ["style italiano"], "url": None,
     "verify": "Частная образовательная группа по эстетической реставрации."},
]

VERIFY_LINKS = {
    "clinic_license": [
        {"title": "Реестр лицензий Министерства здравоохранения КР", "url": "https://license.med.kg/ru/"},
        {"title": "Түндүк: сведения о лицензиях на медицинскую деятельность (по ИНН)", "url": "https://portal.tunduk.kg/public_services/opisanie/6323917"},
        {"title": "Разрешительные документы КР (elicense.gov.kg)", "url": "https://elicense.gov.kg/"},
    ],
    "legal_entity": [
        {"title": "Поиск юрлица по ИНН (osoo.kg)", "url": "https://www.osoo.kg/"},
    ],
    "specialist_cert": [
        {"title": "Сертификат об аттестации медицинских работников — elicense.gov.kg", "url": "https://elicense.gov.kg/license/id/2295"},
    ],
    "academic_degree": [
        {"title": "Национальная аттестационная комиссия при Президенте КР", "url": "https://vak.kg/rekvizity/"},
    ],
    "vendor_provider_status": [
        {"title": "Поиск врачей Invisalign", "url": "https://www.invisalign.com/find-a-doctor"},
    ],
}


def find_issuer(*texts: Optional[str]) -> Optional[Dict]:
    hay = " " + re.sub(r"[^\w\-]+", " ", " ".join(t.lower() for t in texts if t)) + " "
    for issuer in ISSUERS:
        if any(p in hay for p in issuer["patterns"]):
            return issuer
    return None
