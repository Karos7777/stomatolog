from datetime import date

from app.importers import parse_reviews
from app.verification.dates import parse_date


def test_csv_with_russian_headers_and_semicolons():
    raw = "дата;оценка;автор;текст\n12.03.2026;5;Айгерим;Лечили канал\n13.03.2026;2;Бакыт;Долго ждал\n"
    reviews = parse_reviews(raw)
    assert [r.rating for r in reviews] == [5, 2]
    assert reviews[0].author == "Айгерим"
    assert parse_date(reviews[1].date) == date(2026, 3, 13)


def test_json_list_and_wrapped():
    assert len(parse_reviews('[{"text": "a", "rating": 5}]')) == 1
    wrapped = parse_reviews('{"reviews": [{"text": "a", "stars": "4"}, {"text": "b"}]}')
    assert [r.rating for r in wrapped] == [4, None]


def test_text_blocks_copied_from_2gis():
    raw = """Айгерим Т.
3 отзыва
12 марта 2026
5★
Лечили канал под микроскопом, всё хорошо.

Бакыт
1 отзыв
вчера
Лучшая клиника! Всем рекомендую!"""
    a, b = parse_reviews(raw)
    assert a.author == "Айгерим Т." and a.author_reviews_count == 3 and a.rating == 5
    assert a.text == "Лечили канал под микроскопом, всё хорошо."
    assert b.author == "Бакыт" and b.author_reviews_count == 1 and b.date == "вчера" and b.rating is None


def test_parse_date_formats():
    assert parse_date("2026-03-12") == date(2026, 3, 12)
    assert parse_date("12 мая 2025") == date(2025, 5, 12)
    assert parse_date("3 марта 2025") == date(2025, 3, 3)
    assert parse_date("вчера", today=date(2026, 1, 1)) == date(2025, 12, 31)
    assert parse_date("не дата") is None


def test_invalid_rating_is_dropped():
    assert parse_reviews("rating,text\n9,ok\n")[0].rating is None
