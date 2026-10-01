from fastapi.testclient import TestClient

from app.api import app

client = TestClient(app)


def test_home_page():
    r = client.get("/")
    assert r.status_code == 200 and "DentBishkek" in r.text


def test_meta_is_honest_about_licenses():
    m = client.get("/api/meta").json()
    assert m["licenses_verified"] == 0
    assert "не проверено" in m["license_note"]


def test_clinics_sorted_by_trust_and_filters():
    rows = client.get("/api/clinics").json()
    ranked = [r["trust_index"] for r in rows if r["trust_index"] is not None]
    assert ranked == sorted(ranked, reverse=True)
    only = client.get("/api/clinics", params={"only_24_7": True}).json()
    assert only and all(r["is_24_7"] for r in only)
    q = client.get("/api/clinics", params={"q": "Коенкозова"}).json()
    assert {r["id"] for r in q} == {"dental-house", "solnyshko"}


def test_clinic_detail_has_evidence():
    d = client.get("/api/clinics/estet").json()
    assert d["clinic"]["inn"] == "01302200910105"
    assert d["clinic"]["ratings"][0]["source"]["url"].startswith("https://2gis.kg/")
    assert client.get("/api/clinics/nope").status_code == 404


def test_match_emergency_returns_only_24_7():
    res = client.post("/api/match", json={"problem": "острая боль ночью"}).json()
    assert res["need_24_7"] and all(r["is_24_7"] for r in res["results"])


def test_analyze_reviews_from_example_and_errors():
    raw = client.get("/api/examples/boosted").text
    a = client.post("/api/analyze/reviews", json={"raw": raw}).json()
    assert a["verdict"] == "strong_signals"
    assert client.post("/api/analyze/reviews", json={}).status_code == 400
    assert client.post("/api/analyze/reviews", json={"raw": "[{bad json", "format": "json"}).status_code == 400


def test_analyze_credential():
    v = client.post("/api/analyze/credential", json={"title": "Участник конгресса", "issuer": "EAO"}).json()
    assert v["claim_type"] == "conference"


def test_methodology_and_audit():
    assert "duplicates" in client.get("/api/methodology").json()["review_references"]
    assert client.get("/api/legacy-audit").json()["entries"]
