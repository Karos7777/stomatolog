import json
from pathlib import Path
from typing import Dict, List, Optional

from app.models import Clinic, ReviewAnalysis

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CLINICS_FILE = DATA_DIR / "clinics.json"
LEGACY_FILE = DATA_DIR / "legacy_audit.json"
ANALYSES_DIR = DATA_DIR / "review_analyses"


class ClinicRepository:
    def __init__(self, clinics_file: Path = CLINICS_FILE, analyses_dir: Path = ANALYSES_DIR):
        self.clinics_file = clinics_file
        self.analyses_dir = analyses_dir
        self.meta: Dict = {}
        self._clinics: List[Clinic] = []
        self.load()

    def load(self) -> None:
        raw = json.loads(self.clinics_file.read_text(encoding="utf-8"))
        self.meta = raw.get("meta", {})
        self._clinics = [Clinic(**c) for c in raw["clinics"]]

    def save(self) -> None:
        payload = {"meta": self.meta, "clinics": [c.model_dump(exclude_none=True) for c in self._clinics]}
        self.clinics_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def all(self) -> List[Clinic]:
        return self._clinics

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
        return path


def load_legacy_audit() -> Dict:
    return json.loads(LEGACY_FILE.read_text(encoding="utf-8"))


repo = ClinicRepository()
