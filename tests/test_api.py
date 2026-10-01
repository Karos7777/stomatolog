from fastapi.testclient import TestClient

from app.api import app

client = TestClient(app)


def test_home_page():
    r = client.get("/")
    assert r.status_code == 200 and "DentBishkek" in r.text


def test_meta_reports_registry_and_coverage():
    m = client.get("/api/meta").json()
    assert m["clinics_total"] >= 400 and m["clinics_curated"] == 26
    assert m["registry"]["as_of"] == "12.11.2025"
    assert m["licenses_found"] > 100 and sum(m["license_statuses"].values()) == m["clinics_total"]


def test_clinics_sorted_by_trust_and_filters():
    res = client.get("/api/clinics", params={"limit": 600}).json()
    ranked = [r["trust_index"] for r in res["items"] if r["trust_index"] is not None]
    assert ranked == sorted(ranked, reverse=True) and res["total"] == len(res["items"])
    assert not any(r["multi_profile"] for r in res["items"])
    page = client.get("/api/clinics", params={"limit": 10, "offset": 10}).json()
    assert len(page["items"]) == 10 and page["items"][0]["id"] == res["items"][10]["id"]
    only = client.get("/api/clinics", params={"only_24_7": True}).json()["items"]
    assert only and all(r["is_24_7"] for r in only)
    q = client.get("/api/clinics", params={"q": "Коенкозова, 75"}).json()["items"]
    assert [r["id"] for r in q] == ["dental-house"]
    found = client.get("/api/clinics", params={"license": "found", "limit": 600}).json()["items"]
    assert found and all(r["license"]["status"] in ("verified", "probable", "address_match") for r in found)
    unlic = client.get("/api/clinics", params={"license": "unlicensed", "dental_only": False}).json()["items"]
    assert unlic and all(r["license"]["unlicensed_at_address"] for r in unlic)


def test_clinic_detail_has_evidence():
    d = client.get("/api/clinics/estet").json()
    assert d["clinic"]["inn"] == "01302200910105"
    assert any(o["source"]["via"] == "platform_api" for o in d["clinic"]["ratings"])
    assert d["clinic"]["license"]["status"] == "verified"
    assert d["clinic"]["license"]["matches"][0]["number"] == "НГМУ 4259"
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


def test_static_assets_are_versioned_and_revalidated():
    page = client.get("/")
    assert "app.js?v=" in page.text and "style.css?v=" in page.text
    assert page.headers["cache-control"] == "no-cache"
    assert client.get("/static/js/app.js").headers["cache-control"] == "no-cache"
