from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from collections import Counter

from app import app_version
from app.database import load_legacy_audit, repo
from app.importers import parse_reviews
from app.matching import TOPICS, coverage, detect_topics, match
from app.models import (EVIDENCE_LEVELS, Clinic, CredentialCheckRequest, CredentialVerdict,
                        MatchRequest, ReviewAnalysis, ReviewAnalysisRequest)
from app.scoring import WEIGHTS, city_prior, rank
from app.verification.credentials import CLAIM_TYPES, check_credential
from app.verification.issuers import VERIFY_LINKS
from app.verification.doctors import check_text
from app.verification.licenses import load_registry
from app.verdict import verdict as clinic_verdict
from app.database import distance_m
from app.verification.reviews import REFERENCES, analyze_reviews

BASE_DIR = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = BASE_DIR / "examples"

app = FastAPI(
    title="DentBishkek — проверка без иллюзий",
    description="Рейтинг стоматологий Бишкека с доказательствами: откуда каждая цифра, где накрутка, что подтверждено.",
    version="2.0.0",
)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.middleware("http")
async def revalidate_static(request: Request, call_next):
    """Браузер не должен держать старые app.js/style.css после обновления программы."""
    response = await call_next(request)
    if request.url.path.startswith("/static/") or request.url.path == "/":
        response.headers["Cache-Control"] = "no-cache"
    return response


def asset_version() -> str:
    """Меняется при любом изменении статики — ссылки вида app.js?v=… не берутся из старого кэша."""
    files = (BASE_DIR / "static").rglob("*")
    return str(int(max((f.stat().st_mtime for f in files if f.is_file()), default=0)))
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
APP_VERSION = app_version()


def _clinic_payload(clinic: Clinic) -> Dict:
    data = clinic.model_dump()
    data["gis_url"] = clinic.gis_url
    data["license"]["label"] = clinic.license.label
    data["all_sources"] = [s.model_dump() for s in clinic.all_sources()]
    return data


def _row(r: Dict, full: bool = False, need: Optional[str] = None) -> Dict:
    clinic: Clinic = r["clinic"]
    score = r["score"]
    out = {
        "verdict": clinic_verdict(clinic, score, need, r.get("coverage")),
        "doctors_verified": sum(1 for d in clinic.doctors if d.profile.get("documents_verified")),
        "doctors_total": len(clinic.doctors),
        "coordinates": clinic.coordinates,
        "position": r.get("position"),
        "id": clinic.id,
        "name": clinic.name,
        "address": clinic.address,
        "district": clinic.district,
        "is_24_7": clinic.is_24_7,
        "gis_url": clinic.gis_url,
        "website": clinic.website,
        "phones": clinic.phones,
        "services": clinic.services,
        "curated": clinic.curated,
        "multi_profile": clinic.multi_profile,
        "license": {"status": clinic.license.status, "label": clinic.license.label,
                    "holder": clinic.license.matches[0].holder if clinic.license.matches else None,
                    "number": clinic.license.matches[0].number if clinic.license.matches else None,
                    "unlicensed_at_address": bool(clinic.license.unlicensed_at_address)},
        "trust_index": score["trust_index"],
        "rating": score["rating"],
        "volume": score["volume"],
        "confidence": score["confidence"],
        "flags": score["flags"],
        "has_review_analysis": score["has_review_analysis"],
        "components": {k: {"score": v["score"]} for k, v in score["components"].items()},
    }
    for key in ("fit", "coverage", "reasons", "distance_km"):
        if key in r:
            out[key] = r[key]
    if full:
        out["clinic"] = _clinic_payload(clinic)
        out["components"] = score["components"]
        out["platforms"] = score["platforms"]
        out["doctors"] = [d.profile for d in clinic.doctors if d.profile]
    return out


_cache: Dict = {"version": None, "ranked": None}


