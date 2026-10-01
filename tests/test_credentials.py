from datetime import date

from app.models import CredentialCheckRequest as Req
from app.verification.credentials import check_credential

TODAY = date(2026, 10, 1)


def check(**kw):
    return check_credential(Req(**kw), today=TODAY)


def test_vendor_master_title_is_marketing_not_degree():
    v = check(title="Master of Oral Implantology & Guided Surgery", issuer="Straumann", year=2021,
              document_id="CH-STR-84920-KG")
    assert v.claim_type == "vendor_course"
    assert v.verdict == "сомнительно"
    assert any("маркетинговое" in f for f in v.red_flags)
    assert any("Номер документа" in w for w in v.warnings)


def test_postgrad_before_graduation_is_impossible():
    v = check(title="Клиническая ординатура по ортодонтии", issuer="КГМА", year=2010, holder_graduation_year=2011)
    assert v.verdict == "признаки подделки"
    assert v.weight == 0


def test_experience_longer_than_career():
    v = check(title="Сертификат специалиста", issuer="Минздрав КР", holder_graduation_year=2015,
              holder_experience_years=20)
    assert v.verdict == "признаки подделки"


def test_future_year():
    assert check(title="Диплом", issuer="КГМА", year=2030).verdict == "признаки подделки"


def test_unknown_grand_issuer_is_doubtful():
    v = check(title="Certificate of Excellence", issuer="International Academy of Aesthetic Dentistry")
    assert not v.issuer_known
    assert v.verdict == "сомнительно"


def test_awards_do_not_count():
    v = check(title="Лучший стоматолог года", issuer="Bishkek Awards")
    assert v.claim_type == "award" and v.weight == 0 and v.verdict == "не является квалификацией"


def test_invisalign_locator_confirmed():
    v = check(title="Invisalign Provider", issuer="Align Technology", evidence_level=3)
    assert v.claim_type == "vendor_provider_status" and v.verdict == "подтверждено"
    assert any("invisalign.com" in l["url"] for l in v.verify_links)


def test_license_points_to_registries():
    v = check(title="Лицензия на медицинскую деятельность", issuer="Министерство здравоохранения КР")
    urls = " ".join(l["url"] for l in v.verify_links)
    assert "license.med.kg" in urls and "tunduk" in urls


def test_registry_level_evidence_outweighs_claim():
    claimed = check(title="Диплом врача-стоматолога", issuer="КГМА", evidence_level=1)
    verified = check(title="Диплом врача-стоматолога", issuer="КГМА", evidence_level=3)
    assert verified.weight > claimed.weight * 2


def test_implant_course_without_surgical_specialty_warns():
    v = check(title="Курс по синус-лифтингу", issuer="Osstem", holder_specialty="терапевт")
    assert any("имплантации" in w for w in v.warnings)
