"""Индекс доверия клиники.

    Индекс = 50% рейтинг (с поправкой на объём) + 25% подлинность отзывов
           + 15% подтверждённая квалификация + 10% прозрачность

Каждая составляющая объясняется списком причин. Неизвестное не приравнивается к плохому:
клиника без данных о рейтинге не ранжируется, а попадает в группу «недостаточно данных».
"""
import math
from datetime import date
from statistics import median
from typing import Dict, List, Optional, Tuple

from app.models import Clinic, CredentialCheckRequest, RatingObservation, ReviewAnalysis
from app.verification.credentials import check_credential

WEIGHTS = {"rating": 0.50, "authenticity": 0.25, "credentials": 0.15, "transparency": 0.10}
PRIOR_STRENGTH = 25      # «виртуальные» оценки на уровне среднего по городу
RATING_SD = 0.9          # типичный разброс оценок одного пациента
Z_80 = 1.2816            # односторонняя нижняя граница 80%
FLOOR, CEIL = 3.8, 5.0   # шкала рейтинга → 0..100

VIA_RANK = {"official_registry": 5, "platform_api": 4, "manual_check": 3, "web_search_snippet": 2,
            "clinic_claim": 1, "media": 1}


def _platform_estimate(obs: List[RatingObservation]) -> Dict:
    """Консервативная оценка по одной площадке: при расхождении сводок берём меньшие значения."""
    best_via = max(VIA_RANK[o.source.via] for o in obs)
    trusted = [o for o in obs if VIA_RANK[o.source.via] == best_via]
    latest_date = max(o.source.observed for o in trusted)
    current = [o for o in trusted if o.source.observed == latest_date]
    rating = min(o.rating for o in current)
    with_ratings = [o.ratings_count for o in current if o.ratings_count]
    with_reviews = [o.reviews_count for o in current if o.reviews_count]
    volume = min(with_ratings) if with_ratings else (min(with_reviews) if with_reviews else 0)
    volumes = [o.volume for o in obs if o.volume]
    spread = (max(volumes) - min(volumes)) / max(volumes) if len(volumes) > 1 else 0.0
    ratings_spread = max(o.rating for o in obs) - min(o.rating for o in obs)
    unconfirmed = next((o.unconfirmed_count for o in current if o.unconfirmed_count is not None), None)
    return {"rating": rating, "volume": volume, "via": current[0].source.via, "observed": latest_date,
            "volume_spread": round(spread, 2), "rating_spread": round(ratings_spread, 2),
            "unconfirmed": unconfirmed, "n_obs": len(obs)}


def platform_estimates(clinic: Clinic) -> Dict[str, Dict]:
    by_platform: Dict[str, List[RatingObservation]] = {}
    for o in clinic.ratings:
        by_platform.setdefault(o.platform, []).append(o)
    return {p: _platform_estimate(obs) for p, obs in by_platform.items()}


def combined_rating(estimates: Dict[str, Dict]) -> Tuple[Optional[float], int]:
    total = sum(e["volume"] for e in estimates.values())
    if not estimates:
        return None, 0
    if total == 0:
        return round(sum(e["rating"] for e in estimates.values()) / len(estimates), 2), 0
    return round(sum(e["rating"] * e["volume"] for e in estimates.values()) / total, 3), total


def city_prior(clinics: List[Clinic]) -> float:
    num = den = 0.0
    for c in clinics:
        r, v = combined_rating(platform_estimates(c))
        if r is not None and v:
            num += r * v
            den += v
    return round(num / den, 3) if den else 4.6


def rating_component(rating: Optional[float], volume: int, prior: float) -> Dict:
    if rating is None:
        return {"score": None, "bayesian": None, "lower_bound": None,
                "reasons": ["Нет данных о рейтинге — клиника не ранжируется."]}
    v = max(volume, 0)
    bayes = (v * rating + PRIOR_STRENGTH * prior) / (v + PRIOR_STRENGTH)
    lb = bayes - Z_80 * RATING_SD / math.sqrt(v + PRIOR_STRENGTH)
    score = max(0.0, min(1.0, (lb - FLOOR) / (CEIL - FLOOR))) * 100
    reasons = [f"Рейтинг {rating:g}★ по {v} оценкам → с поправкой на объём {bayes:.2f}★, "
               f"«пессимистичная» оценка {lb:.2f}★."]
    if v < 30:
        reasons.append("Оценок меньше 30: даже идеальный рейтинг почти ничего не говорит.")
    elif v >= 300:
        reasons.append("Большой объём оценок: рейтинг статистически устойчив (если не накручен).")
    return {"score": round(score, 1), "bayesian": round(bayes, 3), "lower_bound": round(lb, 3), "reasons": reasons}


