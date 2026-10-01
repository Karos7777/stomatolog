from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from collections import Counter

from app.database import load_legacy_audit, repo
from app.importers import parse_reviews
from app.matching import TOPICS, coverage, match
from app.models import (EVIDENCE_LEVELS, Clinic, CredentialCheckRequest, CredentialVerdict,
                        MatchRequest, ReviewAnalysis, ReviewAnalysisRequest)
from app.scoring import WEIGHTS, city_prior, rank
from app.verification.credentials import CLAIM_TYPES, check_credential
from app.verification.issuers import VERIFY_LINKS
from app.verification.licenses import load_registry
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


def _clinic_payload(clinic: Clinic) -> Dict:
    data = clinic.model_dump()
    data["gis_url"] = clinic.gis_url
    data["license"]["label"] = clinic.license.label
    data["all_sources"] = [s.model_dump() for s in clinic.all_sources()]
    return data


def _row(r: Dict, full: bool = False) -> Dict:
    clinic: Clinic = r["clinic"]
    score = r["score"]
    out = {
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
    for key in ("fit", "coverage", "reasons"):
        if key in r:
            out[key] = r[key]
    if full:
        out["clinic"] = _clinic_payload(clinic)
        out["components"] = score["components"]
        out["platforms"] = score["platforms"]
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
                                               "v": asset_version()})


@app.get("/api/meta")
def get_meta():
    ranked = _ranked()
    rated = [r for r in ranked if r["score"]["trust_index"] is not None]
    statuses = Counter(r["clinic"].license.status for r in ranked)
    big = [r for r in rated if (r["score"]["volume"] or 0) >= 100]
    return {
        **repo.meta,
        "gis": repo.gis_meta,
        "registry": load_registry()["licenses"]["meta"],
        "clinics_total": len(ranked),
        "clinics_curated": sum(1 for r in ranked if r["clinic"].curated),
        "clinics_ranked": len(rated),
        "license_statuses": dict(statuses),
        "licenses_found": statuses.get("verified", 0) + statuses.get("probable", 0) + statuses.get("address_match", 0),
        "unlicensed_at_address": sum(1 for r in ranked if r["clinic"].license.unlicensed_at_address),
        "with_review_analysis": sum(1 for r in ranked if r["score"]["has_review_analysis"]),
        "perfect_big": {"clinics_100plus": len(big), "with_5_0": sum(1 for r in big if r["score"]["rating"] >= 4.95)},
        "city_prior": city_prior(repo.all()),
        "weights": WEIGHTS,
        "topics": {k: v["label"] for k, v in TOPICS.items()},
    }


LICENSE_FILTERS = {
    "found": {"verified", "probable", "address_match"},
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
