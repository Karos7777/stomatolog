"""Модели данных.

Главный принцип: любой факт о клинике хранится вместе с источником (URL), датой и способом
получения. Факт без источника не показывается как подтверждённый.
"""
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Источники и уровни доказанности
# ---------------------------------------------------------------------------

# Как получено наблюдение. Чем выше в списке, тем надёжнее.
ObservedVia = Literal[
    "official_registry",    # госреестр (лицензии МЗ КР, Түндүк, реестр юрлиц)
    "platform_api",         # официальный API площадки (2ГИС Catalog API)
    "manual_check",         # человек открыл страницу и переписал значение
    "web_search_snippet",   # значение из поисковой выдачи (может быть устаревшим)
    "clinic_claim",         # заявление самой клиники (сайт, соцсети)
    "media",                # СМИ
]

# Уровень доказанности квалификации (от 0 до 4).
EVIDENCE_LEVELS = {
    0: "Нет данных",
    1: "Заявлено клиникой/врачом (не проверено)",
    2: "Документ предъявлен, но не сверен с эмитентом",
    3: "Подтверждено эмитентом (вуз, производитель, ассоциация)",
    4: "Подтверждено в государственном реестре",
}


class Source(BaseModel):
    url: str
    title: Optional[str] = None
    observed: str = Field(description="Дата наблюдения, YYYY-MM-DD")
    via: ObservedVia


class RatingObservation(BaseModel):
    platform: str                        # "2gis", "ydoc", "google", ...
    rating: float = Field(ge=0, le=5)
    ratings_count: Optional[int] = None  # число оценок (звёзд)
    reviews_count: Optional[int] = None  # число текстовых отзывов
    unconfirmed_count: Optional[int] = None  # 2ГИС: отзывы в разделе «Неподтверждённые»
    source: Source
    note: Optional[str] = None

    @property
    def volume(self) -> int:
        return self.ratings_count or self.reviews_count or 0


class CredentialEvidence(BaseModel):
    level: int = Field(ge=0, le=4)
    source: Optional[Source] = None
    note: Optional[str] = None


class CredentialClaim(BaseModel):
    """Утверждение о квалификации: диплом, ординатура, сертификат, курс, членство и т.д."""
    title: str
    kind: Optional[str] = None           # явный тип (см. CLAIM_TYPES), если по названию не определить
    issuer: Optional[str] = None
    year: Optional[int] = None
    document_id: Optional[str] = None
    evidence: CredentialEvidence = CredentialEvidence(level=0)


class Doctor(BaseModel):
    name: str
    role: Optional[str] = None
    graduation_year: Optional[int] = None
    experience_years_claimed: Optional[int] = None
    claims: List[CredentialClaim] = []
    sources: List[Source] = []


class LicenseInfo(BaseModel):
    status: Literal["verified", "not_found", "not_checked"] = "not_checked"
    number: Optional[str] = None
    scope: List[str] = []
    source: Optional[Source] = None


class Clinic(BaseModel):
    id: str
    name: str
    legal_name: Optional[str] = None
    inn: Optional[str] = None
    inn_source: Optional[Source] = None
    address: str
    district: Optional[str] = None
    branches: Optional[int] = None
    phones: List[str] = []
    website: Optional[str] = None
    gis_firm_id: Optional[str] = None
    links: Dict[str, str] = {}
    hours: Optional[str] = None
    is_24_7: bool = False
    services: List[str] = []             # из рубрик 2ГИС / сайта клиники
    services_source: Optional[Source] = None
    ratings: List[RatingObservation] = []
    doctors: List[Doctor] = []
    license: LicenseInfo = LicenseInfo()
    awards: List[Dict[str, str]] = []
    notes: List[str] = []
    sources: List[Source] = []
    coordinates: Optional[Dict[str, float]] = None

    @property
    def gis_url(self) -> Optional[str]:
        if self.gis_firm_id:
            return f"https://2gis.kg/bishkek/firm/{self.gis_firm_id}"
        return self.links.get("2gis")

    def all_sources(self) -> List[Source]:
        """Все источники, на которые опираются данные о клинике, без повторов."""
        candidates: List[Source] = list(self.sources)
        candidates += [s for s in (self.inn_source, self.services_source, self.license.source) if s]
        candidates += [o.source for o in self.ratings]
        for d in self.doctors:
            candidates += d.sources + [c.evidence.source for c in d.claims if c.evidence.source]
        seen, out = set(), []
        for s in candidates:
            if s.url not in seen:
                seen.add(s.url)
                out.append(s)
        return out