def rating_velocity(obs: List[RatingObservation]) -> Optional[Dict]:
    """Скачок числа оценок между снимками (нужно ≥3 снимков из API или ручной проверки)."""
    snaps: Dict[str, RatingObservation] = {}
    for o in obs:
        if o.source.via in ("platform_api", "manual_check") and o.volume:
            snaps[o.source.observed] = o
    ordered = [snaps[k] for k in sorted(snaps)]
    if len(ordered) < 3:
        return None
    steps = []
    for a, b in zip(ordered, ordered[1:]):
        days = (date.fromisoformat(b.source.observed) - date.fromisoformat(a.source.observed)).days
        if days > 0:
            steps.append({"rate": (b.volume - a.volume) / days, "delta": b.volume - a.volume, "days": days,
                          "from": a.source.observed, "to": b.source.observed})
    if len(steps) < 2:
        return None
    last = steps[-1]
    base = median(s["rate"] for s in steps[:-1])
    return {**last, "base_rate": round(base, 2),
            "spike": last["delta"] >= 20 and last["rate"] > 4 * max(base, 0.1),
            "drop": last["delta"] <= -10}


def _aggregate_signals(clinic: Clinic, estimates: Dict[str, Dict], with_texts: bool,
                       texts_have_platform_flags: bool) -> Tuple[float, List[str], List[Dict]]:
    """Сигналы на уровне сводных цифр: доля пятёрок, «Неподтверждённые», скачки, расхождение площадок."""
    penalty, reasons, flags = 0.0, [], []
    for platform, e in estimates.items():
        if not with_texts and e["rating"] >= 4.95 and e["volume"] >= 100:
            penalty += 10
            reasons.append(f"{platform}: рейтинг {e['rating']:g} при {e['volume']} оценках — почти не бывает "
                           "недовольных. Для медицины это нетипично: проверьте даты и тексты отзывов.")
            flags.append({"level": "yellow", "text": "Почти 100% пятёрок при большом объёме"})
        if e["unconfirmed"] is not None and e["volume"] and not texts_have_platform_flags:
            share = e["unconfirmed"] / (e["volume"] + e["unconfirmed"])
            if share > 0.02:
                penalty += min(30.0, share * 150)
                reasons.append(f"{platform}: {e['unconfirmed']} отзывов площадка сочла неподтверждёнными ({share:.0%}).")
                flags.append({"level": "red" if share >= 0.1 else "yellow",
                              "text": f"2ГИС пометил {share:.0%} отзывов как неподтверждённые"})
        if e["volume_spread"] > 0.25 and e["n_obs"] > 1:
            reasons.append(f"{platform}: число оценок в разных сводках расходится на {e['volume_spread']:.0%} — "
                           "данные могли устареть; обновите.")
    by_platform: Dict[str, List[RatingObservation]] = {}
    for o in clinic.ratings:
        by_platform.setdefault(o.platform, []).append(o)
    for platform, obs in by_platform.items():
        v = rating_velocity(obs)
        if v and v["spike"]:
            penalty += 15
            reasons.append(f"{platform}: с {v['from']} по {v['to']} добавилось {v['delta']} оценок "
                           f"({v['rate']:.1f} в день при обычных {v['base_rate']}) — похоже на пакет отзывов.")
            flags.append({"level": "red", "text": f"Скачок: +{v['delta']} оценок за {v['days']} дн."})
        elif v and v["drop"]:
            reasons.append(f"{platform}: число оценок уменьшилось на {-v['delta']} — площадка могла удалить "
                           "накрученные отзывы. Посмотрите раздел «Неподтверждённые».")
            flags.append({"level": "yellow", "text": f"Удалено {-v['delta']} оценок"})
    vals = [(p, e["rating"]) for p, e in estimates.items() if e["volume"] >= 10]
    if len(vals) >= 2:
        hi, lo = max(vals, key=lambda x: x[1]), min(vals, key=lambda x: x[1])
        gap = hi[1] - lo[1]
        if gap >= 0.4:
            penalty += 15
            reasons.append(f"Рейтинг на {hi[0]} выше, чем на {lo[0]}, на {gap:.1f}★ — признак накрутки на {hi[0]}.")
            flags.append({"level": "yellow", "text": f"Расхождение площадок {gap:.1f}★"})
    return penalty, reasons, flags


