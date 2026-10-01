"""Генератор СИНТЕТИЧЕСКИХ отзывов для тестов и демонстрации анализатора.

Это не реальные отзывы ни о какой клинике. Нужны, чтобы проверить, что детекторы
отличают органичный поток отзывов от накрученного.

    python -m tools.synthetic_reviews   # пересоздать examples/*.csv
"""
import csv
import random
from datetime import date, timedelta
from pathlib import Path
from typing import List

from app.models import ReviewInput

NAMES = ["Айгерим", "Бакыт", "Нурлан", "Елена", "Азамат", "Мээрим", "Сергей", "Динара", "Улан",
         "Жылдыз", "Алина", "Тимур", "Чолпон", "Марат", "Ольга", "Эрлан", "Камила", "Бекжан",
         "Асель", "Руслан", "Гульнара", "Максат", "Наталья", "Айбек", "Светлана", "Нургуль"]
DOCTORS = ["Асель Маратовна", "Бектур", "Ирина Викторовна", "Азиз", "Эрмек", "Наргиза", "Тилек",
           "Жанара", "Алмаз", "Виктория"]
WHO = ["Мне", "Сыну", "Маме", "Мужу", "Дочке", "Папе", "Жене", "Мне и брату"]
PROCEDURES = ["лечили два канала на нижней шестёрке", "поставили пломбу на семёрку",
              "удаляли нижний зуб мудрости", "делали профчистку с Air Flow",
              "ставили имплант Osstem", "делали циркониевую коронку", "лечили кариес на молочных зубах",
              "ставили брекеты на верхнюю челюсть", "делали КТ перед имплантацией",
              "перелечивали старый канал", "меняли старую пломбу", "делали временную коронку",
              "снимали воспаление десны", "лечили пульпит"]
OPENERS = ["Ходили в начале месяца.", "Были здесь уже раз пятый.", "Пришла по совету подруги.",
           "Нашли клинику через 2ГИС.", "Обратились с острой болью вечером.", "Записались за два дня.",
           "Переехали в этот район и искали рядом.", "", "", ""]
DOC_LINES = ["Врач {d} всё объяснила спокойно и показала снимок.", "{d} работает аккуратно, без спешки.",
             "Доктор {d} сразу сказал, сколько будет стоить.", "У {d} лёгкая рука, укол почти не почувствовал.",
             "{d} предложил два варианта лечения на выбор.", ""]
DETAILS = ["Вышло около {p} сом, как и говорили.", "Ждал в коридоре минут {m}.",
           "Через неделю на контроле всё хорошо.", "Анестезия подействовала сразу.",
           "Администратор перезвонила накануне и напомнила о визите.", "Дали гарантию на год.",
           "Пришлось прийти второй раз на подгонку.", "Парковка рядом неудобная.",
           "Оплатили картой, дали чек.", "Сделали за {k} визита.", "Дома немного ныло пару дней, потом прошло."]
CLOSERS = ["Спасибо!", "Буду ходить сюда.", "Пока всё держится.", "Цены средние по городу.",
           "Рекомендую этого врача.", "", "", ""]
NEGATIVE = ["Пломба выпала через {m} дней, переделывать бесплатно отказались.",
            "Ждал больше часа, хотя был записан на {k}:00. Врач торопился и ничего не объяснил.",
            "Итоговая цена оказалась на {p} сом выше, чем озвучили на консультации.",
            "После удаления неделю болело, на звонки в клинику не отвечали.",
            "Коронку переделывали {k} раза, в итоге всё равно мешает при жевании.",
            "Администратор нагрубила по телефону, перенесли запись без предупреждения.",
            "Ребёнка не смогли успокоить, сказали приходить с наркозом за {p} сом.",
            "Поставили брекеты, а через месяц половина отклеилась, за переклейку взяли деньги."]
