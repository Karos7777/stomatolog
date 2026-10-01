"""Обновление рейтингов через официальный 2GIS Places API (нужен ваш ключ: https://dev.2gis.com).

    python -m tools.refresh_2gis --key ВАШ_КЛЮЧ            # все клиники с карточкой 2ГИС
    python -m tools.refresh_2gis --key ... --only emmar,metadent --dry-run

Каждый запуск ДОБАВЛЯЕТ наблюдение (а не перезаписывает), поэтому со временем
копится история. По ней индекс доверия ловит резкие скачки числа оценок —
типичный след покупки пакета отзывов.
"""
import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import date
from typing import Callable, Dict, Optional

from app.database import ClinicRepository
from app.models import RatingObservation, Source

API = "https://catalog.api.2gis.com/3.0/items/byid"
FIELDS = "items.reviews,items.point,items.address,items.schedule"


def fetch_item(firm_id: str, key: str, opener: Callable = urllib.request.urlopen) -> Optional[Dict]:
    query = urllib.parse.urlencode({"id": firm_id, "fields": FIELDS, "key": key, "locale": "ru_KG"})
    with opener(f"{API}?{query}", timeout=20) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    code = payload.get("meta", {}).get("code")
    if code != 200:
        raise RuntimeError(f"2ГИС ответил {code}: {payload.get('meta', {}).get('error', {}).get('message', '')}")
    items = payload.get("result", {}).get("items", [])
    return items[0] if items else None


def observation_from_item(item: Dict, firm_id: str, today: date) -> Optional[RatingObservation]:
    reviews = item.get("reviews") or {}
    rating = reviews.get("general_rating")
    if rating is None:
        return None
    return RatingObservation(
        platform="2gis",
        rating=float(rating),
        ratings_count=reviews.get("general_review_count_with_stars") or reviews.get("org_review_count_with_stars"),
        reviews_count=reviews.get("general_review_count") or reviews.get("review_count"),
        source=Source(url=f"https://2gis.kg/bishkek/firm/{firm_id}", observed=today.isoformat(),
                      via="platform_api", title="2GIS Places API"),
    )


def refresh(repo: ClinicRepository, key: str, only=None, dry_run: bool = False,
            opener: Callable = urllib.request.urlopen, today: Optional[date] = None) -> Dict[str, str]:
    today = today or date.today()
    report: Dict[str, str] = {}
    for clinic in repo.all():
        if only and clinic.id not in only:
            continue
        if not clinic.gis_firm_id:
            report[clinic.id] = "нет id карточки 2ГИС — пропущено"
            continue
        try:
            item = fetch_item(clinic.gis_firm_id, key, opener)
        except Exception as exc:  # noqa: BLE001 — сеть/ключ: продолжаем по остальным клиникам
            report[clinic.id] = f"ошибка: {exc}"
            continue
        if not item:
            report[clinic.id] = "карточка не найдена"
            continue
        obs = observation_from_item(item, clinic.gis_firm_id, today)
        if obs is None:
            report[clinic.id] = "в ответе нет рейтинга"
            continue
        clinic.ratings = [o for o in clinic.ratings
                          if not (o.source.via == "platform_api" and o.source.observed == obs.source.observed)]
        clinic.ratings.append(obs)
        point = item.get("point")
        if point and "lat" in point and "lon" in point:
            clinic.coordinates = {"lat": point["lat"], "lng": point["lon"]}
        report[clinic.id] = f"{obs.rating}★, оценок {obs.ratings_count}, отзывов {obs.reviews_count}"
    if not dry_run:
        repo.meta["last_api_refresh"] = today.isoformat()
        repo.save()
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--key", default=os.environ.get("DGIS_API_KEY"), help="ключ 2GIS API (или DGIS_API_KEY)")
    ap.add_argument("--only", help="id клиник через запятую")
    ap.add_argument("--dry-run", action="store_true", help="не сохранять изменения")
    args = ap.parse_args(argv)
    if not args.key:
        print("Нужен ключ: --key или переменная окружения DGIS_API_KEY")
        return 1
    only = set(args.only.split(",")) if args.only else None
    report = refresh(ClinicRepository(), args.key, only, args.dry_run)
    for cid, msg in report.items():
        print(f"{cid:20s} {msg}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
