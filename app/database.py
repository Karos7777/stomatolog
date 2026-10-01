import json
import math
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from app.models import (Clinic, CredentialClaim, CredentialEvidence, Doctor, LicenseInfo, RatingObservation,
                        ReviewAnalysis, Source)
from app.verification.doctors import analyze_doctor
from app.verification.licenses import check_clinic, load_registry, names_similarity

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CLINICS_FILE = DATA_DIR / "clinics.json"
GIS_FILE = DATA_DIR / "gis_bishkek.json"
YDOC_FILE = DATA_DIR / "ydoc_doctors.json"
LEGACY_FILE = DATA_DIR / "legacy_audit.json"
ANALYSES_DIR = DATA_DIR / "review_analyses"

_MULTI = re.compile(r"медицинск|многопрофил|педиатр|детская клиника|семейн[а-я]* клиник", re.I)


def is_multi_profile(name: str) -> bool:
    ext = name.split(",", 1)[1] if "," in name else ""
    return bool(_MULTI.search(ext)) and "стомат" not in ext.lower()


def gis_observations(item: Dict) -> List[RatingObservation]:
    url = f"https://2gis.kg/bishkek/firm/{item['id']}"
    return [RatingObservation(platform="2gis", rating=h["rating"], ratings_count=h.get("ratings_count"),
                              reviews_count=h.get("reviews_count"),
                              source=Source(url=url, observed=h["date"], via="platform_api", title="2GIS Places API"))
            for h in item.get("history", []) if h.get("rating") is not None]


def _license_for(clinic: Clinic) -> LicenseInfo:
    result = check_clinic([clinic.name, clinic.legal_name or ""] + clinic.aliases, clinic.address,
                          clinic.services, [d.name for d in clinic.doctors], clinic.living_area)
    meta = load_registry()["licenses"]["meta"]
    src = None
    if meta.get("source_file"):
        src = Source(url=meta["source_file"], observed=meta.get("downloaded", ""), via="official_registry",
                     title=f"Реестр лицензий МЗ КР (на {meta.get('as_of')})")
    return LicenseInfo(method="auto", source=src, **result)


