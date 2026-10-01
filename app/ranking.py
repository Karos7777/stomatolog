from typing import List, Tuple
from app.models import Dentist, SmartMatchRequest, MatchResult

# Default minimum reviews threshold for Bayesian confidence
M_THRESHOLD = 50

def calculate_mean_rating(dentists: List[Dentist]) -> float:
    if not dentists:
        return 4.85
    total_reviews = sum(d.reviews_count for d in dentists)
    if total_reviews == 0:
        return 4.85
    weighted_sum = sum(d.rating * d.reviews_count for d in dentists)
    return weighted_sum / total_reviews

def calculate_bayesian_rating(dentist: Dentist, global_mean: float, m: int = M_THRESHOLD) -> float:
    v = dentist.reviews_count
    r = dentist.rating
    # Bayesian formula: (v / (v + m)) * r + (m / (v + m)) * C
    return round((v / (v + m)) * r + (m / (v + m)) * global_mean, 3)

# Problem keywords mapping with primary and secondary specializations
PROBLEM_KEYWORDS = {
    "кариес": {
        "primary": ["Терапия", "Лечение кариеса", "Лечение каналов под микроскопом"],
        "keywords": ["кариес", "пломб", "пульпит"]
    },
    "боль": {
        "primary": ["Острая зубная боль", "Срочное удаление", "Хирургия"],
        "keywords": ["боль", "флюс", "срочно", "ночь", "дежурн"]
    },
    "брекеты": {
        "primary": ["Ортодонтия", "Брекеты", "Элайнеры"],
        "keywords": ["брекет", "элайнер", "прикус", "выравнивание"]
    },
    "прикус": {
        "primary": ["Ортодонтия", "Брекеты", "Элайнеры", "Исправление прикуса"],
        "keywords": ["прикус", "ровн", "брекет", "элайнер"]
    },
    "имплант": {
        "primary": ["Имплантация", "Хирургия", "Костная пластика", "All-on-4 / All-on-6"],
        "keywords": ["имплант", "синус", "all-on"]
    },
    "удаление": {
        "primary": ["Хирургия", "Удаление зубов мудрости", "Удаление"],
        "keywords": ["удаление", "мудрост", "восьмерк"]
    },
    "дети": {
        "primary": ["Детская стоматология", "Адаптационный прием"],
        "keywords": ["детск", "ребенок", "молочн", "малыш"]
    },
    "ребенок": {
        "primary": ["Детская стоматология", "Адаптационный прием"],
        "keywords": ["детск", "ребенок", "молочн", "малыш"]
    },
    "виниры": {
        "primary": ["Виниры", "Художественная реставрация", "Цифровая ортопедия"],
        "keywords": ["венир", "винир", "эстетик", "улыбк", "реставрац"]
    },
    "отбеливание": {
        "primary": ["Отбеливание зубов", "Чистка Air Flow", "Профессиональная гигиена"],
        "keywords": ["отбеливан", "zoom", "чистк", "гигиен"]
    },
    "чистка": {
        "primary": ["Чистка Air Flow", "Профессиональная гигиена", "Терапия"],
        "keywords": ["чистк", "air flow", "камень", "налет"]
    },
    "коронка": {
        "primary": ["Ортопедия", "Протезирование", "Циркониевая коронка", "Виниры"],
        "keywords": ["коронк", "протез", "мост", "циркони"]
    }
}

