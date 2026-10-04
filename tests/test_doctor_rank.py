from app.doctor_rank import NEEDS, rank_doctors, score_doctor
from app.models import Clinic, LicenseInfo


def clinic(cid="c1", services=("Лечение под микроскопом",), license_status="verified", unlicensed=False, rating=4.9, volume=200):
    c = Clinic(id=cid, name="Клиника " + cid, address="ул. Тестовая, 1", services=list(services),
               license=LicenseInfo(status=license_status,
                                   unlicensed_at_address=[{"name": "x", "address": "y"}] if unlicensed else []))
    return {"clinic": c, "score": {"rating": rating, "volume": volume, "trust_index": 70}}


def doctor(name="Тестов Тест", specialties=("Стоматолог",), exp=10, education=(), verified=False, clinics=("c1",),
           reviews=None, red_flags=(), foreign=False):
    return {
        "id": name, "name": name, "url": "https://ydoc.kg/x", "specialties": list(specialties), "experience_years": exp,
        "documents_verified": verified, "foreign": foreign, "foreign_countries": [], "foreign_verified": False,
        "education": list(education), "red_flags": list(red_flags), "warnings": [],
        "reviews": reviews or {"count": 0, "verified": 0, "mean": None, "negative": 0},
        "clinics": [{"clinic_id": c, "clinic_name": "Клиника " + c, "clinic_address": ""} for c in clinics],
        "profile_updated": None,
    }


def edu(kind, specialty, institution="КГМА", year=2015, confirmed=False):
    return {"kind": kind, "specialty": specialty, "institution": institution, "year": year, "confirmed": confirmed}


ROWS = {"c1": clinic("c1"), "c2": clinic("c2", services=(), license_status="not_found")}


def test_endodontist_with_training_and_verified_papers_beats_general_dentist():
    endo = doctor("Эндо Эндо", ("Стоматолог", "Стоматолог-эндодонтист"), 12,
                  [edu("Базовое образование", "Стоматология", confirmed=True),
                   edu("Циклы переподготовки", "Эндодонтия", "Центр", 2019, confirmed=True)],
                  verified=True, reviews={"count": 8, "verified": 8, "mean": 5.0, "negative": 0})
    general = doctor("Общий Врач", ("Стоматолог",), 25, [edu("Базовое образование", "Стоматология")])
    ranked = rank_doctors([general, endo], "endo", ROWS)
    assert [r["name"] for r in ranked] == ["Эндо Эндо", "Общий Врач"]
    assert ranked[0]["profile_match"] and ranked[0]["confidence"] == "высокая"
    assert not ranked[1]["profile_match"] and ranked[1]["fit"] == "general" and ranked[1]["confidence"] == "низкая"


def test_experience_alone_does_not_outrank_a_specialty():
    veteran = doctor("Ветеран", ("Стоматолог",), 40)
    young = doctor("Молодой", ("Стоматолог", "Стоматолог-эндодонтист"), 3)
    assert [r["name"] for r in rank_doctors([veteran, young], "endo", ROWS)] == ["Молодой", "Ветеран"]


def test_wrong_specialty_is_left_out():
    kids = doctor("Детский", ("Детский стоматолог",))
    ortho = doctor("Ортодонт", ("Стоматолог-ортодонт",))
    assert score_doctor(kids, "endo", ROWS) is None          # детский — не для лечения каналов у взрослых
    assert score_doctor(ortho, "endo", ROWS) is None         # без общего «Стоматолог» — не наш профиль
    assert score_doctor(kids, "kids", ROWS)["profile_match"]
    assert score_doctor(ortho, "ortho", ROWS)["profile_match"]
    assert score_doctor(doctor("Общий"), "implant", ROWS) is None   # имплантацию «просто стоматологу» не предлагаем


def test_claims_are_labelled_by_where_they_come_from():
    d = doctor("Врач", ("Стоматолог-эндодонтист",), 5,
               [edu("Ординатура", "Стоматология общей практики", confirmed=True)], verified=True)
    reasons = {r["text"]: r["basis"] for r in score_doctor(d, "endo", ROWS)["reasons"]}
    assert reasons["В анкете указано: стоматолог-эндодонтист"] == "заявлено"
    assert reasons["YDoc сверил документ об обучении по этой теме"] == "подтверждено"
    assert any(r.startswith("Клиника указывает в услугах: микроскоп") for r in reasons)
    d2 = doctor("Без учёбы", ("Стоматолог-эндодонтист",))
    assert any(r["basis"] == "нет данных" and "нет обучения по этой теме" in r["text"] for r in score_doctor(d2, "endo", ROWS)["reasons"])


def test_red_flag_and_unlicensed_address_cost_points():
    clean = score_doctor(doctor(specialties=("Стоматолог-эндодонтист",)), "endo", ROWS)["score"]
    flagged = score_doctor(doctor(specialties=("Стоматолог-эндодонтист",), red_flags=("Стаж больше карьеры",)), "endo", ROWS)
    assert flagged["score"] < clean - 15 and any(r["sign"] == "-" for r in flagged["reasons"])
    bad_rows = {"c1": clinic("c1", unlicensed=True, license_status="not_found")}
    worse = score_doctor(doctor(specialties=("Стоматолог-эндодонтист",)), "endo", bad_rows)["score"]
    assert worse < clean


def test_filters_profile_equipment_and_documents():
    specialist = doctor("Спец", ("Стоматолог", "Стоматолог-эндодонтист"), clinics=("c2",))   # клиника без микроскопа
    general = doctor("Общий", ("Стоматолог",), verified=True, clinics=("c1",))               # клиника с микроскопом
    both = [specialist, general]
    assert [r["name"] for r in rank_doctors(both, "endo", ROWS, only_profile=True)] == ["Спец"]
    assert [r["name"] for r in rank_doctors(both, "endo", ROWS, require_equipment=True)] == ["Общий"]
    assert [r["name"] for r in rank_doctors(both, "endo", ROWS, verified_docs=True)] == ["Общий"]


def test_every_topic_has_a_doctor_profile():
    from app.matching import TOPICS
    assert set(TOPICS) <= set(NEEDS)


def test_api_recommends_doctors_with_reasons():
    from fastapi.testclient import TestClient
    from app.api import app
    client = TestClient(app)
    res = client.post("/api/recommend/doctors", json={"need": "endo", "limit": 5}).json()
    assert res["total"] > 0 and len(res["items"]) == 5
    scores = [i["score"] for i in res["items"]]
    assert scores == sorted(scores, reverse=True) and all(i["reasons"] for i in res["items"])
    only = client.post("/api/recommend/doctors", json={"need": "endo", "limit": 100, "only_profile": True}).json()
    assert only["total"] == only["with_profile"] > 0 and all(i["profile_match"] for i in only["items"])
    assert client.post("/api/recommend/doctors", json={"need": "nope"}).status_code == 400
