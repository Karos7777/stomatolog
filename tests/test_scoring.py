from app.models import Clinic
from app.scoring import evaluate, rank


def obs(rating, ratings=None, observed="2026-10-01", via="web_search_snippet", platform="2gis"):
    return {"platform": platform, "rating": rating, "ratings_count": ratings,
            "source": {"url": "https://2gis.kg/x", "observed": observed, "via": via}}


def clinic(cid, ratings=(), **kw):
    return Clinic(id=cid, name=cid, address="ул. Тестовая, 1", ratings=list(ratings), **kw)


def test_volume_beats_tiny_perfect_score():
    big = clinic("big", [obs(4.9, 500)])
    tiny = clinic("tiny", [obs(5.0, 14)])
    ranked = rank([big, tiny])
    assert ranked[0]["clinic"].id == "big"


def test_no_rating_means_unranked_not_bad():
    ranked = rank([clinic("a", [obs(4.5, 40)]), clinic("b")])
    b = next(r for r in ranked if r["clinic"].id == "b")
    assert b["score"]["trust_index"] is None and b["position"] is None
    assert ranked[-1]["clinic"].id == "b"


def test_conflicting_snapshots_use_conservative_values():
    c = clinic("c", [obs(5.0, 524), obs(4.9, 551)])
    s = evaluate(c, prior=4.8)
    assert s["rating"] == 4.9 and s["volume"] == 524


def test_api_observation_overrides_search_snippet():
    c = clinic("c", [obs(5.0, 100), obs(4.6, 130, via="platform_api")])
    s = evaluate(c, prior=4.8)
    assert s["rating"] == 4.6 and s["volume"] == 130
    assert s["confidence"] == "средняя"


def test_velocity_spike_penalised():
    calm = clinic("calm", [obs(4.8, 100, "2026-01-01", "platform_api"), obs(4.8, 110, "2026-03-01", "platform_api"),
                           obs(4.8, 121, "2026-05-01", "platform_api")])
    spiky = clinic("spiky", [obs(4.8, 100, "2026-01-01", "platform_api"), obs(4.8, 110, "2026-03-01", "platform_api"),
                             obs(4.9, 190, "2026-03-15", "platform_api")])
    a_calm = evaluate(calm, 4.8)["components"]["authenticity"]["score"]
    a_spiky = evaluate(spiky, 4.8)["components"]["authenticity"]
    assert a_spiky["score"] < a_calm
    assert any("Скачок" in f["text"] for f in a_spiky["flags"])


def test_cross_platform_gap_penalised():
    c = clinic("c", [obs(4.9, 300), obs(4.2, 60, platform="google")])
    auth = evaluate(c, 4.8)["components"]["authenticity"]
    assert auth["score"] <= 55


def test_license_not_found_zeroes_credentials():
    c = clinic("c", [obs(4.9, 300)], license={"status": "not_found"})
    s = evaluate(c, 4.8)
    assert s["components"]["credentials"]["score"] == 0
    assert any(f["level"] == "red" for f in s["flags"])


def test_verified_license_raises_credentials_and_confidence():
    src = {"url": "https://license.med.kg/ru/", "observed": "2026-10-01", "via": "official_registry"}
    c = clinic("c", [obs(4.9, 300, via="platform_api")], license={"status": "verified", "source": src})
    s = evaluate(c, 4.8)
    assert s["components"]["credentials"]["score"] >= 45
    assert s["confidence"] == "высокая"
