"""Проанализировать отзывы о клинике и учесть результат в индексе доверия.

    python -m tools.import_reviews emmar reviews.csv
    python -m tools.import_reviews emmar reviews.csv --unconfirmed 12 --rating 4.9 --count 425

Форматы: CSV/JSON с колонками date, rating, author, author_reviews_count, text
или текст, скопированный со страницы (отзывы через пустую строку).
"""
import argparse
import sys
from datetime import date
from pathlib import Path

from app.database import ClinicRepository
from app.importers import parse_reviews
from app.models import AggregateInput
from app.verification.reviews import analyze_reviews


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("clinic_id")
    ap.add_argument("file", type=Path)
    ap.add_argument("--format", default="auto", choices=["auto", "csv", "json", "text"])
    ap.add_argument("--unconfirmed", type=int, help="число «Неподтверждённых» отзывов в 2ГИС")
    ap.add_argument("--rating", type=float, help="рейтинг на площадке")
    ap.add_argument("--count", type=int, help="число оценок на площадке")
    args = ap.parse_args(argv)

    repo = ClinicRepository()
    clinic = repo.get(args.clinic_id)
    if clinic is None:
        print(f"Нет клиники с id «{args.clinic_id}». Доступные: {', '.join(c.id for c in repo.all())}")
        return 1
    reviews = parse_reviews(args.file.read_text(encoding="utf-8"), args.format)
    if not reviews:
        print("Не удалось прочитать ни одного отзыва.")
        return 1
    aggregate = None
    if args.unconfirmed is not None or args.rating or args.count:
        aggregate = AggregateInput(rating=args.rating, ratings_count=args.count, unconfirmed_count=args.unconfirmed)
    analysis = analyze_reviews(reviews, aggregate)
    path = repo.save_analysis(clinic.id, analysis, {"file": args.file.name, "imported": date.today().isoformat(),
                                                    "reviews": len(reviews)})
    print(f"{clinic.name}: индекс подлинности {analysis.authenticity_index} — {analysis.verdict_text}")
    print(f"Подозрительных: {analysis.suspicious_count} из {analysis.total}; "
          f"рейтинг {analysis.raw_mean_rating} → без них {analysis.cleaned_mean_rating}")
    for s in analysis.signals:
        if s.severity in ("warning", "critical"):
            print(f"  [{s.severity}] {s.title}: −{s.penalty}")
    print(f"Сохранено: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
