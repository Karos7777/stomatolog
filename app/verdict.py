"""Простой вердикт по клинике для обычного человека: 4 понятные проверки и итог.

    ✅ Можно доверять   — лицензия найдена, отзывы в порядке, нет красных флагов
    ⚠️ Можно, но проверьте — нет красных флагов, но что-то не подтверждено
    ❌ Не рекомендуем без проверки — есть красный флаг
"""
from typing import Dict, List, Optional

from app.models import Clinic

NEED_SCOPE = {           # какой профиль должен быть в лицензии для задачи
    "implant": "хирургия",
    "extraction": "хирургия",
    "maxillofacial": "хирургия",
    "sedation": "анестезия/наркоз",
    "prosthetics": "ортопедия (коронки, протезы)",
}


def _license_check(clinic: Clinic, need: Optional[str]) -> Dict:
    lic = clinic.license
    m = lic.matches[0] if lic.matches else None
    holder = f"{m.number} — {m.holder}" if m else ""
    if lic.unlicensed_at_address:
        return {"status": "bad", "title": "Лицензия: по этому адресу Минздрав выявил работу без лицензии",
                "detail": "Спросите номер лицензии и кто именно будет лечить. " + (holder and f"В реестре по адресу: {holder}.")}
    need_scope = NEED_SCOPE.get(need or "")
    gap = need_scope and need_scope in lic.scope_gaps
    if lic.status in ("verified", "probable"):
        if gap:
            return {"status": "bad", "title": f"Лицензия есть, но в ней нет: {need_scope}",
                    "detail": f"{holder}. Для этой задачи нужен такой вид помощи — спросите приложение к лицензии."}
        if lic.status == "probable":
            return {"status": "ok", "title": "Лицензия Минздрава, вероятно, найдена (совпало не всё)",
                    "detail": f"{holder}, {m.address} — сверьте номер на месте." if m else ""}
        return {"status": "ok", "title": "Лицензия Минздрава найдена", "detail": holder}
    if lic.status == "address_match":
        if gap:
            return {"status": "warn", "title": f"Лицензия по адресу есть, но в ней нет: {need_scope}", "detail": holder}
        return {"status": "ok" if m and m.match.get("address") == "exact" else "warn",
                "title": "Лицензия по адресу найдена (оформлена на владельца/юрлицо)", "detail": holder}
    if lic.status == "state":
        return {"status": "ok", "title": "Государственная поликлиника — частная лицензия ей не нужна",
                "detail": "Реестр лицензий Минздрава ведётся только для частных клиник и ИП (приказ МЗ КР №212), "
                          "госполиклиник в нём нет и быть не должно."}
    if lic.status == "ambiguous":
        return {"status": "warn", "title": "В здании много лицензий — чья у клиники, неясно",
                "detail": "Попросите показать лицензию на месте."}
    if lic.status == "doctor_license":
        return {"status": "warn", "title": "Лицензия есть у врача клиники (ИП), но на другой адрес",
                "detail": f"{holder}, в реестре: {m.address}. Спросите, по какой лицензии врач принимает именно здесь."
                          if m else "Спросите, по какой лицензии врач принимает именно здесь."}
    if lic.status == "name_other_address":
        return {"status": "warn", "title": "Лицензия на это название выдана на другой адрес",
                "detail": f"{holder}, в реестре: {m.address}." if m else ""}
    return {"status": "bad", "title": "Лицензии нет в реестре Минздрава",
            "detail": "Это не всегда нарушение (старые лицензии, другое юрлицо), но спросите номер до лечения."}