FAKE_TEMPLATES = ["Лучшая клиника в Бишкеке! Всем рекомендую, врачи профессионалы своего дела!",
                  "Лучшая клиника Бишкека!!! Всем советую, врачи настоящие профессионалы!",
                  "Отличная клиника, лучшие врачи! Всем рекомендую! Спасибо большое!",
                  "Супер клиника! Золотые руки! Всем рекомендую!",
                  "Очень довольна, всё на высшем уровне, рекомендую!"]


def _fmt(rng: random.Random, s: str) -> str:
    return s.format(d=rng.choice(DOCTORS), p=rng.randint(2, 40) * 500, m=rng.randint(5, 90),
                    k=rng.randint(2, 4))


def _organic_text(rng: random.Random, rating: int) -> str:
    if rating <= 2:
        parts = [rng.choice(OPENERS), f"{rng.choice(WHO)} {rng.choice(PROCEDURES)}.",
                 _fmt(rng, rng.choice(NEGATIVE)), _fmt(rng, rng.choice(DETAILS))]
        return " ".join(p for p in parts if p)
    parts = [rng.choice(OPENERS), f"{rng.choice(WHO)} {rng.choice(PROCEDURES)}.",
             _fmt(rng, rng.choice(DOC_LINES))]
    parts += [_fmt(rng, x) for x in rng.sample(DETAILS, rng.randint(1, 3))]
    if rating == 3:
        parts.append("Сделали нормально, но сервис мог бы быть лучше.")
    parts.append(rng.choice(CLOSERS))
    return " ".join(p for p in parts if p)


def generate(kind: str = "organic", seed: int = 7, start: date = date(2024, 9, 1),
             weeks: int = 104) -> List[ReviewInput]:
    rng = random.Random(seed)
    out: List[ReviewInput] = []
    for w in range(weeks):
        for _ in range(rng.choice([0, 1, 1, 1, 2, 2, 3])):
            rating = rng.choices([5, 4, 3, 2, 1], weights=[70, 13, 5, 4, 8])[0]
            out.append(ReviewInput(
                text=_organic_text(rng, rating), rating=rating,
                date=(start + timedelta(days=7 * w + rng.randint(0, 6))).isoformat(),
                author=f"{rng.choice(NAMES)} {rng.choice('АБВГДЕЖЗКМНОРСТ')}.",
                author_reviews_count=rng.choice([1, 1, 2, 3, 4, 6, 9, 15, 27, 40])))
    if kind == "organic":
        return sorted(out, key=lambda r: r.date)

    # --- накрученный вариант: тот же органичный фон + типичные приёмы ---
    burst_start = start + timedelta(days=7 * 60)
    for i in range(45):  # пакет пятёрок за 6 дней
        out.append(ReviewInput(
            text=rng.choice(FAKE_TEMPLATES), rating=5,
            date=(burst_start + timedelta(days=rng.randint(0, 5))).isoformat(),
            author=f"{rng.choice(NAMES)}", author_reviews_count=1))
    for d in (start + timedelta(days=7 * 30), start + timedelta(days=7 * 85)):  # засыпаем негатив
        out.append(ReviewInput(text=NEGATIVE[0].format(m=14, p=0), rating=1, date=d.isoformat(),
                               author="Игорь П.", author_reviews_count=12))
        for k in range(4):
            out.append(ReviewInput(text=rng.choice(FAKE_TEMPLATES), rating=5,
                                   date=(d + timedelta(days=1 + k % 2)).isoformat(),
                                   author=rng.choice(NAMES), author_reviews_count=1))
    return sorted(out, key=lambda r: r.date)


def write_csv(reviews: List[ReviewInput], path: Path) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "rating", "author", "author_reviews_count", "text"])
        for r in reviews:
            w.writerow([r.date, r.rating, r.author, r.author_reviews_count, r.text])


if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent / "examples"
    root.mkdir(exist_ok=True)
    write_csv(generate("organic"), root / "synthetic_organic_reviews.csv")
    write_csv(generate("fake"), root / "synthetic_boosted_reviews.csv")
    print("Записано в", root)
