"""Собрать ВСЕ стоматологии Бишкека из официального 2GIS Places API.

    DGIS_API_KEY=ваш_ключ python -m tools.crawl_2gis

Демо-ключ отдаёт максимум 5 страниц по 10 результатов на запрос, поэтому город
режется на прямоугольники, пока в каждом не останется ≤50 организаций.
Каждый запуск дописывает снимок рейтинга в историю (data/gis_bishkek.json),
чтобы со временем ловить резкие скачки числа оценок.
Ключ не сохраняется ни в какие файлы.
"""
import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

API = "https://catalog.api.2gis.com/3.0/items"
FIELDS = ("items.reviews,items.point,items.org,items.rubrics,items.schedule,items.address,items.attribute_groups,"
          "items.adm_div")
SKIP_GROUPS = {"Способы оплаты", "Услуги", "Премия 2ГИС"}
BISHKEK_BBOX = (74.45, 42.96, 74.76, 42.77)   # lon_left, lat_top, lon_right, lat_bottom
RUBRICS = {"222": "Частные стоматологии", "112852": "Частные детские стоматологии",
           "226": "Стоматологические поликлиники"}
OUT = Path(__file__).resolve().parent.parent / "data" / "gis_bishkek.json"
MAX_PER_QUERY = 50


class Client:
    def __init__(self, key: str, opener: Callable = urllib.request.urlopen, pause: float = 0.15):
        self.key, self.opener, self.pause = key, opener, pause
        self.requests = 0

    def page(self, rubric: str, bbox: Tuple[float, float, float, float], page: int) -> Dict:
        params = {"rubric_id": rubric, "point1": f"{bbox[0]},{bbox[1]}", "point2": f"{bbox[2]},{bbox[3]}",
                  "type": "branch", "page_size": 10, "page": page, "fields": FIELDS,
                  "key": self.key, "locale": "ru_KG"}
        self.requests += 1
        with self.opener(f"{API}?{urllib.parse.urlencode(params)}", timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        time.sleep(self.pause)
        code = payload.get("meta", {}).get("code")
        if code == 404:   # пустой прямоугольник
            return {"total": 0, "items": []}
        if code != 200:
            raise RuntimeError(f"2ГИС ответил {code}: {payload.get('meta', {}).get('error', {}).get('message')}")
        return payload["result"]


def crawl_rubric(client: Client, rubric: str, bbox, depth: int = 0) -> Dict[str, Dict]:
    first = client.page(rubric, bbox, 1)
    total = first.get("total", 0)
    found = {it["id"]: it for it in first.get("items", [])}
    if total <= MAX_PER_QUERY or depth >= 6:
        for p in range(2, min(5, (total + 9) // 10) + 1):
            for it in client.page(rubric, bbox, p).get("items", []):
                found[it["id"]] = it
        return found
    left, top, right, bottom = bbox
    mid_lon, mid_lat = (left + right) / 2, (top + bottom) / 2
    for sub in ((left, top, mid_lon, mid_lat), (mid_lon, top, right, mid_lat),
                (left, mid_lat, mid_lon, bottom), (mid_lon, mid_lat, right, bottom)):
        found.update(crawl_rubric(client, rubric, sub, depth + 1))
    return found


def _is_24_7(item: Dict) -> bool:
    sched = item.get("schedule") or {}
    if sched.get("is_24x7"):
        return True
    days = [v for k, v in sched.items() if isinstance(v, dict) and "working_hours" in v]
    return len(days) == 7 and all(
        any(h.get("from") == "00:00" and h.get("to") in ("24:00", "00:00") for h in d["working_hours"]) for d in days)


def normalize(item: Dict, rubric: str) -> Dict:
    rev = item.get("reviews") or {}
    org = item.get("org") or {}
    point = item.get("point") or {}
    comps = (item.get("address") or {}).get("components") or []
    street = next((c for c in comps if c.get("street")), {})
    return {
        "id": item["id"],
        "name": item.get("name"),
        "brand": org.get("primary") or (item.get("name") or "").split(",")[0],
        "org_id": org.get("id"),
        "branch_count": org.get("branch_count"),
        "address": item.get("address_name"),
        "address_comment": item.get("address_comment"),
        "street": street.get("street"),
        "house": street.get("number"),
        "building_id": (item.get("address") or {}).get("building_id"),
        "point": {"lat": point.get("lat"), "lng": point.get("lon")} if point else None,
        "rating": rev.get("general_rating"),
        "ratings_count": rev.get("general_review_count_with_stars"),
        "reviews_count": rev.get("general_review_count"),
        "org_rating": rev.get("org_rating"),
        "org_ratings_count": rev.get("org_review_count_with_stars"),
        "district": next((a.get("name") for a in item.get("adm_div") or [] if a.get("type") == "district"), None),
        "living_area": next((a.get("name", "").replace("\xa0", " ") for a in item.get("adm_div") or []
                             if a.get("type") == "living_area"), None),
        "rubrics": sorted({r.get("name") for r in item.get("rubrics") or [] if r.get("name")}),
        "services": [a.get("name") for g in item.get("attribute_groups") or [] if g.get("name") not in SKIP_GROUPS
                     for a in g.get("attributes") or [] if a.get("name")],
        "awards": [a.get("name") for g in item.get("attribute_groups") or [] if g.get("name") == "Премия 2ГИС"
                   for a in g.get("attributes") or [] if a.get("name")],
        "rubric_source": RUBRICS[rubric],
        "is_24_7": _is_24_7(item),
    }


def merge_history(old: Dict[str, Dict], new: Dict[str, Dict], today: str) -> None:
    for cid, rec in new.items():
        hist = list((old.get(cid) or {}).get("history", []))
        hist = [h for h in hist if h["date"] != today]
        if rec["rating"] is not None:
            hist.append({"date": today, "rating": rec["rating"], "ratings_count": rec["ratings_count"],
                         "reviews_count": rec["reviews_count"]})
        rec["history"] = sorted(hist, key=lambda h: h["date"])


def run(key: str, out: Path = OUT, opener: Callable = urllib.request.urlopen,
        today: Optional[str] = None, rubrics: Optional[List[str]] = None, pause: float = 0.15) -> Dict:
    today = today or date.today().isoformat()
    client = Client(key, opener, pause)
    collected: Dict[str, Dict] = {}
    for rubric in rubrics or list(RUBRICS):
        for cid, item in crawl_rubric(client, rubric, BISHKEK_BBOX).items():
            collected.setdefault(cid, normalize(item, rubric))
    old = {}
    if out.exists():
        old = {r["id"]: r for r in json.loads(out.read_text(encoding="utf-8"))["items"]}
    merge_history(old, collected, today)
    payload = {"meta": {"source": "2GIS Places API (catalog.api.2gis.com/3.0/items)", "fetched": today,
                        "bbox": BISHKEK_BBOX, "rubrics": RUBRICS, "total": len(collected),
                        "requests": client.requests},
               "items": sorted(collected.values(), key=lambda r: (-(r["ratings_count"] or 0), r["id"]))}
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return payload["meta"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--key", default=os.environ.get("DGIS_API_KEY"), help="ключ 2GIS (или переменная DGIS_API_KEY)")
    args = ap.parse_args(argv)
    if not args.key:
        print("Нужен ключ: --key или переменная окружения DGIS_API_KEY")
        return 1
    meta = run(args.key)
    print(f"Собрано {meta['total']} стоматологий за {meta['requests']} запросов → {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