def _ranked() -> List[Dict]:
    """Рейтинг считается один раз и пересчитывается, когда меняются данные или анализы отзывов."""
    analyses = repo.analyses()
    key = (repo.version, tuple(sorted((k, v.authenticity_index) for k, v in analyses.items())))
    if _cache["version"] != key:
        _cache["ranked"] = rank(repo.all(), analyses)
        _cache["version"] = key
    return _cache["ranked"]


@app.get("/", response_class=HTMLResponse)
async def home_page(request: Request):
    return templates.TemplateResponse(request=request, name="index.html",
                                      context={"topics": {k: v["label"] for k, v in TOPICS.items()},
                                               "v": asset_version(), "version": APP_VERSION})


@app.get("/api/meta")
def get_meta():
    ranked = _ranked()
    rated = [r for r in ranked if r["score"]["trust_index"] is not None]
    statuses = Counter(r["clinic"].license.status for r in ranked)
    big = [r for r in rated if (r["score"]["volume"] or 0) >= 100]
    return {
        **repo.meta,
        "version": APP_VERSION,
        "gis": repo.gis_meta,
        "registry": load_registry()["licenses"]["meta"],
        "clinics_total": len(ranked),
        "clinics_curated": sum(1 for r in ranked if r["clinic"].curated),
        "clinics_ranked": len(rated),
        "license_statuses": dict(statuses),
        "licenses_found": statuses.get("verified", 0) + statuses.get("probable", 0) + statuses.get("address_match", 0),
        "unlicensed_at_address": sum(1 for r in ranked if r["clinic"].license.unlicensed_at_address),
        "with_review_analysis": sum(1 for r in ranked if r["score"]["has_review_analysis"]),
        "doctors": {"total": len(repo.doctors), "verified": sum(1 for d in repo.doctors if d["documents_verified"]),
                    "foreign": sum(1 for d in repo.doctors if d["foreign"]),
                    "fetched": repo.ydoc_meta.get("fetched")},
        "perfect_big": {"clinics_100plus": len(big), "with_5_0": sum(1 for r in big if r["score"]["rating"] >= 4.95)},
        "city_prior": city_prior(repo.all()),
        "weights": WEIGHTS,
        "topics": {k: v["label"] for k, v in TOPICS.items()},
    }


LICENSE_FILTERS = {
    "found": {"verified", "probable", "address_match", "state"},
    "problems": {"not_found", "name_other_address"},
}


@app.get("/api/clinics")
def list_clinics(q: Optional[str] = None, topic: Optional[str] = None, only_24_7: bool = False,
                 sort: str = "trust", dental_only: bool = True, min_volume: int = 0,
                 license: Optional[str] = None, limit: int = 50, offset: int = 0):
    rows = _ranked()
    if q:
        ql = q.lower().strip()
        rows = [r for r in rows if ql in " ".join([
            r["clinic"].name, r["clinic"].address, " ".join(r["clinic"].services),
            " ".join(d.name for d in r["clinic"].doctors), " ".join(r["clinic"].aliases)]).lower()]
    if topic and topic in TOPICS:
        rows = [r for r in rows if coverage(r["clinic"], [topic])["value"] > 0]
    if only_24_7:
        rows = [r for r in rows if r["clinic"].is_24_7]
    if dental_only:
        rows = [r for r in rows if not r["clinic"].multi_profile]
    if min_volume:
        rows = [r for r in rows if (r["score"]["volume"] or 0) >= min_volume]
    if license in LICENSE_FILTERS:
        rows = [r for r in rows if r["clinic"].license.status in LICENSE_FILTERS[license]]
    elif license == "unlicensed":
        rows = [r for r in rows if r["clinic"].license.unlicensed_at_address]
    keyfuncs = {
        "rating": lambda r: (r["score"]["rating"] is None, -(r["score"]["rating"] or 0), -(r["score"]["volume"] or 0)),
        "volume": lambda r: -(r["score"]["volume"] or 0),
        "authenticity": lambda r: -r["score"]["components"]["authenticity"]["score"],
    }
    if sort in keyfuncs:
        rows = sorted(rows, key=keyfuncs[sort])
    limit = max(1, min(limit, 600))
    return {"total": len(rows), "offset": offset,
            "items": [_row(r) for r in rows[offset:offset + limit]]}


