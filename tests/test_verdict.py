from app.models import Clinic
from app.scoring import evaluate
from app.verdict import verdict


def obs(rating, ratings):
    return {"platform": "2gis", "rating": rating, "ratings_count": ratings,
            "source": {"url": "https://2gis.kg/x", "observed": "2026-10-01", "via": "platform_api"}}


def lic(status="verified", **kw):
    m = {"number": "НГМУ 1", "holder": "ОсОО «Тест»", "address": "ул. Тестовая 1", "match": {"address": "exact", "name": "совпадает"}}
    return {"status": status, "matches": [m], **kw}


def run(clinic, need=None):
    return verdict(clinic, evaluate(clinic, 4.8), need)


def test_good_clinic():
    c = Clinic(id="a", name="A", address="ул. Тестовая, 1", ratings=[obs(4.8, 300)], license=lic())
    v = run(c)
    assert v["level"] == "good" and [x["status"] for x in v["checks"]][:2] == ["ok", "ok"]


def test_unlicensed_address_is_bad():
    c = Clinic(id="a", name="A", address="ул. Тестовая, 1", ratings=[obs(4.9, 300)],
               license=lic(unlicensed_at_address=[{"name": "Иванов", "address": "ул. Тестовая, 1"}]))
    assert run(c)["level"] == "bad"


def test_all_fives_needs_checking():
    c = Clinic(id="a", name="A", address="ул. Тестовая, 1", ratings=[obs(5.0, 400)], license=lic())
    v = run(c)
    assert v["level"] == "ok" and "пятёрки" in v["checks"][1]["title"]


def test_sedation_without_anesthesia_in_license_is_bad():
    c = Clinic(id="a", name="A", address="ул. Тестовая, 1", ratings=[obs(4.8, 300)],
               license=lic(scope_gaps=["анестезия/наркоз"]))
    assert run(c, need="sedation")["level"] == "bad"
    assert run(c)["level"] == "good"   # для лечения кариеса анестезия в лицензии не нужна


def test_not_in_registry_is_bad():
    c = Clinic(id="a", name="A", address="ул. Тестовая, 1", ratings=[obs(4.8, 300)], license={"status": "not_found"})
    assert run(c)["level"] == "bad"
