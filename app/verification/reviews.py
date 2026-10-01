"""Анализатор подлинности отзывов.

Ни один отдельный признак не доказывает накрутку. Мы считаем несколько независимых
поведенческих и текстовых сигналов, которые в исследованиях лучше всего отделяли
заказные отзывы от настоящих, и показываем, на чём основан каждый вывод.
"""
import zlib
from collections import Counter, defaultdict
from datetime import date, timedelta
from statistics import mean, median
from typing import Dict, List, Optional, Tuple

from app.models import (AggregateInput, ReviewAnalysis, ReviewFlags, ReviewInput,
                        Signal)
from app.verification.dates import parse_date
from app.verification.text import (DETAIL_STEMS, DOCTOR_MENTION, NUMBER, PRAISE_STEMS,
                                   PROCEDURE_STEMS, char_shingles, count_hits, jaccard,
                                   normalize)

REFERENCES = {
    "duplicates": "Jindal & Liu (2008) «Opinion Spam and Analysis», WSDM — копии и почти-копии текстов как главный признак спама.",
    "bursts": "Fei et al. (2013) «Exploiting Burstiness in Reviews for Review Spammer Detection», ICWSM — заказные отзывы приходят всплесками.",
    "behavior": "Mukherjee et al. (2013) «What Yelp Fake Review Filter Might Be Doing?», ICWSM — поведенческие признаки (одноразовые аккаунты, всплески) надёжнее текста.",
    "specificity": "Ott et al. (2011) «Finding Deceptive Opinion Spam by Any Stretch of the Imagination», ACL — выдуманные отзывы беднее конкретикой и богаче общими восторгами.",
    "distribution": "Hu, Pavlou & Zhang (2009) «Overcoming the J-shaped distribution of product reviews», Comm. ACM — у настоящих отзывов J-образное распределение, а не сплошные пятёрки.",
    "cross_platform": "Mayzlin, Dover & Chevalier (2014) «Promotional Reviews», American Economic Review — сравнение площадок с разной стоимостью накрутки выявляет манипуляции.",
    "competition": "Luca & Zervas (2016) «Fake It Till You Make It», Management Science — накручивают чаще те, у кого мало отзывов или ухудшается репутация; конкуренты пишут фальшивый негатив.",
    "2gis": "Помощник 2ГИС «Куда пропал отзыв»: сомнительные отзывы переносятся в раздел «Неподтверждённые» и не влияют на рейтинг.",
}

DUP_THRESHOLD = 0.6        # Jaccard по символьным 5-граммам
MIN_DUP_LEN = 25           # короче — «Спасибо!» совпадает у честных людей, не считаем копией
SUSPICIOUS_AT = 0.5        # порог итоговой подозрительности отзыва
SPECIFIC_RELIEF = 0.15     # скидка подозрения за ≥3 конкретных деталей
MAX_REVIEWS = 2000

WEIGHTS = {
    "duplicate": 0.4,
    "burst": 0.3,
    "generic": 0.2,
    "singleton": 0.2,
    "burying": 0.2,
    "unconfirmed": 0.5,
}


class _Prepared:
    __slots__ = ("idx", "src", "norm", "shingles", "day", "generic", "specific", "empty")

    def __init__(self, idx: int, src: ReviewInput, today: date):
        self.idx = idx
        self.src = src
        self.norm = normalize(src.text)
        self.shingles = char_shingles(src.text) if len(self.norm) >= MIN_DUP_LEN else set()
        self.day = parse_date(src.date, today)
        self.empty = len(self.norm) == 0
        specific = (
            count_hits(self.norm, PROCEDURE_STEMS)
            + count_hits(self.norm, DETAIL_STEMS)
            + (1 if DOCTOR_MENTION.search(src.text or "") else 0)
            + (1 if NUMBER.search(src.text or "") else 0)
        )
        self.specific = specific
        praise = count_hits(self.norm, PRAISE_STEMS)
        self.generic = (not self.empty) and specific == 0 and praise >= 1 and len(self.norm) < 200


# ---------------------------------------------------------------------------
# Отдельные детекторы
# ---------------------------------------------------------------------------