def evaluate_match(dentist: Dentist, request: SmartMatchRequest, global_mean: float) -> MatchResult:
    score = 0.0
    reasons = []

    bayesian = calculate_bayesian_rating(dentist, global_mean)
    prob_clean = request.problem.lower().strip()

    # Find matched topic
    primary_specs = []
    topic_keywords = []

    for key, data in PROBLEM_KEYWORDS.items():
        if key in prob_clean or any(k in prob_clean for k in data["keywords"]):
            primary_specs.extend(data["primary"])
            topic_keywords.extend(data["keywords"])

    # 1. Specialization Match (0 to 45 pts)
    exact_primary_match = False
    for spec in dentist.specializations:
        if any(ps.lower() == spec.lower() for ps in primary_specs):
            exact_primary_match = True
            reasons.append(f"Профильная специализация: {spec}")
            break

    # Bonus if the doctor explicitly has the exact term in their specializations
    has_exact_searched_keyword = any(any(k in s.lower() for k in topic_keywords) for s in dentist.specializations)

    # Direct token-level query match (e.g. user typed 'брекеты' and doctor has 'Брекеты')
    query_tokens = [w for w in prob_clean.split() if len(w) > 3]
    has_direct_query_token = any(
        any(token in s.lower() for token in query_tokens) 
        for s in (dentist.specializations + [dentist.title, dentist.name])
    )

    # Exclude child-clinic boost for adult requests
    is_child_request = any(k in prob_clean for k in ["дет", "ребенок", "малыш"])
    is_child_clinic = "детск" in dentist.clinic.lower() or any("детск" in s.lower() for s in dentist.specializations)

    if exact_primary_match:
        score += 38.0
        # If doctor has direct match on the searched keyword
        if has_exact_searched_keyword:
            score += 5.0
        if has_direct_query_token:
            score += 4.0
    else:
        # Partial match in specializations
        if has_exact_searched_keyword:
            score += 26.0
            reasons.append("Смежное направление лечения в клинике")
        else:
            # Check services
            has_service = any(any(k in s.lower() for k in topic_keywords) for s in dentist.services.keys())
            if has_service:
                score += 20.0
                reasons.append("Услуга представлена в прайс-листе")
            else:
                score += 5.0

    if not is_child_request and is_child_clinic and not exact_primary_match:
        score -= 20.0  # Child clinic shouldn't take priority for adult issues

    # 2. Quality & Trust (Bayesian score: 0 to 25 pts)
    quality_pts = max(0.0, min(25.0, (bayesian - 4.6) * 62.5))
    score += quality_pts
    if dentist.reviews_count >= 300:
        reasons.append(f"Высокий рейтинг доверия: {dentist.rating} ({dentist.reviews_count} отзывов 2ГИС)")
    else:
        reasons.append(f"Рейтинг {dentist.rating} ({dentist.reviews_count} отзывов)")

    # 3. Doctor Experience (0 to 12 pts)
    exp_pts = min(12.0, dentist.experience_years * 0.75)
    score += exp_pts
    if dentist.experience_years >= 15:
        reasons.append(f"Большой практический опыт: {dentist.experience_years} лет")
    elif dentist.experience_years >= 10:
        reasons.append(f"Опыт специалиста: {dentist.experience_years} лет")

    # 4. District Match (0 to 10 pts)
    if request.district and request.district != "Все":
        req_d = request.district.lower()
        if req_d in dentist.district.lower():
            score += 10.0
            reasons.append(f"Клиника в вашем районе ({dentist.district})")
        elif "центр" in req_d and "центр" in dentist.district.lower():
            score += 8.0
            reasons.append("Удобная локация в Центре Бишкека")
        else:
            score += 2.0
    else:
        score += 8.0

    # 5. Budget Match (0 to 8 pts)
    if request.price_level and request.price_level != "Все":
        if request.price_level.lower() == dentist.price_level.lower():
            score += 8.0
            reasons.append(f"Подходящий ценовой сегмент ({dentist.price_level})")
        else:
            score += 3.0
    else:
        score += 6.0

    # 6. Priority modifier
    prio = request.priority or "reputation"
    if prio == "reputation":
        if dentist.rating >= 4.92:
            score += 6.0
            reasons.append("Входит в топ врачей Бишкека по рейтингу")
    elif prio == "price":
        if dentist.price_level == "эконом":
            score += 8.0
            reasons.append("Самая выгодная стоимость процедур")
        elif dentist.price_level == "комфорт":
            score += 4.0
    elif prio == "technology":
        tech_badges = [b for b in dentist.badges if any(k in b.lower() for k in ["микроскоп", "3d", "сканер", "cad/cam", "damon", "томограф"])]
        if tech_badges:
            score += 7.0
            reasons.append(f"Продвинутое оснащение: {tech_badges[0]}")
    elif prio == "proximity":
        if request.district and request.district.lower() in dentist.district.lower():
            score += 6.0

    # 7. Night / Emergency bonus
    if any(k in prob_clean for k in ["срочно", "ночь", "острая"]):
        if dentist.is_24_7:
            score += 25.0
            reasons.insert(0, "🚨 Работает круглосуточно 24/7 (срочный ночной прием)")
        else:
            score -= 15.0

    # Normalize final score between 40% and 99%
    final_score = min(99.0, max(40.0, round(score, 1)))

    return MatchResult(
        dentist=dentist,
        score=final_score,
        reasons=reasons,
        bayesian_rating=bayesian
    )

def rank_dentists(dentists: List[Dentist], request: SmartMatchRequest) -> List[MatchResult]:
    global_mean = calculate_mean_rating(dentists)
    results = [evaluate_match(d, request, global_mean) for d in dentists]
    # Sort descending by match score, then by bayesian rating
    results.sort(key=lambda x: (x.score, x.bayesian_rating), reverse=True)
    return results
