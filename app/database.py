import json
import re
from pathlib import Path
from typing import Dict, List, Optional

from app.models import Clinic, LicenseInfo, RatingObservation, ReviewAnalysis, Source
from app.verification.licenses import check_clinic, load_registry

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CLINICS_FILE = DATA_DIR / "clinics.json"
GIS_FILE = DATA_DIR / "gis_bishkek.json"
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
                          clinic.services, [d.name for d in clinic.doctors])
    meta = load_registry()["licenses"]["meta"]
    src = None
    if meta.get("source_file"):
        src = Source(url=meta["source_file"], observed=meta.get("downloaded", ""), via="official_registry",
                     title=f"Реестр лицензий МЗ КР (на {meta.get('as_of')})")
    return LicenseInfo(method="auto", source=src, **result)


class ClinicRepository:
    def __init__(self, clinics_file: Path = CLINICS_FILE, analyses_dir: Path = ANALYSES_DIR,
                 gis_file: Optional[Path] = GIS_FILE):
        self.clinics_file = clinics_file
        self.analyses_dir = analyses_dir
        self.gis_file = gis_file
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
                services=item.get("rubrics", []), services_source=api_src if item.get("rubrics") else None,
                ratings=gis_observations(item), coordinates=item.get("point"), sources=[api_src],
                multi_profile=is_multi_profile(item["name"]), curated=False,
                notes=[f"Карточка собрана автоматически из 2GIS API: {item['name']}."]))

        clinics = curated + auto
        for c in clinics:
            if c.license.method != "manual":
                c.license = _license_for(c)
        self._clinics = clinics
        self.version += 1

    def save(self) -> None:
        """Сохраняет только курируемые клиники (автоматические пересобираются из gis_bishkek.json)."""
        by_id = {c.id: c for c in self._clinics if c.curated}
        out = []
        for raw in self._curated_raw:
            c = by_id.get(raw["id"])
            if c is None:
                continue
            d = c.model_dump(exclude_none=True, exclude={"curated", "multi_profile"})
            if c.license.method == "auto":
                d.pop("license", None)
            d["ratings"] = [o.model_dump(exclude_none=True) for o in c.ratings
                            if not (o.source.via == "platform_api" and o.source.title == "2GIS Places API"
                                    and self._from_gis(c, o))]
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