def authenticity_component(clinic: Clinic, estimates: Dict[str, Dict],
                           analysis: Optional[ReviewAnalysis]) -> Dict:
    if analysis is not None:
        has_pf = any(s.code == "platform_flags" for s in analysis.signals)
        penalty, extra, flags = _aggregate_signals(clinic, estimates, True, has_pf)
        for s in analysis.signals:
            if s.severity in ("warning", "critical"):
                flags.append({"level": "red" if s.severity == "critical" else "yellow", "text": s.title})
        return {"score": round(max(0.0, analysis.authenticity_index - penalty), 1),
                "confidence": analysis.confidence, "source": "texts",
                "reasons": [f"Проанализировано отзывов: {analysis.total}. {analysis.verdict_text}",
                            f"Подозрительных отзывов: {analysis.suspicious_count}; рейтинг без них — "
                            f"{analysis.cleaned_mean_rating}★ (было {analysis.raw_mean_rating}★)."] + extra,
                "flags": flags}

    penalty, extra, flags = _aggregate_signals(clinic, estimates, False, False)
    reasons = ["Тексты отзывов не анализировались — оценка только по сводным цифрам (нейтральные 70). "
               "Загрузите отзывы на вкладке «Проверить отзывы», чтобы проверить по-настоящему."] + extra
    return {"score": round(max(0.0, 70.0 - penalty), 1), "confidence": "низкая", "source": "aggregate",
            "reasons": reasons, "flags": flags}


def credentials_component(clinic: Clinic) -> Dict:
    score = 0.0
    reasons: List[str] = []
    flags: List[Dict] = []
    checks = []
    if clinic.license.status == "verified":
        score += 45
        reasons.append("Лицензия МЗ КР найдена в реестре.")
        flags.append({"level": "green", "text": "Лицензия подтверждена"})
    elif clinic.license.status == "not_found":
        reasons.append("Лицензия в реестре МЗ КР НЕ найдена.")
        flags.append({"level": "red", "text": "Лицензия не найдена в реестре"})
        return {"score": 0.0, "reasons": reasons, "flags": flags, "checks": checks}
    else:
        reasons.append("Лицензия МЗ КР не сверена с реестром.")
        flags.append({"level": "yellow", "text": "Лицензия не проверена"})
    if clinic.inn and clinic.inn_source:
        reasons.append(f"Юрлицо найдено в открытом реестре: ИНН {clinic.inn} — по нему можно проверить лицензию.")
        flags.append({"level": "green", "text": "Юрлицо найдено (ИНН)"})
    if clinic.doctors:
        score += 10
        reasons.append("Врачи названы публично: " + ", ".join(d.name for d in clinic.doctors) + ".")
    claim_weight = 0.0
    for doc in clinic.doctors:
        for c in doc.claims:
            v = check_credential(CredentialCheckRequest(
                title=c.title, claim_type=c.kind, issuer=c.issuer, year=c.year, document_id=c.document_id,
                holder_graduation_year=doc.graduation_year,
                holder_experience_years=doc.experience_years_claimed,
                holder_specialty=doc.role, evidence_level=c.evidence.level))
            checks.append({"doctor": doc.name, "claim": c.title, "verdict": v.model_dump()})
            claim_weight += v.weight
            if v.red_flags:
                score -= 15
                flags.append({"level": "red", "text": f"{doc.name}: {v.verdict}"})
    score += min(30.0, claim_weight * 30)
    if clinic.doctors and claim_weight < 0.5:
        reasons.append("Квалификация врачей известна только со слов клиники/СМИ — документы не сверены.")
    if not clinic.doctors:
        reasons.append("Ни один врач не назван в открытых источниках, которые мы нашли.")
    return {"score": round(max(0.0, min(100.0, score)), 1), "reasons": reasons, "flags": flags, "checks": checks}


