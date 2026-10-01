import json
from pathlib import Path
from typing import List, Optional
from datetime import datetime
from app.models import Dentist, Review, ReviewCreate

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "dentists.json"

class DentistDatabase:
    def __init__(self, filepath: Path = DATA_FILE):
        self.filepath = filepath
        self._dentists: List[Dentist] = []
        self.load()

    def load(self):
        if not self.filepath.exists():
            self._dentists = []
            return
        with open(self.filepath, "r", encoding="utf-8") as f:
            raw_data = json.load(f)
            self._dentists = [Dentist(**item) for item in raw_data]

    def save(self):
        with open(self.filepath, "w", encoding="utf-8") as f:
            raw = [d.model_dump() for d in self._dentists]
            json.dump(raw, f, ensure_ascii=False, indent=2)

    def get_all(self) -> List[Dentist]:
        return self._dentists

    def get_by_id(self, dentist_id: str) -> Optional[Dentist]:
        for d in self._dentists:
            if d.id == dentist_id:
                return d
        return None

    def search_and_filter(
        self,
        query: Optional[str] = None,
        specialization: Optional[str] = None,
        district: Optional[str] = None,
        price_level: Optional[str] = None,
        min_rating: Optional[float] = None,
        only_24_7: bool = False
    ) -> List[Dentist]:
        results = self._dentists

        if query:
            q = query.lower().strip()
            results = [
                d for d in results
                if q in d.name.lower()
                or q in d.clinic.lower()
                or q in d.address.lower()
                or q in d.description.lower()
                or any(q in s.lower() for s in d.specializations)
                or any(q in s.lower() for s in d.services.keys())
            ]

        if specialization and specialization != "Все":
            s_low = specialization.lower()
            results = [
                d for d in results
                if any(s_low in spec.lower() for spec in d.specializations)
                or any(s_low in s.lower() for s in d.services.keys())
            ]

        if district and district != "Все":
            d_low = district.lower()
            results = [d for d in results if d_low in d.district.lower()]

        if price_level and price_level != "Все":
            results = [d for d in results if d.price_level.lower() == price_level.lower()]

        if min_rating:
            results = [d for d in results if d.rating >= min_rating]

        if only_24_7:
            results = [d for d in results if d.is_24_7]

        return results

    def add_review(self, dentist_id: str, review_in: ReviewCreate) -> Optional[Dentist]:
        dentist = self.get_by_id(dentist_id)
        if not dentist:
            return None

        new_review = Review(
            author=review_in.author,
            rating=review_in.rating,
            date=datetime.now().strftime("%d.%m.%Y"),
            text=review_in.text
        )

        dentist.sample_reviews.insert(0, new_review)
        # Update rating & reviews count
        total_rating = (dentist.rating * dentist.reviews_count) + review_in.rating
        dentist.reviews_count += 1
        dentist.rating = round(total_rating / dentist.reviews_count, 2)

        self.save()
        return dentist

db = DentistDatabase()
