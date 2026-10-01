from datetime import date

import pytest

from app.database import link_workplace
from app.models import Clinic
from app.verification.doctors import analyze_doctor, check_text, detect_country
from tools.crawl_ydoc import parse_profile

TODAY = date(2026, 10, 1)


def ydoc_record(**kw):
    rec = {
        "url": "https://ydoc.kg/bishkek/vrach/1-test/", "name": "Тестов Тест Тестович",
        "specialties": ["Стоматолог", "Стоматолог-хирург", "Стоматолог-имплантолог", "Стоматолог-ортопед", "Детский стоматолог"],
        "experience_years": 4,
        "documents_verified": {"education": True, "category": False, "science": False},
        "document_types": ["Диплом о медицинском образовании"],
        "education": [
            {"institution": "Кыргызско-Российский Славянский университет", "year": 2022, "specialty": "Стоматология",
             "kind": "Базовое образование"},
            {"institution": "Кыргызско-Российский Славянский университет", "year": 2024,
             "specialty": "Стоматология общей практики", "kind": "Ординатура"}],
        "workplaces": [], "reviews": [{"id": "1", "date": "2026-09-18", "rating": 5, "verified": True}],
    }
    rec.update(kw)
    return rec


@pytest.mark.parametrize("text,code", [
    ("Кыргызско-Российский Славянский университет", "KG"), ("КГМА им. И.К. Ахунбаева", "KG"),
    ("Первый МГМУ им. И.М. Сеченова", "RU"), ("КазНМУ им. Асфендиярова", "KZ"),
    ("Hacettepe Üniversitesi", "TR"), ("Yonsei University, Seoul", "KR"), ("Неизвестный институт", None),
])
def test_detect_country(text, code):
    assert detect_country(text)[0] == code


def test_verified_doctor_with_unsupported_specialties():
    a = analyze_doctor(ydoc_record(), TODAY)
    assert a["documents_verified"] and a["graduation_year"] == 2022 and not a["foreign"]
    assert a["education"][0]["confirmed"] and a["education"][0]["evidence_level"] == 2
    assert not a["education"][1]["confirmed"]   # свидетельства об ординатуре среди проверенных нет
    assert not a["red_flags"]
    assert any("без отдельной подготовки" in w for w in a["warnings"])
    assert any("специальностей при стаже" in w for w in a["warnings"])
    assert a["reviews"]["count"] == 1 and a["reviews"]["mean"] == 5


def test_experience_longer_than_career_is_red_flag():
    a = analyze_doctor(ydoc_record(experience_years=15), TODAY)
    assert any("Заявленный стаж 15 лет" in f for f in a["red_flags"])


def test_foreign_education_detected():
    edu = [{"institution": "Первый МГМУ им. И.М. Сеченова", "year": 2005, "specialty": "Стоматология",
            "kind": "Базовое образование"}]
    a = analyze_doctor(ydoc_record(education=edu, experience_years=20, specialties=["Стоматолог"]), TODAY)
    assert a["foreign"] and a["foreign_countries"] == ["Россия"] and a["foreign_verified"]
    # без отметки «Документы проверены» зарубежный диплом — только слова анкеты
    a = analyze_doctor(ydoc_record(education=edu, experience_years=20, specialties=["Стоматолог"],
                                   documents_verified={"education": False}, document_types=[]), TODAY)
    assert a["foreign"] and not a["foreign_verified"] and not a["education"][0]["confirmed"]
    assert "obrnadzor.gov.ru" in a["education"][0]["how_to_verify"][0]


def test_expired_certificate_is_a_warning():
    a = analyze_doctor(ydoc_record(document_types=["Диплом о медицинском образовании",
                                                   "Сертификат специалиста. Документ уже недействителен"]), TODAY)
    assert any("недействителен" in w for w in a["warnings"]) and not a["red_flags"]