_MINHASH_SALTS = [zlib.crc32(f"dentbishkek-{k}".encode()) for k in range(32)]
_BANDS, _ROWS = 16, 2   # при сходстве 0.6 вероятность попасть в кандидаты ≈ 99.9%


def _minhash(shingles: set) -> Tuple[int, ...]:
    hashes = [zlib.crc32(s.encode()) for s in shingles]
    return tuple(min(map(salt.__xor__, hashes)) for salt in _MINHASH_SALTS)


def _find_duplicate_groups(items: List[_Prepared]) -> List[List[int]]:
    """Группы почти-одинаковых текстов: MinHash LSH для кандидатов, точный Jaccard для проверки."""
    with_text = [p for p in items if p.shingles]
    if len(with_text) < 2:
        return []
    buckets: Dict[tuple, List[int]] = defaultdict(list)
    for pos, p in enumerate(with_text):
        sig = _minhash(p.shingles)
        for b in range(_BANDS):
            buckets[(b,) + sig[b * _ROWS:(b + 1) * _ROWS]].append(pos)

    candidates = set()
    for members in buckets.values():
        if len(members) < 2:
            continue
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                candidates.add((members[i], members[j]))

    parent = list(range(len(with_text)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i, j in candidates:
        if find(i) == find(j):
            continue
        if jaccard(with_text[i].shingles, with_text[j].shingles) >= DUP_THRESHOLD:
            parent[find(i)] = find(j)

    groups: Dict[int, List[int]] = defaultdict(list)
    for pos in range(len(with_text)):
        groups[find(pos)].append(with_text[pos].idx)
    return [sorted(g) for g in groups.values() if len(g) > 1]


def _polarity(rating: Optional[int]) -> Optional[str]:
    if rating is None:
        return None
    if rating >= 4:
        return "pos"
    if rating <= 2:
        return "neg"
    return None


def _find_bursts(items: List[_Prepared]) -> Tuple[Dict[int, str], List[dict], Optional[float]]:
    """Всплески: 7-дневное окно, где отзывов в разы больше обычного недельного темпа.

    Базовый темп — медиана по неделям (а не среднее), чтобы сам всплеск не поднимал порог.
    Возвращает: {idx: polarity} для отзывов во всплесках, эпизоды, порог.
    """
    dated = sorted((p for p in items if p.day), key=lambda p: p.day)
    if len(dated) < 10:
        return {}, [], None
    start, end = dated[0].day, dated[-1].day
    span_days = (end - start).days + 1
    if span_days < 28:
        return {}, [], None

    weeks = Counter((p.day - start).days // 7 for p in dated)
    n_weeks = span_days // 7 + 1
    weekly = [weeks.get(w, 0) for w in range(n_weeks)]
    base = median(weekly)
    threshold = max(5, int(round(4 * max(base, 0.5))))

    days = [p.day for p in dated]
    in_burst: Dict[int, str] = {}
    lo = 0
    hot_windows: List[Tuple[date, date, List[_Prepared]]] = []
    for hi in range(len(dated)):
        while days[hi] - days[lo] > timedelta(days=6):
            lo += 1
        window = dated[lo:hi + 1]
        if len(window) >= threshold:
            hot_windows.append((days[lo], days[hi], window))

    # Склеиваем пересекающиеся окна в эпизоды
    episodes: List[dict] = []
    for w_start, w_end, window in hot_windows:
        if episodes and w_start <= episodes[-1]["end"]:
            ep = episodes[-1]
            ep["end"] = max(ep["end"], w_end)
            ep["members"].update(p.idx for p in window)
            ep["items"].update({p.idx: p for p in window})
        else:
            episodes.append({"start": w_start, "end": w_end,
                             "members": {p.idx for p in window},
                             "items": {p.idx: p for p in window}})

    result_eps = []
    for ep in episodes:
        members = list(ep["items"].values())
        ratings = [p.src.rating for p in members if p.src.rating]
        pos_share = (sum(1 for r in ratings if r >= 4) / len(ratings)) if ratings else None
        neg_share = (sum(1 for r in ratings if r <= 2) / len(ratings)) if ratings else None
        if pos_share is not None and pos_share >= 0.8:
            pol = "pos"
        elif neg_share is not None and neg_share >= 0.6:
            pol = "neg"
        else:
            pol = None
        if pol:
            for p in members:
                if _polarity(p.src.rating) == pol:
                    in_burst[p.idx] = pol
        result_eps.append({
            "start": ep["start"].isoformat(),
            "end": ep["end"].isoformat(),
            "count": len(members),
            "polarity": pol,
            "pos_share": round(pos_share, 2) if pos_share is not None else None,
        })
    return in_burst, result_eps, float(base)


def _find_burying(items: List[_Prepared]) -> Tuple[set, List[str]]:
    """«Закапывание» негатива: после отзыва на 1–2★ за 72 часа приходит ≥3 пятёрок."""
    dated = sorted((p for p in items if p.day and p.src.rating), key=lambda p: p.day)
    buried, evidence = set(), []
    for i, neg in enumerate(dated):
        if neg.src.rating > 2:
            continue
        followers = [p for p in dated[i + 1:]
                     if p.day - neg.day <= timedelta(days=3) and p.src.rating == 5]
        if len(followers) >= 3:
            buried.update(p.idx for p in followers)
            evidence.append(f"{neg.day.isoformat()}: отзыв на {neg.src.rating}★, затем {len(followers)} пятёрок за 3 дня")
    return buried, evidence


# ---------------------------------------------------------------------------
# Основная функция
# ---------------------------------------------------------------------------

def analyze_reviews(reviews: List[ReviewInput],
                    aggregate: Optional[AggregateInput] = None,
                    today: Optional[date] = None) -> ReviewAnalysis:
    today = today or date.today()
    reviews = reviews[-MAX_REVIEWS:]
    items = [_Prepared(i, r, today) for i, r in enumerate(reviews)]
    n = len(items)
    signals: List[Signal] = []
    per_review: Dict[int, List[Tuple[str, float]]] = defaultdict(list)

    rated = [p.src.rating for p in items if p.src.rating]
    dist = {str(s): sum(1 for r in rated if r == s) for s in range(1, 6)}
    with_text = [p for p in items if not p.empty]

    # 1. Копии текстов -------------------------------------------------------
    groups = _find_duplicate_groups(items)
    dup_ids = {i for g in groups for i in g}
    dup_share = len(dup_ids) / len(with_text) if with_text else 0.0
    for i in dup_ids:
        per_review[i].append(("почти дословно совпадает с другим отзывом", WEIGHTS["duplicate"]))
    dup_pen = min(30.0, dup_share * 100)
    signals.append(Signal(
        code="duplicates",
        title="Копии и почти-копии текстов",
        severity="critical" if dup_share >= 0.1 else "warning" if dup_ids else "ok",
        value=round(dup_share, 3),
        penalty=round(dup_pen, 1),
        explanation=(f"{len(dup_ids)} из {len(with_text)} текстов входят в {len(groups)} групп(ы) "
                     f"почти одинаковых отзывов (сходство ≥{int(DUP_THRESHOLD * 100)}%). "
                     "Разные живые люди не пишут один и тот же текст."
                     if dup_ids else "Совпадающих текстов не найдено."),
        evidence=[" | ".join(f"#{i + 1}" for i in g[:8]) + (f" (+{len(g) - 8})" if len(g) > 8 else "")
                  for g in groups[:5]],
        reference=REFERENCES["duplicates"],
    ))

    # 2. Всплески ------------------------------------------------------------
    in_burst, episodes, base = _find_bursts(items)
    dated_n = sum(1 for p in items if p.day)
    if base is None:
        signals.append(Signal(
            code="bursts", title="Всплески отзывов по датам", severity="info",
            explanation=("Недостаточно датированных отзывов (нужно ≥10 за период ≥4 недель) — "
                         "всплески не проверялись." if dated_n < 10 else
                         "Все отзывы оставлены за период короче 4 недель — сравнивать не с чем."),
            reference=REFERENCES["bursts"]))
    else:
        pos_ids = [i for i, pol in in_burst.items() if pol == "pos"]
        neg_ids = [i for i, pol in in_burst.items() if pol == "neg"]
        burst_share = len(pos_ids) / dated_n if dated_n else 0.0
        for i in in_burst:
            label = "оставлен во время всплеска пятёрок" if in_burst[i] == "pos" else "оставлен во время волны негатива"
            per_review[i].append((label, WEIGHTS["burst"]))
        burst_pen = min(25.0, burst_share * 60)
        ev = [f"{e['start']} — {e['end']}: {e['count']} отзывов"
              + (f", положительных {int(e['pos_share'] * 100)}%" if e["pos_share"] is not None else "")
              + (" (волна негатива)" if e["polarity"] == "neg" else "")
              for e in episodes[:6]]
        expl = (f"Обычный темп (медиана) — {base:g} отз. в неделю. "
                f"{len(pos_ids)} положительных отзывов ({burst_share:.0%}) пришли во время всплесков, "
                "когда за неделю отзывов в несколько раз больше нормы. "
                "Так выглядит раздача «отзывов за скидку» или покупка пакета отзывов.")
        if not episodes:
            expl = f"Обычный темп (медиана) — {base:g} отз. в неделю, аномальных всплесков нет."
        elif neg_ids and not pos_ids:
            expl = (f"Есть волна негатива ({len(neg_ids)} отзывов). Это может быть реальный инцидент "
                    "или атака конкурентов — читайте эти отзывы внимательно.")
        signals.append(Signal(
            code="bursts", title="Всплески отзывов по датам",
            severity="critical" if burst_share >= 0.25 else "warning" if episodes else "ok",
            value=round(burst_share, 3), penalty=round(burst_pen, 1),
            explanation=expl, evidence=ev, reference=REFERENCES["bursts"]))

    # 3. Пустая похвала без конкретики ---------------------------------------
    generic_ids = [p.idx for p in items if p.generic]
    generic_share = len(generic_ids) / len(with_text) if with_text else 0.0
    for i in generic_ids:
        per_review[i].append(("только общие восторги, ни одной детали лечения", WEIGHTS["generic"]))
    gen_pen = min(15.0, max(0.0, generic_share - 0.5) * 50)
    signals.append(Signal(
        code="generic", title="Похвала без единой детали",
        severity="warning" if generic_share > 0.6 else "info" if generic_share > 0.5 else "ok",
        value=round(generic_share, 3), penalty=round(gen_pen, 1),
        explanation=(f"{len(generic_ids)} из {len(with_text)} текстов ({generic_share:.0%}) — только "
                     "«лучшая клиника, всем рекомендую» без процедуры, врача, сроков или цены. "
                     "Короткие честные отзывы тоже бывают такими, поэтому сам по себе признак слабый: "
                     "штраф начинается, только если таких больше половины."),
        evidence=[f"#{i + 1}: «{(reviews[i].text or '')[:80]}»" for i in generic_ids[:4]],
        reference=REFERENCES["specificity"]))

    # 4. Одноразовые аккаунты ------------------------------------------------
    known = [p for p in items if p.src.author_reviews_count is not None]
    if len(known) >= max(5, n // 2):
        singles = [p.idx for p in known if p.src.author_reviews_count <= 1]
        single_share = len(singles) / len(known)
        for i in singles:
            per_review[i].append(("у автора это единственный отзыв на площадке", WEIGHTS["singleton"]))
        # Абсолютная доля одноразовых авторов зависит от площадки, поэтому главное —
        # сравнить её у пятёрок и у остальных оценок того же списка.
        fives = [p for p in known if p.src.rating == 5]
        others = [p for p in known if p.src.rating is not None and p.src.rating < 5]
        s5 = sum(1 for p in fives if p.src.author_reviews_count <= 1) / len(fives) if fives else 0.0
        so = sum(1 for p in others if p.src.author_reviews_count <= 1) / len(others) if others else None
        skew = (s5 - so) if so is not None and len(others) >= 5 and len(fives) >= 10 else None
        single_pen = min(10.0, max(0.0, single_share - 0.6) * 40)
        if skew is not None and skew >= 0.15:
            single_pen += min(15.0, skew * 40)
        ev = [f"Одноразовых авторов среди пятёрок: {s5:.0%}"]
        if so is not None:
            ev.append(f"Одноразовых авторов среди оценок 1–4★: {so:.0%}")
        signals.append(Signal(
            code="singletons", title="Авторы с единственным отзывом",
            severity="warning" if single_pen >= 5 else "ok",
            value=round(single_share, 3), penalty=round(single_pen, 1),
            explanation=(f"{single_share:.0%} авторов больше ничего не оценивали. "
                         + (f"Среди пятёрок таких на {skew:.0%} больше, чем среди остальных оценок — "
                            "похоже, что положительные отзывы пишут специально созданные аккаунты. "
                            if skew is not None and skew >= 0.15 else
                            "Перекоса между пятёрками и остальными оценками нет. ")
                         + "Аккаунты «на один отзыв» — самый сильный поведенческий признак в фильтре Yelp."),
            evidence=ev, reference=REFERENCES["behavior"]))
    else:
        signals.append(Signal(
            code="singletons", title="Авторы с единственным отзывом", severity="info",
            explanation="Не указано, сколько отзывов у каждого автора — признак не проверялся. "
                        "В 2ГИС это видно под именем автора.",
            reference=REFERENCES["behavior"]))

    # 5. Закапывание негатива ------------------------------------------------
    buried, bury_ev = _find_burying(items)
    for i in buried:
        per_review[i].append(("пришёл сразу после негативного отзыва в пачке пятёрок", WEIGHTS["burying"]))
    bury_pen = min(15.0, 5.0 * len(bury_ev))
    signals.append(Signal(
        code="burying", title="Пятёрки «засыпают» негатив",
        severity="warning" if bury_ev else "ok", value=float(len(bury_ev)), penalty=bury_pen,
        explanation=(f"{len(bury_ev)} раз(а) после плохого отзыва в течение 3 дней появлялись 3+ пятёрки — "
                     "классический приём, чтобы негатив ушёл вниз ленты." if bury_ev else
                     "После негативных отзывов волн пятёрок не обнаружено."),
        evidence=bury_ev[:5], reference=REFERENCES["behavior"]))

    # 6. Распределение оценок ------------------------------------------------
    if len(rated) >= 30:
        share5 = dist["5"] / len(rated)
        mid = (dist["2"] + dist["3"] + dist["4"]) / len(rated)
        pen = 10.0 if share5 >= 0.97 else 5.0 if share5 >= 0.93 else 0.0
        signals.append(Signal(
            code="distribution", title="Форма распределения оценок",
            severity="warning" if pen else "ok", value=round(share5, 3), penalty=pen,
            explanation=(f"Пятёрок {share5:.0%}, средних оценок (2–4★) {mid:.0%}. "
                         + ("Почти полное отсутствие не-пятёрок при таком объёме статистически нетипично "
                            "для медицины: даже у лучших клиник бывают недовольные. Это не доказательство, "
                            "но повод проверить остальные признаки." if pen else
                            "Распределение похоже на естественное.")),
            reference=REFERENCES["distribution"]))

    # 7. Данные самой площадки ----------------------------------------------
    flagged_by_platform = [p.idx for p in items if p.src.confirmed is False]
    for i in flagged_by_platform:
        per_review[i].append(("площадка сама пометила отзыв как неподтверждённый", WEIGHTS["unconfirmed"]))
    unconf_share = None
    if aggregate and aggregate.unconfirmed_count is not None and aggregate.ratings_count:
        unconf_share = aggregate.unconfirmed_count / (aggregate.ratings_count + aggregate.unconfirmed_count)
    elif any(p.src.confirmed is not None for p in items):
        unconf_share = len(flagged_by_platform) / n if n else 0.0
    if unconf_share is not None:
        pen = min(25.0, unconf_share * 100)
        signals.append(Signal(
            code="platform_flags", title="Отзывы, которые площадка сочла сомнительными",
            severity="critical" if unconf_share >= 0.1 else "warning" if unconf_share > 0.02 else "ok",
            value=round(unconf_share, 3), penalty=round(pen, 1),
            explanation=(f"{unconf_share:.0%} отзывов 2ГИС перенёс в «Неподтверждённые». Это прямое "
                         "свидетельство попытки накрутки, найденное антифродом площадки."),
            reference=REFERENCES["2gis"]))

    # 8. Расхождение площадок ------------------------------------------------
    if aggregate and aggregate.rating and aggregate.other_platforms:
        gaps = []
        for other in aggregate.other_platforms:
            if other.volume >= 10:
                gaps.append((other.platform, round(aggregate.rating - other.rating, 2), other.volume))
        if gaps:
            worst = max(gaps, key=lambda g: g[1])
            pen = 15.0 if worst[1] >= 0.7 else 8.0 if worst[1] >= 0.4 else 0.0
            signals.append(Signal(
                code="cross_platform", title="Сравнение с другими площадками",
                severity="warning" if pen else "ok", value=worst[1], penalty=pen,
                explanation=(f"На {aggregate.platform} рейтинг выше, чем на {worst[0]}, на {worst[1]}★. "
                             "Если на одной площадке клиника заметно «лучше», чем на других, накрутка "
                             "вероятнее всего именно там." if pen else
                             "Рейтинги на разных площадках согласуются."),
                evidence=[f"{p}: разница {g:+}★ ({v} оценок)" for p, g, v in gaps],
                reference=REFERENCES["cross_platform"]))

    # Итоги по отдельным отзывам ---------------------------------------------
    flags: List[ReviewFlags] = []
    suspicious = set()
    for i, reasons in per_review.items():
        score = min(1.0, sum(w for _, w in reasons))
        # Конкретика (процедура, врач, сроки, цена) дорога для заказного отзыва — немного снижает подозрение.
        if items[i].specific >= 3 and score < 1.0:
            score = max(0.0, score - SPECIFIC_RELIEF)
            reasons = reasons + [("есть конкретные детали лечения — это снижает подозрение", -SPECIFIC_RELIEF)]
        if score >= SUSPICIOUS_AT:
            suspicious.add(i)
        flags.append(ReviewFlags(
            index=i + 1, author=reviews[i].author, date=reviews[i].date, rating=reviews[i].rating,
            excerpt=(reviews[i].text or "")[:160], suspicion=round(score, 2),
            reasons=[r for r, _ in reasons]))
    flags.sort(key=lambda f: -f.suspicion)

    raw_mean = round(mean(rated), 2) if rated else None
    clean = [items[i].src.rating for i in range(n) if i not in suspicious and items[i].src.rating]
    clean_mean = round(mean(clean), 2) if clean else None

    total_pen = sum(s.penalty for s in signals)
    index = round(max(0.0, 100.0 - total_pen), 1)

    if n < 10:
        verdict, text = "insufficient_data", ("Слишком мало отзывов для статистических выводов. "
                                              "Признаки ниже — только ориентир.")
    elif index >= 75:
        verdict, text = "organic", "Явных признаков накрутки не найдено."
    elif index >= 50:
        verdict, text = "some_signals", "Есть отдельные признаки накрутки — читайте отмеченные отзывы критически."
    else:
        verdict, text = "strong_signals", "Сильные признаки накрутки: значительная часть отзывов похожа на заказные."

    checked = sum(1 for s in signals if s.severity != "info")
    confidence = "высокая" if n >= 50 and checked >= 5 else "средняя" if n >= 20 and checked >= 3 else "низкая"

    return ReviewAnalysis(
        total=n, analyzed_with_dates=dated_n, authenticity_index=index, verdict=verdict,
        verdict_text=text, confidence=confidence, rating_distribution=dist,
        raw_mean_rating=raw_mean, cleaned_mean_rating=clean_mean, cleaned_count=len(clean),
        suspicious_count=len(suspicious), signals=signals,
        suspicious_reviews=[f for f in flags if f.suspicion >= 0.3][:100],
    )
