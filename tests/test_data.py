"""Проверки целостности базы: ничего без источника, никаких «верифицировано» без реестра."""
import re

from app.database import load_legacy_audit, repo
from app.scoring import rank

OLD_FAKE_ID = re.compile(r"^[A-ZА-Я]{2,}-[A-ZА-Я]{2,}-\d{2,}")


def test_every_clinic_has_a_source():
    for c in repo.curated():
        assert c.all_sources(), c.id
        assert all(s.url.startswith("https://") for s in c.all_sources()), c.id


def test_every_rating_has_url_and_date():
    for c in repo.all():
        for o in c.ratings:
            assert o.source.url.startswith("https://"), c.id
            assert re.match(r"\d{4}-\d{2}-\d{2}$", o.source.observed), c.id


def test_no_license_marked_found_without_registry_record():
    for c in repo.all():
        if c.license.status in ("verified", "probable", "address_match"):
            assert c.license.matches and c.license.source and c.license.source.via == "official_registry", c.id
            assert re.match(r"^(НГМУ|ИП|Ип)\s*\d+", c.license.matches[0].number), c.id


def test_no_invented_certificate_numbers():
    for c in repo.all():
        for d in c.doctors:
            for claim in d.claims:
                assert not (claim.document_id and OLD_FAKE_ID.match(claim.document_id)), (c.id, claim.document_id)
                if claim.evidence.level >= 2:
                    assert claim.evidence.source is not None, (c.id, claim.title)


def test_ids_unique_and_ranking_runs():
    ids = [c.id for c in repo.all()]
    assert len(ids) == len(set(ids))
    ranked = rank(repo.all())
    assert sum(1 for r in ranked if r["position"]) >= 400


def test_legacy_audit_is_complete():
    audit = load_legacy_audit()
    assert len(audit["entries"]) == 15
    assert all(e["verdict"] in audit["verdict_labels"] for e in audit["entries"])
    assert sum(1 for e in audit["entries"] if e["verdict"] == "not_found") == 1