@app.get("/api/clinics/{clinic_id}")
def get_clinic(clinic_id: str):
    for r in _ranked():
        if r["clinic"].id == clinic_id:
            return _row(r, full=True)
    raise HTTPException(status_code=404, detail="Клиника не найдена")


@app.post("/api/match")
def match_clinics(req: MatchRequest):
    result = match(_ranked(), req.problem, req.need_24_7)
    order = {"низкая": 0, "средняя": 1, "высокая": 2}
    if req.min_confidence != "any":
        result["results"] = [r for r in result["results"]
                             if order[r["score"]["confidence"]] >= order[req.min_confidence]]
    return {"topics": result["topics"], "need_24_7": result["need_24_7"],
            "results": [_row(r) for r in result["results"]]}


@app.post("/api/analyze/reviews", response_model=ReviewAnalysis)
def analyze(req: ReviewAnalysisRequest):
    reviews = list(req.reviews)
    if req.raw:
        try:
            reviews += parse_reviews(req.raw, req.format)
        except Exception as exc:  # noqa: BLE001 — показываем пользователю, что не так с файлом
            raise HTTPException(status_code=400, detail=f"Не удалось разобрать отзывы: {exc}")
    if not reviews:
        raise HTTPException(status_code=400, detail="Нет отзывов для анализа")
    return analyze_reviews(reviews, req.aggregate)


@app.post("/api/analyze/credential", response_model=CredentialVerdict)
def analyze_credential(req: CredentialCheckRequest):
    return check_credential(req)


@app.get("/api/methodology")
def methodology():
    return {
        "weights": WEIGHTS,
        "review_references": REFERENCES,
        "evidence_levels": EVIDENCE_LEVELS,
        "claim_types": {k: {"label": v["label"], "proves": v["proves"], "does_not_prove": v["does_not_prove"],
                            "weight": v["weight"]} for k, v in CLAIM_TYPES.items()},
        "verify_links": VERIFY_LINKS,
        "today": date.today().isoformat(),
    }


@app.get("/api/legacy-audit")
def legacy_audit():
    return load_legacy_audit()


@app.get("/api/examples/{name}", response_class=PlainTextResponse)
def example(name: str):
    allowed = {"organic": "synthetic_organic_reviews.csv", "boosted": "synthetic_boosted_reviews.csv"}
    if name not in allowed:
        raise HTTPException(status_code=404, detail="Пример не найден")
    return (EXAMPLES_DIR / allowed[name]).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Простой режим: подбор, врачи, проверки в один клик
# ---------------------------------------------------------------------------

VERDICT_ORDER = {"good": 0, "ok": 1, "bad": 2}


# Что делает клинику сильнее именно под задачу: профиль в лицензии, оборудование, профильный врач с дипломом
NEED_EVIDENCE = {
    "implant": {"scope": "хирургия", "services": ("кт зубов", "клкт"), "doctor": ("имплантолог", "хирург")},
    "extraction": {"scope": "хирургия", "services": ("кт зубов", "клкт", "оптг"), "doctor": ("хирург",)},
    "ortho": {"scope": "ортодонтия (брекеты)", "services": ("цифровая",), "doctor": ("ортодонт",)},
    "kids": {"scope": None, "services": ("седация для детей", "микроскопом детям"), "doctor": ("детский",)},
    "sedation": {"scope": "анестезия/наркоз", "services": (), "doctor": ("анестезиолог",)},
    "endo": {"scope": None, "services": ("микроскоп",), "doctor": ("эндодонт", "терапевт")},
    "prosthetics": {"scope": "ортопедия (коронки, протезы)", "services": ("цифровая",), "doctor": ("ортопед",)},
    "caries": {"scope": None, "services": ("микроскоп",), "doctor": ("терапевт", "эндодонт")},
    "hygiene": {"scope": None, "services": (), "doctor": ("гигиенист", "пародонтолог")},
}


