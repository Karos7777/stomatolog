from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from pathlib import Path
from typing import Optional, List

from app.models import Dentist, SmartMatchRequest, MatchResult, ReviewCreate
from app.database import db
from app.ranking import rank_dentists, calculate_mean_rating, calculate_bayesian_rating

BASE_DIR = Path(__file__).resolve().parent.parent

app = FastAPI(
    title="DentistFinder Bishkek",
    description="Интеллектуальная система подбора лучшего стоматолога в Бишкеке",
    version="1.0.0"
)

# Static and templates
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

@app.get("/", response_class=HTMLResponse)
async def home_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "districts": [
                "Все районы",
                "Центр / Первомайский",
                "Октябрьский / Южные мкрн",
                "7-й микрорайон",
                "Асанбай",
                "Свердловский / Восток-5",
                "Ленинский"
            ],
            "specializations": [
                "Все направления",
                "Терапия (Кариес / Пульпит)",
                "Ортодонтия (Брекеты / Элайнеры)",
                "Имплантация и хирургия",
                "Детская стоматология",
                "Виниры и эстетика",
                "Острая зубная боль (24/7)",
                "Профессиональная чистка зубов"
            ]
        }
    )

@app.get("/api/dentists")
def get_dentists(
    query: Optional[str] = None,
    specialization: Optional[str] = None,
    district: Optional[str] = None,
    price_level: Optional[str] = None,
    min_rating: Optional[float] = None,
    only_24_7: bool = False,
    sort_by: str = "bayesian"
):
    dentists = db.search_and_filter(
        query=query,
        specialization=specialization,
        district=district,
        price_level=price_level,
        min_rating=min_rating,
        only_24_7=only_24_7
    )

    global_mean = calculate_mean_rating(db.get_all())

    # Sorting
    if sort_by == "rating":
        dentists.sort(key=lambda x: x.rating, reverse=True)
    elif sort_by == "reviews":
        dentists.sort(key=lambda x: x.reviews_count, reverse=True)
    elif sort_by == "experience":
        dentists.sort(key=lambda x: x.experience_years, reverse=True)
    elif sort_by == "price_asc":
        order = {"эконом": 1, "комфорт": 2, "премиум": 3}
        dentists.sort(key=lambda x: order.get(x.price_level, 2))
    else:  # default bayesian weighted rating
        dentists.sort(key=lambda x: calculate_bayesian_rating(x, global_mean), reverse=True)

    # Attach bayesian rating to response
    result = []
    for d in dentists:
        d_dict = d.model_dump()
        d_dict["bayesian_rating"] = calculate_bayesian_rating(d, global_mean)
        result.append(d_dict)

    return result

@app.get("/api/dentists/{dentist_id}")
def get_dentist_detail(dentist_id: str):
    dentist = db.get_by_id(dentist_id)
    if not dentist:
        raise HTTPException(status_code=404, detail="Стоматолог или клиника не найдены")
    
    global_mean = calculate_mean_rating(db.get_all())
    d_dict = dentist.model_dump()
    d_dict["bayesian_rating"] = calculate_bayesian_rating(dentist, global_mean)
    return d_dict

@app.post("/api/smart-match", response_model=List[MatchResult])
def smart_match_dentist(req: SmartMatchRequest):
    all_dentists = db.get_all()
    ranked = rank_dentists(all_dentists, req)
    return ranked

@app.post("/api/dentists/{dentist_id}/reviews")
def add_dentist_review(dentist_id: str, review_in: ReviewCreate):
    updated = db.add_review(dentist_id, review_in)
    if not updated:
        raise HTTPException(status_code=404, detail="Стоматолог не найден")
    return {"message": "Отзыв успешно добавлен", "rating": updated.rating, "reviews_count": updated.reviews_count}

@app.get("/api/stats")
def get_statistics():
    all_dentists = db.get_all()
    if not all_dentists:
        return {}
    
    global_mean = calculate_mean_rating(all_dentists)
    top_doctor = max(all_dentists, key=lambda x: calculate_bayesian_rating(x, global_mean))
    
    return {
        "total_clinics": len(all_dentists),
        "total_reviews": sum(d.reviews_count for d in all_dentists),
        "average_rating": round(global_mean, 2),
        "top_doctor": {
            "name": top_doctor.name,
            "clinic": top_doctor.clinic,
            "rating": top_doctor.rating,
            "reviews_count": top_doctor.reviews_count,
            "bayesian_score": calculate_bayesian_rating(top_doctor, global_mean)
        }
    }