# ---------------------------------------------------------------------------
# Анализ отзывов
# ---------------------------------------------------------------------------

class ReviewInput(BaseModel):
    text: str = ""
    rating: Optional[int] = Field(default=None, ge=1, le=5)
    date: Optional[str] = None               # ISO, «12.03.2026» или «12 марта 2026»
    author: Optional[str] = None
    author_reviews_count: Optional[int] = None  # сколько всего отзывов у автора на площадке
    confirmed: Optional[bool] = None            # «Отзыв подтверждён» / «Неподтверждённый» в 2ГИС


class AggregateInput(BaseModel):
    platform: str = "2gis"
    rating: Optional[float] = None
    ratings_count: Optional[int] = None
    unconfirmed_count: Optional[int] = None
    other_platforms: List[RatingObservation] = []


class Signal(BaseModel):
    code: str
    title: str
    severity: Literal["ok", "info", "warning", "critical"]
    value: Optional[float] = None
    penalty: float = 0.0
    explanation: str
    evidence: List[str] = []
    reference: Optional[str] = None


class ReviewFlags(BaseModel):
    index: int
    author: Optional[str] = None
    date: Optional[str] = None
    rating: Optional[int] = None
    excerpt: str
    suspicion: float
    reasons: List[str]


class ReviewAnalysis(BaseModel):
    total: int
    analyzed_with_dates: int
    authenticity_index: float          # 0..100, 100 = признаков манипуляции нет
    verdict: Literal["organic", "some_signals", "strong_signals", "insufficient_data"]
    verdict_text: str
    confidence: Literal["высокая", "средняя", "низкая"]
    rating_distribution: Dict[str, int]
    raw_mean_rating: Optional[float] = None
    cleaned_mean_rating: Optional[float] = None
    cleaned_count: int = 0
    suspicious_count: int = 0
    signals: List[Signal]
    suspicious_reviews: List[ReviewFlags] = []


class ReviewAnalysisRequest(BaseModel):
    reviews: List[ReviewInput] = []
    raw: Optional[str] = None
    format: Literal["auto", "csv", "json", "text"] = "auto"
    aggregate: Optional[AggregateInput] = None


# ---------------------------------------------------------------------------
# Проверка сертификатов
# ---------------------------------------------------------------------------

class CredentialCheckRequest(BaseModel):
    title: str
    claim_type: Optional[str] = None
    issuer: Optional[str] = None
    year: Optional[int] = None
    document_id: Optional[str] = None
    holder_graduation_year: Optional[int] = None
    holder_experience_years: Optional[int] = None
    holder_specialty: Optional[str] = None
    evidence_level: int = Field(default=1, ge=0, le=4)


class CredentialVerdict(BaseModel):
    claim_type: str
    claim_type_label: str
    issuer_known: bool
    issuer_name: Optional[str] = None
    proves: str
    does_not_prove: str
    how_to_verify: List[str]
    verify_links: List[Dict[str, str]] = []
    red_flags: List[str]
    warnings: List[str]
    evidence_level: int
    evidence_label: str
    verdict: Literal["подтверждено", "правдоподобно, но не проверено", "сомнительно", "признаки подделки",
                     "не является квалификацией"]
    weight: float                       # вклад в оценку квалификации (0..1)


# ---------------------------------------------------------------------------
# Подбор
# ---------------------------------------------------------------------------

class MatchRequest(BaseModel):
    problem: str = ""
    need_24_7: bool = False
    min_confidence: Literal["any", "низкая", "средняя", "высокая"] = "any"