def distance_m(a: Dict, b: Dict) -> float:
    lat1, lng1, lat2, lng2 = map(math.radians, (a["lat"], a["lng"], b["lat"], b["lng"]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 6371000 * 2 * math.asin(math.sqrt(h))


def _lpu_brand(name: Optional[str]) -> str:
    m = re.search(r"«([^»]+)»", name or "")
    return m.group(1) if m else (name or "")


def link_workplace(workplace: Dict, clinics: List[Clinic]) -> Tuple[Optional[Clinic], Optional[str]]:
    """Клиника 2ГИС для места работы врача на YDoc: рядом (≤150 м) и с похожим названием."""
    if workplace.get("lat") is None or workplace.get("lng") is None:
        return None, None
    point = {"lat": workplace["lat"], "lng": workplace["lng"]}
    near = [(distance_m(point, c.coordinates), c) for c in clinics
            if c.coordinates and c.coordinates.get("lat") is not None]
    near = [(d, c) for d, c in near if d <= 150]
    if not near:
        return None, None
    brand = _lpu_brand(workplace.get("name"))
    scored = [(names_similarity([brand], [c.name] + c.aliases), -d, c) for d, c in near]
    best = max(scored, key=lambda x: (x[0], x[1]))
    if best[0] >= 1:
        return best[2], "название и адрес"
    very_close = [c for d, c in near if d <= 25]
    if len(very_close) == 1:
        return very_close[0], "только адрес"
    return None, None


class ClinicRepository:
    def __init__(self, clinics_file: Path = CLINICS_FILE, analyses_dir: Path = ANALYSES_DIR,
                 gis_file: Optional[Path] = GIS_FILE, ydoc_file: Optional[Path] = YDOC_FILE):
        self.clinics_file = clinics_file
        self.analyses_dir = analyses_dir
        self.gis_file = gis_file
        self.ydoc_file = ydoc_file
        self.doctors: List[Dict] = []
        self.ydoc_meta: Dict = {}
        self.meta: Dict = {}
        self.gis_meta: Dict = {}
        self._curated_raw: List[Dict] = []
        self._clinics: List[Clinic] = []
        self.version = 0
        self.load()

    def load(self) -> None:
        raw = json.loads(self.clinics_file.read_text(encoding="utf-8"))
        self.meta = raw.get("meta", {})
        self._curated_raw = raw["clinics"]
        curated = [Clinic(**c) for c in raw["clinics"]]
        gis_items: Dict[str, Dict] = {}
        if self.gis_file and self.gis_file.exists():
            gis = json.loads(self.gis_file.read_text(encoding="utf-8"))
            self.gis_meta = gis.get("meta", {})
            gis_items = {it["id"]: it for it in gis["items"]}

        linked = set()
        for c in curated:
            item = gis_items.get(c.gis_firm_id or "")
            if not item:
                continue
            linked.add(item["id"])
            known = {(o.source.via, o.source.observed) for o in c.ratings}
            c.ratings += [o for o in gis_observations(item) if (o.source.via, o.source.observed) not in known]
            c.address = item["address"] + (f" ({item['address_comment']})" if item.get("address_comment") else "")
            c.coordinates = item.get("point") or c.coordinates
            c.is_24_7 = c.is_24_7 or item.get("is_24_7", False)
            c.multi_profile = is_multi_profile(item["name"])
            c.branches = c.branches or item.get("branch_count")
            c.district = item.get("district") or c.district
            c.living_area = item.get("living_area")
            if item.get("services"):
                c.services = item["services"]
                c.services_source = Source(url=f"https://2gis.kg/bishkek/firm/{item['id']}", via="platform_api",
                                           observed=self.gis_meta.get("fetched", ""), title="Услуги в 2ГИС")
            c.awards = [a for a in c.awards if a.get("source") != "2gis"] + [
                {"title": a, "confidence": "высокая", "note": "Премия 2ГИС (по голосованию пользователей)", "source": "2gis"}
                for a in item.get("awards", [])]

        auto = []
        for item in gis_items.values():
            if item["id"] in linked or item.get("rating") is None and not item.get("history"):
                continue
            url = f"https://2gis.kg/bishkek/firm/{item['id']}"
            api_src = Source(url=url, observed=self.gis_meta.get("fetched", ""), via="platform_api",
                             title="2GIS Places API")
            auto.append(Clinic(
                id=f"2gis-{item['id']}", name=item["brand"] or item["name"], address=item["address"] or "",
                gis_firm_id=item["id"], branches=item.get("branch_count"), is_24_7=item.get("is_24_7", False),
                district=item.get("district"), living_area=item.get("living_area"),
                services=item.get("services") or item.get("rubrics", []),
                services_source=api_src if (item.get("services") or item.get("rubrics")) else None,
                awards=[{"title": a, "confidence": "высокая", "note": "Премия 2ГИС (по голосованию пользователей)",
                         "source": "2gis"} for a in item.get("awards", [])],
                ratings=gis_observations(item), coordinates=item.get("point"), sources=[api_src],
                multi_profile=is_multi_profile(item["name"]), curated=False,
                notes=[f"Карточка собрана автоматически из 2GIS API: {item['name']}."]))

        clinics = curated + auto
        self._attach_ydoc(clinics)
        for c in clinics:
            if c.license.method != "manual":
                c.license = _license_for(c)
        self._clinics = clinics
        self.version += 1

    def _attach_ydoc(self, clinics: List[Clinic]) -> None:
        """Врачи с YDoc: разбор анкеты, привязка к клинике, подтверждённые отзывы как вторая площадка."""
        self.doctors = []
        if not self.ydoc_file or not self.ydoc_file.exists():
            return
        raw = json.loads(self.ydoc_file.read_text(encoding="utf-8"))
        self.ydoc_meta = raw.get("meta", {})
        fetched = self.ydoc_meta.get("fetched", "")
        reviews_by_clinic: Dict[str, Dict[str, Dict]] = {}
        for doc in raw.get("doctors", []):
            if not doc.get("name"):
                continue
            a = analyze_doctor(doc)
            links = []
            for w in a["workplaces"]:
                clinic, how = link_workplace(w, clinics)
                if clinic and clinic.id not in [l["clinic_id"] for l in links]:
                    links.append({"clinic_id": clinic.id, "clinic_name": clinic.name,
                                  "clinic_address": clinic.address, "how": how})
                    self._add_doctor(clinic, a, fetched)
                    for r in doc.get("reviews", []):
                        reviews_by_clinic.setdefault(clinic.id, {})[r["id"]] = r
            a["clinics"] = links
            self.doctors.append(a)
        by_id = {c.id: c for c in clinics}
        for cid, reviews in reviews_by_clinic.items():
            rated = [r["rating"] for r in reviews.values() if r.get("rating")]
            if len(rated) < 3:
                continue
            confirmed = sum(1 for r in reviews.values() if r.get("verified"))
            by_id[cid].ratings.append(RatingObservation(
                platform="ydoc", rating=round(sum(rated) / len(rated), 2), reviews_count=len(rated),
                source=Source(url="https://ydoc.kg/bishkek/stomatolog/", observed=fetched, via="platform_page",
                              title="YDoc: отзывы о врачах клиники"),
                note=f"{confirmed} из {len(rated)} отзывов YDoc подтвердил записью на приём или звонком"))

    @staticmethod
    def _add_doctor(clinic: Clinic, a: Dict, fetched: str) -> None:
        src = Source(url=a["url"], observed=fetched, via="platform_page", title="YDoc: анкета врача")
        surname = (a["name"] or "").split()[0].lower() if a.get("name") else ""
        existing = next((d for d in clinic.doctors if d.name.split()[0].lower() == surname), None)
        claims = [CredentialClaim(title=e["title"], kind=e["claim_type"], issuer=e.get("institution"),
                                  year=e.get("year"),
                                  evidence=CredentialEvidence(level=e["evidence_level"], source=src))
                  for e in a["education"]]
        if existing:
            existing.profile = a
            existing.claims += claims
            existing.sources.append(src)
            return
        clinic.doctors.append(Doctor(name=a["name"], role=", ".join(a["specialties"]) or None,
                                     graduation_year=a["graduation_year"],
                                     experience_years_claimed=a["experience_years"],
                                     claims=claims, sources=[src], profile=a))

    def save(self) -> None:
        """Сохраняет курируемые клиники. Пишем только то, что меняют инструменты (наблюдения рейтинга
        и координаты); врачи с YDoc, лицензии и данные 2ГИС пересобираются при загрузке."""
        by_id = {c.id: c for c in self._clinics if c.curated}
        out = []
        for raw in self._curated_raw:
            c = by_id.get(raw["id"])
            d = dict(raw)
            if c is not None:
                d["ratings"] = [o.model_dump(exclude_none=True) for o in c.ratings
                                if o.platform != "ydoc" and not (o.source.via == "platform_api" and self._from_gis(c, o))]
                if c.coordinates:
                    d["coordinates"] = c.coordinates
            out.append(d)
        payload = {"meta": self.meta, "clinics": out}
        self.clinics_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _from_gis(self, clinic: Clinic, obs: RatingObservation) -> bool:
        if not self.gis_file or not self.gis_file.exists():
            return False
        return obs.source.observed in self._gis_dates(clinic.gis_firm_id)

    def _gis_dates(self, firm_id: Optional[str]) -> set:
        gis = json.loads(self.gis_file.read_text(encoding="utf-8"))
        item = next((i for i in gis["items"] if i["id"] == firm_id), None)
        return {h["date"] for h in item.get("history", [])} if item else set()

    def all(self) -> List[Clinic]:
        return self._clinics

    def curated(self) -> List[Clinic]:
        return [c for c in self._clinics if c.curated]

    def get(self, clinic_id: str) -> Optional[Clinic]:
        return next((c for c in self._clinics if c.id == clinic_id), None)

    def analyses(self) -> Dict[str, ReviewAnalysis]:
        """Результаты анализа отзывов, сохранённые tools/import_reviews.py."""
        out: Dict[str, ReviewAnalysis] = {}
        if not self.analyses_dir.exists():
            return out
        for f in self.analyses_dir.glob("*.json"):
            data = json.loads(f.read_text(encoding="utf-8"))
            out[f.stem] = ReviewAnalysis(**data["analysis"])
        return out

    def save_analysis(self, clinic_id: str, analysis: ReviewAnalysis, meta: Dict) -> Path:
        self.analyses_dir.mkdir(parents=True, exist_ok=True)
        path = self.analyses_dir / f"{clinic_id}.json"
        path.write_text(json.dumps({"meta": meta, "analysis": analysis.model_dump()}, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        self.version += 1
        return path


def load_legacy_audit() -> Dict:
    return json.loads(LEGACY_FILE.read_text(encoding="utf-8"))


repo = ClinicRepository()
