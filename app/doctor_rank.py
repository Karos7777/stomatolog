"""Подбор врача под задачу. Врач важнее клиники, поэтому ранжируем людей, а клинику учитываем только как условия работы.

Каждая причина честно помечена, откуда она известна:
  «подтверждено» — YDoc сверил документ, запись есть в реестре Минздрава или отзыв подтверждён записью на приём;
  «заявлено»     — врач или клиника сами так пишут (анкета, список услуг в 2ГИС);
  «нет данных»   — этого мы не знаем; в баллы такое не идёт, но показывается, чтобы было понятно, что спросить.

Оценка — это соответствие задаче по бумагам, а не качество лечения: как врач работает руками (коффердам, снимки,
микроскоп в кабинете), видно только на приёме.
"""
from typing import Dict, List, Optional

SCORE_PARTS = {"relevance": 30, "training": 15, "verification": 15, "experience": 10, "feedback": 10, "setting": 12}
MAX_POINTS = sum(SCORE_PARTS.values())

POSTGRAD = ("ординатур", "интернатур", "переподготовк", "повышение квалификации", "стажировк", "докторантур",
            "аспирантур", "курс")

# core — специальность в анкете, прямо про задачу; strong/related — слова в названии ординатуры или курса;
# equipment — слова в списке услуг клиники (2ГИС); general — подойдёт ли «просто стоматолог»;
# adult_only — детских стоматологов для этой задачи не берём.
NEEDS: Dict[str, Dict] = {
    "endo": {"label": "Лечение каналов", "core": ("эндодонт",), "general": True, "adult_only": True,
             "strong": ("эндодонт", "микроскоп", "ретритмент"), "related": ("терапевт", "общей практики"),
             "equipment": ("микроскоп",), "equipment_label": "микроскоп",
             "specialty_label": "эндодонтист",
             "tips": ["Коффердам (резиновая завеса) на зубе: его видно сразу, спрашивать не нужно.",
                      "Микроскоп или лупы в кабинете: они либо стоят, либо нет.",
                      "Снимок до и после пломбирования: его показывают на экране и дают копию. Нет снимка — нет и контроля."]},
    "caries": {"label": "Лечение кариеса", "core": ("терапевт",), "general": True, "adult_only": True,
               "strong": ("терапевт",), "related": ("общей практики",), "equipment": ("микроскоп",),
               "equipment_label": "микроскоп", "specialty_label": "стоматолог-терапевт"},
    "emergency": {"label": "Срочная помощь", "core": ("терапевт", "хирург"), "general": True, "adult_only": True,
                  "strong": ("терапевт", "хирург"), "related": ("общей практики",), "equipment": (),
                  "specialty_label": "терапевт или хирург"},
    "implant": {"label": "Имплантация", "core": ("имплантолог",), "also": ("хирург", "челюстно"), "general": False,
                "adult_only": True, "strong": ("имплант",), "related": ("хирург", "челюстно"),
                "equipment": ("кт зубов", "клкт", "компьютерная томограф"), "equipment_label": "КТ",
                "specialty_label": "имплантолог"},
    "extraction": {"label": "Удаление зубов", "core": ("хирург", "челюстно"), "general": True, "adult_only": True,
                   "strong": ("хирург", "челюстно"), "related": (), "equipment": ("кт зубов", "клкт", "оптг"),
                   "equipment_label": "КТ или панорамный снимок", "specialty_label": "хирург"},
    "ortho": {"label": "Брекеты, элайнеры", "core": ("ортодонт",), "general": False, "adult_only": False,
              "strong": ("ортодонт",), "related": (), "equipment": ("цифровая", "3d"),
              "equipment_label": "цифровая диагностика", "specialty_label": "ортодонт"},
    "kids": {"label": "Детская стоматология", "core": ("детск",), "general": False, "adult_only": False,
             "strong": ("детск", "педиатр"), "related": (), "equipment": ("седация для детей",),
             "equipment_label": "седация для детей", "specialty_label": "детский стоматолог"},
    "prosthetics": {"label": "Коронки, протезы, виниры", "core": ("ортопед",), "general": False, "adult_only": True,
                    "strong": ("ортопед", "протез"), "related": (), "equipment": ("цифровая", "cad"),
                    "equipment_label": "цифровое моделирование", "specialty_label": "ортопед"},
    "hygiene": {"label": "Чистка и гигиена", "core": ("гигиенист", "пародонт"), "general": True, "adult_only": False,
                "strong": ("гигиен", "пародонт"), "related": (), "equipment": (),
                "specialty_label": "гигиенист или пародонтолог"},
    "sedation": {"label": "Лечение во сне", "core": ("анестезиолог",), "general": False, "adult_only": False,
                 "strong": ("анестезиолог",), "related": (), "equipment": ("седац", "наркоз", "во сне"),
                 "equipment_label": "седация или наркоз", "specialty_label": "анестезиолог"},
    "maxillofacial": {"label": "Челюстно-лицевая хирургия", "core": ("челюстно",), "general": False, "adult_only": False,
                      "strong": ("челюстно", "ортогнат"), "related": ("хирург",), "equipment": (),
                      "specialty_label": "челюстно-лицевой хирург"},
}