def specialist_bonus(clinic: Clinic, need: Optional[str]) -> tuple:
    rule = NEED_EVIDENCE.get(need or "")
    if not rule:
        return 0.0, []
    bonus, why = 0.0, []
    if rule["scope"] and rule["scope"] in clinic.license.scope and clinic.license.status in ("verified", "probable", "address_match"):
        bonus += 4
        why.append(f"в лицензии есть «{rule['scope']}»")
    services = " ".join(clinic.services).lower()
    found = [x for x in rule["services"] if x in services]
    if found:
        bonus += 2
        why.append("есть " + ", ".join(found))
    docs = [d for d in clinic.doctors if d.profile.get("documents_verified")
            and any(k in " ".join(d.profile.get("specialties", [])).lower() for k in rule["doctor"])]
    if docs:
        bonus += 5
        why.append("профильный врач с проверенным дипломом: " + ", ".join(d.name for d in docs[:2]))
    return bonus, why


class RecommendRequest(BaseModel):
    need: Optional[str] = None
    problem: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    radius_km: float = 5.0
    verified_doctors: bool = False
    limit: int = 5


@app.post("/api/recommend")
def recommend(req: RecommendRequest):
    topics = [req.need] if req.need in TOPICS else detect_topics(req.problem or "")
    need = topics[0] if topics else None
    need_24_7 = any(TOPICS[t].get("needs_24_7") for t in topics)
    here = {"lat": req.lat, "lng": req.lng} if req.lat is not None and req.lng is not None else None
    rows = []
    for r in _ranked():
        c, score = r["clinic"], r["score"]
        if score["trust_index"] is None or (c.multi_profile and need != "kids"):
            continue
        if need_24_7 and not c.is_24_7:
            continue
        if req.verified_doctors and not any(d.profile.get("documents_verified") for d in c.doctors):
            continue
        dist = None
        if here and c.coordinates and c.coordinates.get("lat") is not None:
            dist = distance_m(here, c.coordinates) / 1000
            if dist > req.radius_km:
                continue
        cov = coverage(c, topics)
        if topics and cov["value"] == 0:
            continue
        bonus, why = specialist_bonus(c, need)
        cov = {**cov, "matched": cov["matched"] + why}
        item = {**r, "coverage": cov,
                "fit": round(score["trust_index"] * (0.6 + 0.4 * cov["value"]) + bonus, 1)}
        if dist is not None:
            item["distance_km"] = round(dist, 1)
        row = _row(item, need=need)
        rows.append(row)
    rows.sort(key=lambda x: (VERDICT_ORDER[x["verdict"]["level"]], -x["fit"]))
    counts = {k: sum(1 for x in rows if x["verdict"]["level"] == k) for k in VERDICT_ORDER}
    return {"need": need, "need_label": TOPICS[need]["label"] if need else None, "need_24_7": need_24_7,
            "total": len(rows), "counts": counts, "results": rows[:max(1, min(req.limit, 20))]}


def _doctor_rows() -> List[Dict]:
    return repo.doctors


@app.get("/api/doctors")
def list_doctors(q: Optional[str] = None, specialty: Optional[str] = None, verified: bool = False,
                 foreign: bool = False, sort: str = "trust", limit: int = 30, offset: int = 0):
    docs = _doctor_rows()
    stats = {"total": len(docs), "verified": sum(1 for d in docs if d["documents_verified"]),
             "foreign": sum(1 for d in docs if d["foreign"]),
             "foreign_verified": sum(1 for d in docs if d["foreign_verified"]),
             "linked": sum(1 for d in docs if d.get("clinics")), "fetched": repo.ydoc_meta.get("fetched")}
    if q:
        ql = q.lower().strip()
        docs = [d for d in docs if ql in " ".join([d["name"] or "", " ".join(d["specialties"]),
                                                    " ".join(c["clinic_name"] for c in d.get("clinics", [])),
                                                    " ".join(w.get("name") or "" for w in d["workplaces"]),
                                                    " ".join(e.get("institution") or "" for e in d["education"])]).lower()]
    if specialty:
        docs = [d for d in docs if any(specialty.lower() in s.lower() for s in d["specialties"])]
    if verified:
        docs = [d for d in docs if d["documents_verified"]]
    if foreign:
        docs = [d for d in docs if d["foreign"]]
    keys = {
        "experience": lambda d: -(d["experience_years"] or 0),
        "reviews": lambda d: -(d["reviews"]["count"] or 0),
        "name": lambda d: d["name"] or "",
        "trust": lambda d: (not d["documents_verified"], bool(d["red_flags"]), not d["education"],
                            -(d["reviews"]["count"] or 0), -(d["experience_years"] or 0)),
    }
    docs = sorted(docs, key=keys.get(sort, keys["trust"]))
    specialties = sorted({s for d in _doctor_rows() for s in d["specialties"]})
    return {"total": len(docs), "stats": stats, "specialties": specialties, "items": docs[offset:offset + min(limit, 200)]}


