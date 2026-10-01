"""Подбор клиники под проблему пациента: индекс доверия × соответствие услуг."""
from typing import Dict, List

from app.models import Clinic

TOPICS: Dict[str, Dict] = {
    "implant": {"label": "Имплантация", "keys": ("имплант", "all-on", "синус", "нет зуба", "нету зуба", " кост"),
                "services": ("имплант", "синус"), "partial": ("хирург",)},
    "ortho": {"label": "Ортодонтия", "keys": ("брекет", "элайнер", "прикус", "кривые", "ровн", "капп"),
              "services": ("ортодонт", "брекет", "элайнер", "прикус")},
    "kids": {"label": "Детская стоматология", "keys": ("ребен", "ребён", "детск", "дети", "малыш", "молочн", " сын", "дочь", "дочк"),
             "services": ("детск", "дети", "детей")},
    "sedation": {"label": "Лечение во сне / седация", "keys": ("наркоз", "седац", "во сне", "боюсь", "страх", "паник"),
                 "services": ("седац", "наркоз", "во сне")},
    "emergency": {"label": "Срочная помощь 24/7", "keys": ("срочно", "ночь", "ночью", "острая", "флюс", "отек", "отёк", "24/7", "круглосуточ"),
                  "services": ("круглосуточ",), "needs_24_7": True},
    "endo": {"label": "Лечение каналов", "keys": ("канал", "пульпит", "нерв ", "нерва", "микроскоп"),
             "services": ("микроскоп",), "partial": ("терапевт", "лечение")},
    "caries": {"label": "Лечение кариеса", "keys": ("кариес", "пломб", "дырк"),
               "services": ("стоматолог-терапевт", "кариес"), "universal": True},
    "extraction": {"label": "Удаление", "keys": ("удалит", "удален", "удалени", "удалять", "вырвать", "мудрост", "восьмерк"),
                   "services": ("хирург", "удален")},
    "prosthetics": {"label": "Коронки, протезы, виниры", "keys": ("коронк", "протез", " мост", "винир"),
                    "services": ("ортопед", "протез", "винир", "коронк"), "partial": ("эстетик", "цифров")},
    "hygiene": {"label": "Чистка и гигиена", "keys": ("чистк", "камень", "налет", "налёт", "отбел", "гигиен"),
                "services": ("чистк", "гигиен", "профилакт", "пародонт"), "universal": True},
    "maxillofacial": {"label": "Челюстно-лицевая хирургия", "keys": ("челюст", "ортогнат", "травм"),
                      "services": ("челюстно", "ортогнат")},
}


def detect_topics(problem: str) -> List[str]:
    p = f" {problem.lower()} "
    return [t for t, d in TOPICS.items() if any(k in p for k in d["keys"])]


def coverage(clinic: Clinic, topics: List[str]) -> Dict:
    """Доля нужных направлений, которые клиника указывает в услугах (по источникам).
    «Частично» — указано смежное направление (например, хирургия вместо имплантации)."""
    if not topics:
        return {"value": 1.0, "matched": [], "partial": [], "missing": [], "unknown": False}
    if not clinic.services:
        return {"value": 0.5, "matched": [], "partial": [], "missing": [], "unknown": True}
    text = " ".join(clinic.services).lower()
    matched, partial, missing = [], [], []
    for t in topics:
        d = TOPICS[t]
        if (any(s in text for s in d["services"]) or (d.get("needs_24_7") and clinic.is_24_7)
                or (d.get("universal") and not clinic.multi_profile)):
            matched.append(d["label"])
        elif any(s in text for s in d.get("partial", ())):
            partial.append(d["label"])
        else:
            missing.append(d["label"])
    value = (len(matched) + 0.5 * len(partial)) / len(topics)
    return {"value": value, "matched": matched, "partial": partial, "missing": missing, "unknown": False}


def match(ranked: List[Dict], problem: str, need_24_7: bool = False) -> Dict:
    topics = detect_topics(problem)
    if any(TOPICS[t].get("needs_24_7") for t in topics):
        need_24_7 = True
    results = []
    for r in ranked:
        clinic, score = r["clinic"], r["score"]
        if score["trust_index"] is None:
            continue
        if need_24_7 and not clinic.is_24_7:
            continue
        cov = coverage(clinic, topics)
        fit = round(score["trust_index"] * (0.6 + 0.4 * cov["value"]), 1)
        reasons = []
        if cov["matched"]:
            reasons.append("Указывает услуги: " + ", ".join(cov["matched"]))
        if cov["partial"]:
            reasons.append("Смежное направление, уточните: " + ", ".join(cov["partial"]))
        if cov["missing"]:
            reasons.append("Не указывает: " + ", ".join(cov["missing"]) + " — уточните по телефону")
        if cov["unknown"]:
            reasons.append("Перечень услуг неизвестен — уточните по телефону")
        if clinic.is_24_7:
            reasons.append("Работает круглосуточно (по данным 2ГИС)")
        results.append({**r, "fit": fit, "coverage": cov, "reasons": reasons})
    results.sort(key=lambda x: (-x["fit"], -x["score"]["trust_index"]))
    return {"topics": [TOPICS[t]["label"] for t in topics], "need_24_7": need_24_7, "results": results}
