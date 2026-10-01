from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field

class Review(BaseModel):
    author: str
    rating: int = Field(ge=1, le=5)
    date: str
    text: str

class Coordinates(BaseModel):
    lat: float
    lng: float

class Education(BaseModel):
    university: str
    graduation_year: int
    faculty: str
    degree: str
    residency: Optional[str] = None
    residency_years: Optional[str] = None
    internships: List[str] = []

class CertificationProof(BaseModel):
    title: str
    issuer: str
    year: int
    cert_id: str
    skills: List[str] = []

class IntegrityAudit(BaseModel):
    license_status: str
    diploma_verification: str
    commercial_certs_note: str
    red_flags: List[str] = []
    negative_feedback: List[str] = []
    safety_advice: str

class Dentist(BaseModel):
    id: str
    name: str
    title: str
    clinic: str
    photo_badge: str = "🦷"
    photo_url: Optional[str] = None
    specializations: List[str]
    services: Dict[str, int]
    comprehensive_prices: Dict[str, Dict[str, int]] = {}
    education: Optional[Education] = None
    certifications: List[CertificationProof] = []
    audit: Optional[IntegrityAudit] = None
    equipment: List[str] = []
    languages: List[str] = ["Кыргызча", "Русский"]
    rating: float
    reviews_count: int
    experience_years: int
    district: str
    address: str
    coordinates: Coordinates
    phone: str
    whatsapp: str
    gis_url: str
    website: Optional[str] = None
    working_hours: str
    is_24_7: bool = False
    price_level: str  # "эконом", "комфорт", "премиум"
    badges: List[str] = []
    description: str
    sample_reviews: List[Review] = []

class SmartMatchRequest(BaseModel):
    problem: str
    district: Optional[str] = None
    price_level: Optional[str] = None
    priority: Optional[str] = "reputation"

class MatchResult(BaseModel):
    dentist: Dentist
    score: float
    reasons: List[str]
    bayesian_rating: float

class ReviewCreate(BaseModel):
    author: str
    rating: int = Field(ge=1, le=5)
    text: str
