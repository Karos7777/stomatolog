import pytest

from app.database import repo
from app.verification.licenses import (_address_match, _person_match, area_words, chairs_of, check_clinic,
                                       is_state_clinic, name_tokens, parse_address, same_street, scope_gaps, scope_of)


@pytest.mark.parametrize("raw,street,house", [
    ("улица Исы Ахунбаева, 42а", "исы ахунбаева", "42а"),
    ("8-й микрорайон, 83", "мкр8", "83"),
    ("мкр. 8 462", "мкр8", "462"),
    ("ул. А.Дуйшеева 8", "дуйшеева", "8"),
    ("улица 7 апреля, 2/12", "апреля7", "2/12"),
    ("микрорайон Джал-23, 18/2", "джал-23", "18/2"),
    ("ул. Московская 219-2", "московская", "219"),
    ("ул. Шевченко 6 (MedC", "шевченко", "6"),
    ("улица Молдокулова, 2", "молдокулова", "2"),      # «ул» внутри слова не трогаем
    ("ул. Пржевальского 5", "пржевальского", "5"),
    ("бульв. Молодой Гвардии 2/1", "молодой гвардии", "2/1"),
    ("микрорайон Улан, 3/3", "улан", "3/3"),
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
    ("metadent", "verified"),         # ИП врача клиники Темиркулова Н.С. на тот же адрес (врач найден в полной базе YDoc)
    ("dentmen", "ambiguous"),         # MedCity: много лицензиатов в одном здании
    ("kairos", "name_other_address"), # «КАЙРОС стом» — на Рыскулова, 79б
    ("emmar", "verified"),            # ИП врача клиники Эшдолотова Э.М., «мкр. Асанбай 17/1» = ул. Айтиева 17/1
    ("kings-clinic", "verified"),     # ИП Макеевой Э.А.: в реестре «Суюмбаева 102» вместо «10/2»
    ("expert-dental", "not_found"),   # ИП Эргешовой Айгул — не врач клиники Эргешова Бегимай
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


def _rec(name, address="ул. Несуществующая 1"):
    street, house = parse_address(address)
    return {"name": name, "_tokens": name_tokens(name, fallback=True), "_street": street, "_house": house}


@pytest.mark.parametrize("doctor,holder,same", [
    ("Валиев Мирбек Бектурсунович", "ИП Валиев Мирбек Бектурсунович", True),
    ("Тыналиев Уланбек Аманович", "Тыналиеву Уланбеку Амановичу", True),             # дательный падеж
    ("Мамедкасанов Видади Адыкезалович", "Мамедкасанов Вивади Адыкезалович", True),   # опечатка + отчество
    ("Ваис Светлана Евгеньевна", "Вайс Светлане Евгеньевне", True),
    ("Эшдолотов Эмиль", "Эшдолотов Эмиль Маратович", True),
    ("Эргешова Бегимай Эргешовна", "ИП Эргешова Айгул Салижановна", False),          # отчество ≠ фамилия
    ("Шукуров Эрбол Азизбекович", "ИП Шукуров Уран Азизбекович", False),            # братья
    ("Талантбеков Аскат Талантбекович", "ИП Талантбекова Жанат Талантбековна", False),
    ("Баялиев Тимурлан", "ИП Баялиев Темурлан Усупжанович", False),                  # опечатка без отчества
])
def test_person_match(doctor, holder, same):
    assert _person_match([name_tokens(doctor)], _rec(holder)) is same


def test_registry_address_typos():
    street, house = parse_address("улица Ахматбека Суюмбаева, 10/2 (1 этаж)")
    assert _address_match(street, house, _rec("x", "ул. Суюмбаева 102")) == "probable"   # потерянная дробь
    street, house = parse_address("микрорайон Джал-29, 41")
    assert _address_match(street, house, _rec("x", "мкр. Джал 41")) == "probable"
    assert _address_match(street, house, _rec("x", "мкр. Джал 42")) is None
    street, house = parse_address("улица Касыма Тыныстанова, 1")
    assert _address_match(street, house, _rec("x", "ул. Тыныстанова 18")) is None   # «1» — не начало «18»
    street, house = parse_address("улица Токтогула, 106, офис 18")
    assert _address_match(street, house, _rec("x", "ул. Токтогула 10618")) == "probable"


def test_area_words():
    assert area_words("Асанбай м-н") == "асанбай"
    assert area_words("12-й м-н") == "мкр12"
    assert area_words(None) == ""


def test_state_polyclinics_are_not_expected_in_private_registry():
    # приказ МЗ КР №212 (25.03.2013), п. 1.2: лицензируется только негосударственный сектор
    assert is_state_clinic(["Стоматологическая поликлиника №2"])
    assert is_state_clinic(["Городская стоматологическая поликлиника №7"])
    assert not is_state_clinic(["ОсОО «Поликлиника 312»", "Smile Clinic"])
    assert check_clinic(["Стоматологическая поликлиника №5"], "8-й микрорайон, 83")["status"] == "state"