@app.get("/api/doctors/{doctor_id}")
def get_doctor(doctor_id: str):
    for d in _doctor_rows():
        if d["id"] == doctor_id:
            return d
    raise HTTPException(status_code=404, detail="Врач не найден")


@app.get("/api/search")
def search(q: str = ""):
    ql = q.lower().strip()
    if len(ql) < 2:
        return {"clinics": [], "doctors": []}
    clinics = [{"id": c.id, "name": c.name, "address": c.address} for c in repo.all()
               if ql in (c.name + " " + " ".join(c.aliases) + " " + c.address).lower()][:12]
    doctors = [{"id": d["id"], "name": d["name"], "specialties": d["specialties"][:2],
                "clinic": (d.get("clinics") or [{}])[0].get("clinic_name")}
               for d in _doctor_rows() if d["name"] and ql in d["name"].lower()][:12]
    return {"clinics": clinics, "doctors": doctors}


@app.get("/api/check/reviews/{clinic_id}")
def check_reviews(clinic_id: str):
    """Проверка отзывов клиники в один клик — по всему, что известно без копирования текстов."""
    r = next((x for x in _ranked() if x["clinic"].id == clinic_id), None)
    if not r:
        raise HTTPException(status_code=404, detail="Клиника не найдена")
    c, score = r["clinic"], r["score"]
    auth = score["components"]["authenticity"]
    v = clinic_verdict(c, score)
    reviews_check = v["checks"][1]
    points = []
    gis = score["platforms"].get("2gis")
    if gis:
        texts = next((o.reviews_count for o in reversed(c.ratings) if o.platform == "2gis" and o.reviews_count), None)
        points.append(f"2ГИС: {gis['rating']:g}★, оценок {gis['volume']}" + (f", из них с текстом {texts}" if texts else "") + ".")
    ydoc = next((o for o in c.ratings if o.platform == "ydoc"), None)
    if ydoc:
        points.append(f"YDoc: {ydoc.rating:g}★ по {ydoc.reviews_count} отзывам о врачах клиники. {ydoc.note}.")
    else:
        points.append("На YDoc отзывов о врачах этой клиники нет — сравнить не с чем.")
    points += [x for x in auth["reasons"] if not x.startswith("Тексты отзывов не анализировались")]
    hist = [o for o in c.ratings if o.platform == "2gis" and o.source.via == "platform_api"]
    if len(hist) < 3:
        points.append("История рейтинга пока короткая: скачки числа оценок станут видны после нескольких обновлений "
                      "(python -m tools.crawl_2gis раз в 2–4 недели).")
    return {"clinic": {"id": c.id, "name": c.name, "address": c.address, "gis_url": c.gis_url,
                       "gis_reviews_url": (c.gis_url + "/tab/reviews") if c.gis_url else None},
            "status": reviews_check["status"], "title": reviews_check["title"], "detail": reviews_check["detail"],
            "points": points, "authenticity_score": auth["score"], "source": auth["source"]}


class TextCheckRequest(BaseModel):
    text: str


@app.post("/api/check/text")
def check_free_text(req: TextCheckRequest):
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="Вставьте текст")
    return check_text(req.text)
