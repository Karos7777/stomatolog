import pytest

from app.database import repo
from app.verification.licenses import check_clinic, parse_address, same_street, scope_gaps, scope_of, chairs_of


@pytest.mark.parametrize("raw,street,house", [
    ("улица Исы Ахунбаева, 42а", "исы ахунбаева", "42а"),
    ("8-й микрорайон, 83", "мкр8", "83"),
    ("мкр. 8 462", "мкр8", "462"),
    ("ул. А.Дуйшеева 8", "дуйшеева", "8"),
    ("улица 7 апреля, 2/12", "апреля7", "2/12"),
    ("микрорайон Джал-23, 18/2", "джал-23", "18/2"),
    ("ул. Московская 219-2", "московская", "219"),
    ("ул. Шевченко 6 (MedC", "шевченко", "6"),
])
def test_parse_address(raw, street, house):
    assert parse_address(raw) == (street, house)


def test_same_street_handles_abbreviated_first_names():
    assert same_street("арстанбека дуйшеева", "дуйшеева")
    assert same_street("огонбаева атая", "огонбаева")
    assert not same_street("киевская", "московская")


def test_scope_and_chairs():
    act = "диагностика и лечение стоматологических заболеваний терапевтического и ортопедического профилей (на 4 кресла)"
    assert scope_of(act) == ["терапия", "ортопедия (коронки, протезы)"]
    assert chairs_of(act) == 4
    assert scope_gaps(["имплантация", "брекеты"], ["терапия"]) == ["хирургия", "ортодонтия (брекеты)"]
    assert scope_gaps(["имплантация"], ["общая практика"]) == []


@pytest.mark.parametrize("clinic_id,status", [
    ("estet", "verified"),            # ОсОО «Клиника-студия Эстет», мкр 3, 14/2
    ("dental-house", "verified"),     # ОсОО «Дентал Хаус» — латиница ↔ кириллица
    ("alpha-dental", "verified"),     # ИП на имя основателя (Абдылдаев Нурмухамет)
    ("implant-service", "verified"),
    ("metadent", "address_match"),    # по адресу — ИП на другое имя
    ("dentmen", "ambiguous"),         # MedCity: много лицензиатов в одном здании
    ("kairos", "name_other_address"), # «КАЙРОС стом» — на Рыскулова, 79б
    ("emmar", "not_found"),
])
def test_known_clinics_match_registry(clinic_id, status):
    assert repo.get(clinic_id).license.status == status


def test_unlicensed_flag_requires_exact_address():
    dentmen = repo.get("dentmen").license
    assert dentmen.unlicensed_at_address and all("Шевченко, 6" in u["address"] for u in dentmen.unlicensed_at_address)
    assert not repo.get("estet").license.unlicensed_at_address


def test_one_common_word_is_not_a_license_match():
    res = check_clinic(["Профи"], "улица Несуществующая, 1")
    assert res["status"] == "not_found"


def test_ip_requires_surname_and_name():
    # «Dr. Эмиль Дакенов» не должен совпасть с ИП «Эшдолотов Эмиль Маратович» по одному имени
    res = check_clinic(["Dr. Эмиль Дакенов"], "улица Несуществующая, 1")
    assert all("Эшдолотов" not in m["holder"] for m in res["matches"])
