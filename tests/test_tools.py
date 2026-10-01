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
    api_obs = [o for o in emmar.ratings if o.source.via == "platform_api"]
    assert len(api_obs) == 1 and api_obs[0].ratings_count == 480 and api_obs[0].reviews_count == 210
    assert emmar.coordinates == {"lat": 42.87, "lng": 74.6}
    assert len(emmar.ratings) == 3  # старые наблюдения сохранены


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
