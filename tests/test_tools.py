import io
import json
import shutil
from datetime import date

from app.database import CLINICS_FILE, ClinicRepository
from tools import import_reviews, refresh_2gis


class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake_opener(url, timeout=20):
    payload = {"meta": {"code": 200}, "result": {"items": [{
        "id": "x", "point": {"lat": 42.87, "lon": 74.6},
        "reviews": {"general_rating": 4.7, "general_review_count": 210, "general_review_count_with_stars": 480}}]}}
    return FakeResp(json.dumps(payload).encode())


def test_refresh_appends_api_observation(tmp_path):
    path = tmp_path / "clinics.json"
    shutil.copy(CLINICS_FILE, path)
    repo = ClinicRepository(clinics_file=path, analyses_dir=tmp_path / "an")
    report = refresh_2gis.refresh(repo, "KEY", only={"emmar"}, opener=fake_opener, today=date(2026, 10, 2))
    assert report["emmar"].startswith("4.7")
    reloaded = ClinicRepository(clinics_file=path, analyses_dir=tmp_path / "an")
    emmar = reloaded.get("emmar")
    new = [o for o in emmar.ratings if o.source.via == "platform_api" and o.source.observed == "2026-10-02"]
    assert len(new) == 1 and new[0].ratings_count == 480 and new[0].reviews_count == 210
    assert any(o.source.via == "web_search_snippet" for o in emmar.ratings)  # старые наблюдения сохранены


def test_refresh_reports_api_errors(tmp_path):
    path = tmp_path / "clinics.json"
    shutil.copy(CLINICS_FILE, path)
    repo = ClinicRepository(clinics_file=path, analyses_dir=tmp_path / "an")

    def bad(url, timeout=20):
        return FakeResp(json.dumps({"meta": {"code": 403, "error": {"message": "bad key"}}}).encode())

    report = refresh_2gis.refresh(repo, "BAD", only={"emmar"}, opener=bad, dry_run=True)
    assert "bad key" in report["emmar"]


def test_import_reviews_saves_analysis(tmp_path, monkeypatch):
    path = tmp_path / "clinics.json"
    shutil.copy(CLINICS_FILE, path)
    monkeypatch.setattr(import_reviews, "ClinicRepository",
                        lambda: ClinicRepository(clinics_file=path, analyses_dir=tmp_path / "an"))
    csv_path = tmp_path / "r.csv"
    shutil.copy("examples/synthetic_boosted_reviews.csv", csv_path)
    assert import_reviews.main(["emmar", str(csv_path)]) == 0
    repo = ClinicRepository(clinics_file=path, analyses_dir=tmp_path / "an")
    assert repo.analyses()["emmar"].verdict == "strong_signals"


def test_crawl_splits_city_until_each_tile_fits(tmp_path):
    from tools import crawl_2gis
    from urllib.parse import parse_qs, urlparse

    def item(i, lon, lat):
        return {"id": str(i), "name": f"Клиника {i}, стоматология", "address_name": f"ул. Тестовая, {i}",
                "point": {"lat": lat, "lon": lon}, "org": {"id": f"o{i}", "branch_count": 1, "primary": f"Клиника {i}"},
                "reviews": {"general_rating": 4.5, "general_review_count": 10, "general_review_count_with_stars": 20}}

    world = [item(i, 74.46 + (i % 12) * 0.025, 42.78 + (i // 12) * 0.015) for i in range(120)]

    def opener(url, timeout=30):
        q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
        if q["rubric_id"] != "222":
            return FakeResp(json.dumps({"meta": {"code": 404}}).encode())
        l, t = map(float, q["point1"].split(",")); r, b = map(float, q["point2"].split(","))
        inside = [w for w in world if l <= w["point"]["lon"] < r and b < w["point"]["lat"] <= t]
        page = int(q["page"])
        payload = {"meta": {"code": 200}, "result": {"total": len(inside), "items": inside[(page - 1) * 10: page * 10]}}
        return FakeResp(json.dumps(payload).encode())

    out = tmp_path / "gis.json"
    meta = crawl_2gis.run("KEY", out=out, opener=opener, today="2026-10-01", pause=0)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert meta["total"] == 120 and len(data["items"]) == 120
    assert data["items"][0]["history"] == [{"date": "2026-10-01", "rating": 4.5, "ratings_count": 20, "reviews_count": 10}]
    crawl_2gis.run("KEY", out=out, opener=opener, today="2026-11-01", pause=0)
    again = json.loads(out.read_text(encoding="utf-8"))
    assert len(again["items"][0]["history"]) == 2   # история копится


def test_registry_links_found_on_minzdrav_page():
    from tools.license_registry import find_links
    page = ('<a href="uploads/abc-Реестр выданных лицензий на медицинскую деятельность (по состоянию на 12.11. 2025 г.).xlsx">'
            'Реестр</a><a href="uploads/def-Список субъектов предпренимательства осуществляющих без лицензионную '
            'деятельность.docx">Список</a>')
    links = find_links(page)
    assert links["licenses"][0].startswith("https://med.kg/uploads/") and links["licenses"][0].endswith(".xlsx")
    assert "12.11. 2025" in links["licenses"][1]
    assert links["unlicensed"][0].endswith(".docx")