def test_free_text_check():
    r = check_text("Окончил КГМА им. И.К. Ахунбаева в 2010 году. Клиническая ординатура по ортопедии (2010–2012). "
                   "Стаж 20 лет. Сертификат Master of Implantology, International Academy, 2019. "
                   "Стажировка в Сеуле (Osstem, 2018)", TODAY)
    types = [c["claim_type"] for c in r["claims"]]
    assert types[:2] == ["state_diploma", "postgrad"] and len(r["claims"]) == 4
    assert r["graduation_year"] == 2010 and r["experience"] == 20
    assert any("Стаж 20 лет больше" in f for f in r["red_flags"])
    assert any(c["foreign"] for c in r["claims"])
    assert not any("obrnadzor" in h for c in r["claims"] for h in c["how_to_verify"])   # Корея: такого сервиса нет
    assert "противоречия" in r["verdict"]


def test_parse_profile_from_markup():
    page = (
        '<title>Иванов Иван Иванович, стоматолог - отзывы | Бишкек - YDoc</title>'
        '<h1><span class="d-block text-h5 text--text mb-2" itemprop=name> Иванов Иван Иванович <span></span></span></h1>'
        '<div class="b-doctor-intro__specs mb-4"><a class=b-doctor-intro__spec href="/x/"> стоматолог-хирург </a></div>'
        '<div data-documents-verified-open="{ isEducationConfirmed: true, isCategoryConfirmed: false, categoryExpiresDate: \'\', '
        'isScienceConfirmed: false, }"><div>Стаж 12 лет</div></div> Обновлено 01.09.2026 '
        ":lpu-address-list='[{\"lpu_id\": 5, \"lpu\": {\"name\": \"Стоматология «Тест»\"}, \"address\": \"ул. Тестовая, 1\", "
        "\"lat\": 42.87, \"lon\": 74.6, \"workplaces\": []}]' "
        '<div id=educations><div class="b-doctor-details__data-title text-body-1">КГМА</div></div>'
        '<div class="b-doctor-details__item-description pl-7"><div class="text-body-1 text-info--text mb-1">2014</div>'
        '<div class="text-body-1 text--text mb-1">Стоматология <img src=/diplom-blue.png></div>'
        '<div class="text-body-2 text-info--text">Базовое образование</div></div></div><div id=rating>'
        '<div class="b-review-card year2026 b-review-card_positive" data-review-id=7 data-review-type=doctor>'
        '<div content=2026-08-01 itemprop=datePublished></div><meta content=80 itemprop=ratingValue>'
        '<span> Отзыв проверен </span></div><div id=documents></div>')
    d = parse_profile(page, "/bishkek/vrach/9-ivanov/")
    assert d["name"] == "Иванов Иван Иванович" and d["experience_years"] == 12
    assert d["specialties"] == ["Стоматолог-хирург"] and d["documents_verified"]["education"]
    assert d["education"] == [{"institution": "КГМА", "year": 2014, "specialty": "Стоматология",
                               "kind": "Базовое образование"}]
    assert d["workplaces"][0]["name"] == "Стоматология «Тест»" and d["workplaces"][0]["lng"] == 74.6
    assert d["reviews"] == [{"id": "7", "date": "2026-08-01", "rating": 4, "verified": True, "verification": [],
                             "origin": None, "negative": False}]


def test_link_workplace_by_distance_and_name():
    near = Clinic(id="a", name="Эстет", address="3-й мкр, 14/2", coordinates={"lat": 42.83776, "lng": 74.61786})
    other = Clinic(id="b", name="Другая", address="3-й мкр, 14/2", coordinates={"lat": 42.83770, "lng": 74.61780})
    far = Clinic(id="c", name="Эстет", address="далеко", coordinates={"lat": 42.90, "lng": 74.70})
    clinic, how = link_workplace({"name": "Стоматология «Эстет»", "lat": 42.837756, "lng": 74.617858}, [near, other, far])
    assert clinic.id == "a" and how == "название и адрес"
    clinic, _ = link_workplace({"name": "Стоматология «Нет»", "lat": 42.0, "lng": 74.0}, [near, far])
    assert clinic is None
