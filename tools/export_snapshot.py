"""Снимок сайта одним HTML-файлом: открывается на телефоне без сервера и без ноутбука.

Данные считает тот же код, что и сайт (через API), поэтому цифры совпадают. Чего в снимке нет:
проверки вставленного текста (сертификат, тексты отзывов) и «рядом со мной» — для них нужен запущенный сайт.

    python -m tools.export_snapshot --out snapshot.html                # вставка в страницу Claude (Artifact)
    python -m tools.export_snapshot --out docs/index.html --standalone # обычная страница, например для GitHub Pages
"""
import argparse
import json
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from app.api import APP_VERSION, app

TEMPLATE = Path(__file__).with_name("snapshot_template.html")
NEEDS = ["caries", "emergency", "implant", "ortho", "kids", "extraction", "prosthetics", "hygiene", "sedation", "endo"]
PER_NEED = 20          # столько клиник отдаёт /api/recommend (потолок API)
DOCTORS_PER_NEED = 80  # столько лучших врачей по каждой задаче кладём в снимок

STANDALONE = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<style>
:root { color-scheme: light; padding-top: env(safe-area-inset-top, 0px); padding-bottom: env(safe-area-inset-bottom, 0px); }
body { margin: 0; font: 14px system-ui, sans-serif; }
[hidden] { display: none !important; }
</style>
</head>
<body>
%s
</body>
</html>
"""


def checks(verdict):
    return [[c["status"], c["title"], c.get("detail") or ""] for c in verdict["checks"]]


def clinic_row(r, doctors_by_clinic):
    names = [r["name"], r["address"], *doctors_by_clinic.get(r["id"], [])]
    return {
        "id": r["id"], "name": r["name"], "address": r["address"],
        "district": (r["district"] or "").replace(" район", ""),
        "position": r["position"], "rating": r["rating"], "volume": r["volume"],
        "trust": None if r["trust_index"] is None else round(r["trust_index"]),
        "level": r["verdict"]["level"], "checks": checks(r["verdict"]),
        "license": r["license"]["status"], "unlicensed": r["license"]["unlicensed_at_address"],
        "phone": (r["phones"] or [None])[0], "gis": r["gis_url"], "h24": r["is_24_7"],
        "doctors_verified": r["doctors_verified"], "doctors_total": r["doctors_total"],
        "multi": r["multi_profile"], "q": " ".join(names).lower(),
    }


def doctor_row(d):
    return {
        "id": d["id"], "name": d["name"], "url": d["url"], "specialties": d["specialties"],
        "experience": d["experience_years"], "verified": d["documents_verified"],
        "checked_documents": d["checked_documents"], "foreign": d["foreign"],
        "foreign_countries": d["foreign_countries"], "foreign_verified": d["foreign_verified"],
        "red_flags": d["red_flags"], "warnings": d["warnings"],
        "education": [{"kind": e.get("kind"), "institution": e.get("institution"), "year": e.get("year"),
                       "specialty": e.get("specialty"), "country": e.get("country_label"), "foreign": e["foreign"],
                       "confirmed": e["confirmed"], "hint": (e.get("how_to_verify") or [None])[0]}
                      for e in d["education"]],
        "clinics": [{"id": c["clinic_id"], "name": c["clinic_name"], "address": c.get("clinic_address")}
                    for c in d.get("clinics") or []],
        "workplaces": [w["name"] for w in d["workplaces"] if w.get("name")] if not d.get("clinics") else [],
        "reviews": {k: d["reviews"][k] for k in ("count", "mean", "verified")},
        "updated": d["profile_updated"],
    }


def doctor_rec_row(r):
    c = r["clinic"]
    return {
        "id": r["id"], "name": r["name"], "url": r["url"], "specialties": r["specialties"], "experience": r["experience"],
        "score": r["score"], "confidence": r["confidence"], "profile": r["profile_match"], "equipment": r["equipment"],
        "verified": r["documents_verified"], "foreign": r["foreign_countries"],
        "reasons": [[x["sign"], x["text"], x["basis"]] for x in r["reasons"]],
        "clinic": {"id": c["id"], "name": c["name"], "address": c["address"]} if c else None,
        "others": r["other_clinics"][:3],
    }


def build() -> dict:
    client = TestClient(app)
    get = lambda url, **kw: client.get(url, **kw).json()
    meta = get("/api/meta")

    docs = []
    while True:
        page = get("/api/doctors", params={"limit": 200, "offset": len(docs)})
        docs += page["items"]
        if len(docs) >= page["total"] or not page["items"]:
            break
    doctors_by_clinic = {}
    for d in docs:
        for c in d.get("clinics") or []:
            doctors_by_clinic.setdefault(c["clinic_id"], []).append((d["name"] or "").lower())

    clinics = get("/api/clinics", params={"limit": 600, "dental_only": False})["items"]
    rows = [clinic_row(r, doctors_by_clinic) for r in clinics]

    rec = {}
    for need in NEEDS:
        for verified in (False, True):
            res = client.post("/api/recommend", json={"need": need, "limit": PER_NEED, "verified_doctors": verified}).json()
            rec.setdefault(need, {})["1" if verified else "0"] = {
                "label": res["need_label"], "total": res["total"], "counts": res["counts"],
                "items": [{"id": x["id"], "level": x["verdict"]["level"], "checks": checks(x["verdict"])}
                          for x in res["results"]]}

    doctor_recs = {}
    for need in NEEDS:
        res = client.post("/api/recommend/doctors", json={"need": need, "limit": DOCTORS_PER_NEED}).json()
        doctor_recs[need] = {k: res[k] for k in ("label", "specialty_label", "equipment_label", "tips", "total", "with_profile")}
        doctor_recs[need]["items"] = [doctor_rec_row(r) for r in res["items"]]

    reviews = {r["id"]: get(f"/api/check/reviews/{r['id']}")["points"] for r in rows}
    return {
        "generated": date.today().isoformat(), "version": APP_VERSION,
        "meta": {"registry_as_of": meta["registry"]["as_of"], "gis_fetched": meta["gis"]["fetched"],
                 "clinics": len(rows), "license_statuses": meta["license_statuses"],
                 "unlicensed_at_address": meta["unlicensed_at_address"], "doctors": page["stats"],
                 "big_clinics": meta["perfect_big"]},
        "needs": NEEDS, "recommend": rec, "doctor_recs": doctor_recs, "clinics": rows, "reviews": reviews,
        "doctors": [doctor_row(d) for d in docs], "specialties": page["specialties"],
        "districts": sorted({r["district"] for r in rows if r["district"]}),
    }


def render(data: dict, standalone: bool = False) -> str:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    page = TEMPLATE.read_text(encoding="utf-8").replace("/*__DATA__*/", payload)
    return STANDALONE % page if standalone else page


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="snapshot.html")
    ap.add_argument("--standalone", action="store_true", help="добавить doctype и head — для обычного хостинга")
    args = ap.parse_args()
    data = build()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(data, args.standalone), encoding="utf-8")
    print(f"{out}: {out.stat().st_size / 1024:.0f} КБ, клиник {len(data['clinics'])}, врачей {len(data['doctors'])}")


if __name__ == "__main__":
    main()