def transparency_component(clinic: Clinic) -> Dict:
    """Что клиника сама открыла о себе. Наличие карточки 2ГИС не учитываем — она есть у всех."""
    parts = []
    if clinic.website:
        parts.append((20, "есть сайт"))
    if clinic.doctors:
        parts.append((20, "врачи названы"))
    platforms = {k for k in clinic.links if k in ("ydoc", "medelement", "medik", "kaktus")}
    if platforms:
        parts.append((15, "есть на медицинских площадках: " + ", ".join(sorted(platforms))))
    if clinic.inn:
        parts.append((15, "указано юрлицо"))
    if clinic.phones:
        parts.append((10, "телефоны опубликованы"))
    if clinic.hours:
        parts.append((10, "часы работы опубликованы"))
    if clinic.services and clinic.services_source:
        parts.append((10, "услуги описаны"))
    score = sum(p for p, _ in parts)
    return {"score": float(min(100, score)),
            "reasons": [("Найдено в открытых источниках: " + ", ".join(t for _, t in parts) + "."
                         if parts else "О клинике почти нет открытых данных."),
                        "Отражает то, что удалось найти к дате сбора; если клиника публикует больше — обновите данные."]}


def data_confidence(clinic: Clinic, analysis: Optional[ReviewAnalysis]) -> str:
    best = max((VIA_RANK[o.source.via] for o in clinic.ratings), default=0)
    if clinic.license.status == "verified" and (best >= 4 or analysis is not None):
        return "высокая"
    if best >= 3 or analysis is not None:
        return "средняя"
    return "низкая"


def evaluate(clinic: Clinic, prior: float, analysis: Optional[ReviewAnalysis] = None) -> Dict:
    estimates = platform_estimates(clinic)
    rating, volume = combined_rating(estimates)
    comp = {
        "rating": rating_component(rating, volume, prior),
        "authenticity": authenticity_component(clinic, estimates, analysis),
        "credentials": credentials_component(clinic),
        "transparency": transparency_component(clinic),
    }
    flags = comp["authenticity"].get("flags", []) + comp["credentials"]["flags"]
    if rating is not None:
        if volume >= 300 and rating >= 4.8:
            flags.insert(0, {"level": "green", "text": f"{rating:g}★ при {volume} оценках"})
        if rating < 4.3:
            flags.insert(0, {"level": "red", "text": f"Низкий рейтинг: {rating:g}★"})
        if volume < 30:
            flags.append({"level": "yellow", "text": f"Мало оценок ({volume})"})
    if clinic.ratings and all(o.source.via == "web_search_snippet" for o in clinic.ratings):
        flags.append({"level": "yellow", "text": "Рейтинг из поисковой выдачи — сверьте с 2ГИС"})

    trust = None
    if comp["rating"]["score"] is not None:
        trust = round(sum(WEIGHTS[k] * comp[k]["score"] for k in WEIGHTS), 1)
    return {
        "trust_index": trust,
        "rating": rating,
        "volume": volume,
        "platforms": estimates,
        "components": comp,
        "flags": flags,
        "confidence": data_confidence(clinic, analysis),
        "has_review_analysis": analysis is not None,
    }


def rank(clinics: List[Clinic], analyses: Optional[Dict[str, ReviewAnalysis]] = None) -> List[Dict]:
    analyses = analyses or {}
    prior = city_prior(clinics)
    results = [{"clinic": c, "score": evaluate(c, prior, analyses.get(c.id))} for c in clinics]
    ranked = sorted([r for r in results if r["score"]["trust_index"] is not None],
                    key=lambda r: (-r["score"]["trust_index"], -(r["score"]["volume"] or 0)))
    unranked = [r for r in results if r["score"]["trust_index"] is None]
    for pos, r in enumerate(ranked, 1):
        r["position"] = pos
    for r in unranked:
        r["position"] = None
    return ranked + unranked