def _reviews_check(clinic: Clinic, score: Dict) -> Dict:
    rating, volume = score["rating"], score["volume"] or 0
    auth = score["components"]["authenticity"]
    ydoc = next((o for o in clinic.ratings if o.platform == "ydoc"), None)
    extra = f" На YDoc — {ydoc.rating:g}★ по {ydoc.reviews_count} отзывам о врачах (подтверждены записью/звонком)." if ydoc else ""
    red = [f for f in auth.get("flags", []) if f["level"] == "red"]
    if rating is None:
        return {"status": "unknown", "title": "Отзывов почти нет", "detail": "Оценить по отзывам нельзя." + extra}
    base = f"{rating:g}★ по {volume} оценкам в 2ГИС."
    if red:
        return {"status": "bad", "title": "Отзывы: признаки накрутки", "detail": base + " " + red[0]["text"] + extra}
    if rating < 4.3:
        return {"status": "bad", "title": f"Отзывы: низкий рейтинг {rating:g}★", "detail": base + extra}
    if volume < 30:
        return {"status": "warn", "title": "Отзывов мало — рейтингу рано верить", "detail": base + extra}
    if rating >= 4.95 and volume >= 100:
        return {"status": "warn", "title": "Почти одни пятёрки — так бывает при накрутке",
                "detail": base + " Прочитайте плохие отзывы (1–3★) и проверьте, не пришли ли пятёрки пачкой." + extra}
    return {"status": "ok", "title": f"Отзывы хорошие: {rating:g}★, оценок много", "detail": base + extra}


def _doctors_check(clinic: Clinic) -> Dict:
    verified = [d for d in clinic.doctors if d.profile.get("documents_verified")]
    flagged = [d for d in clinic.doctors if d.profile.get("red_flags")]
    if flagged:
        d = flagged[0]
        return {"status": "bad", "title": f"Врач с противоречиями в анкете: {d.name}", "detail": d.profile["red_flags"][0]}
    if verified:
        names = "; ".join(f"{d.name} ({(d.profile.get('specialties') or ['стоматолог'])[0].lower()}"
                          f"{', стаж ' + str(d.profile['experience_years']) + ' л.' if d.profile.get('experience_years') else ''})"
                          for d in verified[:3])
        foreign = [d for d in verified if d.profile.get("foreign_verified")]
        tail = f" Зарубежный диплом проверен: {', '.join(d.name for d in foreign)}." if foreign else ""
        return {"status": "ok", "title": f"Врачей с проверенными дипломами: {len(verified)}", "detail": names + "." + tail}
    if clinic.doctors:
        return {"status": "warn", "title": "Врачи известны, но дипломы не проверены",
                "detail": ", ".join(d.name for d in clinic.doctors[:4]) + ". Попросите показать дипломы."}
    return {"status": "unknown", "title": "Врачи не известны",
            "detail": "Спросите ФИО врача и посмотрите его анкету на YDoc."}


def _fit_check(clinic: Clinic, coverage: Optional[Dict]) -> Optional[Dict]:
    if not coverage or (not coverage["matched"] and not coverage["partial"] and not coverage["missing"]
                        and not coverage["unknown"]):
        return None
    if coverage["matched"]:
        return {"status": "ok", "title": "Делают то, что нужно", "detail": "; ".join(coverage["matched"])}
    if coverage["partial"]:
        return {"status": "warn", "title": "Близкое направление — уточните по телефону", "detail": ", ".join(coverage["partial"])}
    if coverage["unknown"]:
        return {"status": "warn", "title": "Список услуг неизвестен — уточните по телефону", "detail": ""}
    return {"status": "warn", "title": "Нужную услугу не указывают", "detail": ", ".join(coverage["missing"])}


def verdict(clinic: Clinic, score: Dict, need: Optional[str] = None, coverage: Optional[Dict] = None) -> Dict:
    checks: List[Dict] = [_license_check(clinic, need), _reviews_check(clinic, score), _doctors_check(clinic)]
    fit = _fit_check(clinic, coverage)
    if fit:
        checks.append(fit)
    statuses = [c["status"] for c in checks]
    if "bad" in statuses:
        level, title = "bad", "Не рекомендуем без проверки"
    elif checks[0]["status"] == "ok" and checks[1]["status"] == "ok":
        level, title = "good", "Можно доверять"
    else:
        level, title = "ok", "Можно, но проверьте пункты с ⚠️"
    return {"level": level, "title": title, "checks": checks}