LICENSE_FOUND = {"verified", "probable", "state"}
LICENSE_PARTLY = {"address_match", "doctor_license"}
CLAIMED, CONFIRMED, UNKNOWN = "заявлено", "подтверждено", "нет данных"


def _has(text: str, words) -> bool:
    return any(w in text for w in words)


def _reason(sign: str, text: str, basis: str, points: float = 0) -> Dict:
    return {"sign": sign, "text": text, "basis": basis, "points": round(points, 1)}


def _clinic_view(row: Dict) -> Dict:
    c = row["clinic"]
    return {"id": c.id, "name": c.name, "address": c.address, "license": c.license.status,
            "unlicensed": bool(c.license.unlicensed_at_address), "rating": row["score"]["rating"],
            "volume": row["score"]["volume"], "trust": row["score"]["trust_index"]}


def best_clinic(doctor: Dict, rows_by_id: Dict[str, Dict]) -> Optional[Dict]:
    """Место работы врача с лучшей репутацией: условия приёма у него смотрим по этой клинике."""
    rows = [rows_by_id[l["clinic_id"]] for l in doctor.get("clinics", []) if l["clinic_id"] in rows_by_id]
    return max(rows, key=lambda r: r["score"]["trust_index"] or 0, default=None)


def score_doctor(doctor: Dict, need: str, rows_by_id: Dict[str, Dict]) -> Optional[Dict]:
    """None — врач для этой задачи не подходит вовсе (например, детский стоматолог для взрослого лечения каналов)."""
    prof = NEEDS[need]
    specs = [s.lower() for s in doctor["specialties"]]
    pediatric_only = bool(specs) and all("детск" in s for s in specs)
    if prof["adult_only"] and pediatric_only:
        return None

    reasons: List[Dict] = []
    parts = {k: 0.0 for k in SCORE_PARTS}

    # --- 1. Профиль: что указано в анкете ---
    core = [s for s in doctor["specialties"] if _has(s.lower(), prof["core"])]
    also = [s for s in doctor["specialties"] if _has(s.lower(), prof.get("also", ())) and s not in core]
    plain = any(s in ("стоматолог", "стоматолог-терапевт") or "терапевт" in s for s in specs)
    if core:
        parts["relevance"] = 30
        reasons.append(_reason("+", f"В анкете указано: {', '.join(c.lower() for c in core)}", CLAIMED, 30))
        fit = "profile"
    elif also:
        parts["relevance"] = 20
        reasons.append(_reason("+", f"Смежная специальность: {', '.join(a.lower() for a in also)}", CLAIMED, 20))
        fit = "profile"
    elif prof["general"] and plain:
        narrow = [s for s in doctor["specialties"] if s.lower() != "стоматолог" and "терапевт" not in s.lower()]
        parts["relevance"] = 6 if narrow else 12
        reasons.append(_reason("?", "Специальность по этой теме в анкете не указана: общий стоматолог"
                               + (f" (занимается также: {', '.join(n.lower() for n in narrow)})" if narrow else ""),
                               CLAIMED, parts["relevance"]))
        fit = "general"
    else:
        return None

    # --- 2. Обучение по теме ---
    post = [e for e in doctor["education"] if _has((e.get("kind") or "").lower(), POSTGRAD)]
    strong = [e for e in post if _has(f"{e.get('specialty') or ''} {e.get('institution') or ''}".lower(), prof["strong"])]
    related = [e for e in post if e not in strong
               and _has(f"{e.get('specialty') or ''} {e.get('kind') or ''}".lower(), prof["related"])]

    def edu_text(e):
        return f"{(e.get('kind') or 'Обучение').lower()}: {e.get('institution') or '—'}" \
               f"{', ' + str(e['year']) if e.get('year') else ''}{' — ' + e['specialty'] if e.get('specialty') else ''}"

    if strong:
        parts["training"] = 15
        reasons.append(_reason("+", "Учился именно по этой теме — " + edu_text(strong[0]),
                               CONFIRMED if strong[0]["confirmed"] else CLAIMED, 15))
    elif related:
        parts["training"] = 8
        reasons.append(_reason("+", "Учился по близкой программе — " + edu_text(related[0]),
                               CONFIRMED if related[0]["confirmed"] else CLAIMED, 8))
    elif prof["general"] or core:
        reasons.append(_reason("?", "В анкете нет обучения по этой теме" + (
            " (специальность указана, а подтверждающей учёбы нет)" if core else ""), UNKNOWN))

    # --- 3. Проверенные документы ---
    base_ok = any(e["confirmed"] and (e.get("kind") or "").lower().startswith("базовое") for e in doctor["education"])
    topic_ok = any(e["confirmed"] for e in strong + related)
    other_post_ok = any(e["confirmed"] for e in post)
    if base_ok:
        parts["verification"] += 8
        reasons.append(_reason("+", "YDoc сверил диплом о высшем образовании", CONFIRMED, 8))
    if topic_ok:
        parts["verification"] += 7
        reasons.append(_reason("+", "YDoc сверил документ об обучении по этой теме", CONFIRMED, 7))
    elif other_post_ok:
        parts["verification"] += 4
        reasons.append(_reason("+", "YDoc сверил документ о послевузовском обучении", CONFIRMED, 4))
    if not base_ok:
        reasons.append(_reason("?", "Документы пока никто не сверил — попросите показать диплом", UNKNOWN))
    if doctor["foreign"] and not doctor["foreign_verified"]:
        reasons.append(_reason("?", "Учёба за рубежом ("
                               + ", ".join(doctor["foreign_countries"]) + ") указана в анкете, документ не проверен", CLAIMED))

    # --- 4. Стаж ---
    exp = doctor["experience_years"]
    if exp:
        parts["experience"] = round(min(exp, 20) / 20 * 10, 1)
        reasons.append(_reason("+", f"Стаж {exp} лет", CLAIMED, parts["experience"]))
    else:
        reasons.append(_reason("?", "Стаж не указан", UNKNOWN))

    # --- 5. Отзывы о враче на YDoc (подтверждённые записью весят полностью, остальные вполовину) ---
    rv = doctor["reviews"]
    if rv["count"]:
        weight = rv["verified"] + 0.5 * (rv["count"] - rv["verified"])
        shrunk = ((rv["mean"] or 0) * weight + 4.6 * 4) / (weight + 4)
        parts["feedback"] = round(10 * max(0.0, min(1.0, (shrunk - 4.3) / 0.7)), 1)
        reasons.append(_reason("+" if parts["feedback"] >= 5 else "?",
                               f"Отзывы о враче на YDoc: {rv['mean']:.1f}★, {rv['count']} шт., подтверждены записью: {rv['verified']}",
                               CONFIRMED if rv["verified"] else CLAIMED, parts["feedback"]))
    else:
        reasons.append(_reason("?", "На YDoc отзывов о враче нет", UNKNOWN))

    # --- 6. Условия: клиника, где принимает ---
    row = best_clinic(doctor, rows_by_id)
    clinic = None
    equipment_found: List[str] = []
    if row:
        clinic = _clinic_view(row)
        c = row["clinic"]
        services = " ".join(c.services).lower()
        equipment_found = [w for w in prof["equipment"] if w in services]
        if equipment_found:
            parts["setting"] += 6
            reasons.append(_reason("+", f"Клиника указывает в услугах: {prof['equipment_label']}", CLAIMED, 6))
        elif prof["equipment"]:
            reasons.append(_reason("?", f"Клиника не указывает: {prof['equipment_label']}", UNKNOWN))
        if c.license.status in LICENSE_FOUND:
            parts["setting"] += 4
            reasons.append(_reason("+", "Лицензия клиники найдена в реестре Минздрава" if c.license.status != "state"
                                   else "Государственная поликлиника (лицензия частного реестра не нужна)", CONFIRMED, 4))
        elif c.license.status in LICENSE_PARTLY:
            parts["setting"] += 2
            reasons.append(_reason("?", "Лицензия по адресу есть, но оформлена не на клинику: уточните, чья она", CONFIRMED, 2))
        else:
            reasons.append(_reason("-", "Лицензии клиники нет в реестре Минздрава — спросите номер", CONFIRMED))
        if c.license.unlicensed_at_address:
            parts["setting"] -= 6
            reasons.append(_reason("-", "По адресу клиники Минздрав выявлял работу без лицензии", CONFIRMED, -6))
        if clinic["rating"] and clinic["rating"] >= 4.5 and (clinic["volume"] or 0) >= 30:
            parts["setting"] += 2
            reasons.append(_reason("+", f"Рейтинг клиники в 2ГИС {clinic['rating']:.1f}★ по {clinic['volume']} оценкам", CLAIMED, 2))
    else:
        reasons.append(_reason("?", "Клинику в 2ГИС по анкете определить не удалось", UNKNOWN))

    # --- Штрафы ---
    penalty = 0.0
    for flag in doctor["red_flags"]:
        penalty += 25
        reasons.append(_reason("-", "Противоречие в анкете: " + flag, CONFIRMED, -25))
    for warning in doctor["warnings"]:
        if "без отдельной подготовки" in warning or "специальностей при стаже" in warning:
            reasons.append(_reason("?", warning, CLAIMED))

    raw = sum(parts.values()) - penalty
    score = round(max(0.0, raw) / MAX_POINTS * 100)
    confirmed_any = base_ok or topic_ok
    if fit == "profile" and confirmed_any and rv["count"] >= 3:
        confidence = "высокая"
    elif fit == "profile" or confirmed_any:
        confidence = "средняя"
    else:
        confidence = "низкая"
    return {
        "id": doctor["id"], "name": doctor["name"], "url": doctor["url"], "specialties": doctor["specialties"],
        "experience": exp, "score": score, "confidence": confidence, "fit": fit,
        "profile_match": bool(core or also), "equipment": bool(equipment_found),
        "documents_verified": doctor["documents_verified"], "foreign": doctor["foreign"],
        "foreign_countries": doctor["foreign_countries"],
        "reasons": sorted(reasons, key=lambda r: ({"+": 0, "-": 1, "?": 2}[r["sign"]], -abs(r["points"]))),
        "clinic": clinic, "other_clinics": [l["clinic_name"] for l in doctor.get("clinics", [])
                                            if not clinic or l["clinic_id"] != clinic["id"]],
        "reviews": rv, "updated": doctor["profile_updated"],
    }


def rank_doctors(doctors: List[Dict], need: str, rows_by_id: Dict[str, Dict], only_profile: bool = False,
                 require_equipment: bool = False, verified_docs: bool = False) -> List[Dict]:
    out = []
    for d in doctors:
        r = score_doctor(d, need, rows_by_id)
        if not r:
            continue
        if only_profile and not r["profile_match"]:
            continue
        if require_equipment and not r["equipment"]:
            continue
        if verified_docs and not r["documents_verified"]:
            continue
        out.append(r)
    out.sort(key=lambda r: (-r["score"], r["name"] or ""))
    return out
