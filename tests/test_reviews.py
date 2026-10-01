from datetime import date, timedelta

import pytest

from app.models import AggregateInput, RatingObservation, ReviewInput, Source
from app.verification.reviews import analyze_reviews
from tools.synthetic_reviews import FAKE_TEMPLATES, generate

TODAY = date(2026, 10, 1)


def _signal(analysis, code):
    return next(s for s in analysis.signals if s.code == code)


@pytest.mark.parametrize("seed", range(1, 9))
def test_organic_and_boosted_are_separated(seed):
    organic = analyze_reviews(generate("organic", seed=seed), today=TODAY)
    boosted = analyze_reviews(generate("fake", seed=seed), today=TODAY)
    assert organic.verdict == "organic"
    assert organic.authenticity_index >= 85
    assert boosted.verdict == "strong_signals"
    assert boosted.authenticity_index <= 45
    assert boosted.authenticity_index < organic.authenticity_index - 40


def test_injected_fakes_are_flagged_with_few_false_positives():
    reviews = generate("fake", seed=3)
    analysis = analyze_reviews(reviews, today=TODAY)
    flagged = {f.index - 1 for f in analysis.suspicious_reviews if f.suspicion >= 0.5}
    injected = {i for i, r in enumerate(reviews) if r.text in FAKE_TEMPLATES}
    organic = set(range(len(reviews))) - injected
    recall = len(flagged & injected) / len(injected)
    false_positive_rate = len(flagged & organic) / len(organic)
    assert recall >= 0.85
    assert false_positive_rate <= 0.05


def test_cleaned_rating_drops_when_fakes_removed():
    analysis = analyze_reviews(generate("fake", seed=5), today=TODAY)
    assert analysis.cleaned_mean_rating < analysis.raw_mean_rating


def test_near_duplicates_detected_despite_small_edits():
    base = "Отличная клиника, лечили зуб мудрости, доктор Азамат всё сделал быстро и без боли, спасибо"
    reviews = [ReviewInput(text=base, rating=5),
               ReviewInput(text=base.replace("быстро", "очень быстро") + "!", rating=5),
               ReviewInput(text="Ставили брекеты в прошлом году, через полгода отклеились два замка, переклеили бесплатно", rating=4)]
    dup = _signal(analyze_reviews(reviews, today=TODAY), "duplicates")
    assert dup.value == pytest.approx(2 / 3, abs=0.01)


def test_short_identical_thanks_are_not_counted_as_copies():
    reviews = [ReviewInput(text="Спасибо!", rating=5) for _ in range(12)]
    assert _signal(analyze_reviews(reviews, today=TODAY), "duplicates").value == 0


def test_burst_detected_against_median_baseline():
    start = date(2025, 1, 6)
    reviews = [ReviewInput(text=f"Лечили кариес, пломба держится уже {w} недель", rating=5,
                           date=(start + timedelta(weeks=w)).isoformat()) for w in range(30)]
    reviews += [ReviewInput(text=f"Отзыв номер {i} про чистку и снимок", rating=5,
                            date=(start + timedelta(weeks=20, days=i % 3)).isoformat()) for i in range(15)]
    bursts = _signal(analyze_reviews(reviews, today=TODAY), "bursts")
    assert bursts.severity in ("warning", "critical")
    assert bursts.value > 0.25


def test_burying_negative_reviews():
    d = date(2025, 5, 10)
    reviews = [ReviewInput(text="Пломба выпала через неделю", rating=1, date=d.isoformat())]
    reviews += [ReviewInput(text=f"Супер {i}", rating=5, date=(d + timedelta(days=1)).isoformat()) for i in range(4)]
    burying = _signal(analyze_reviews(reviews, today=TODAY), "burying")
    assert burying.value == 1


def test_small_sample_is_reported_as_insufficient():
    analysis = analyze_reviews([ReviewInput(text="Хорошо", rating=5)] * 3, today=TODAY)
    assert analysis.verdict == "insufficient_data"


def test_platform_unconfirmed_share_penalised():
    reviews = generate("organic", seed=2)
    agg = AggregateInput(rating=4.8, ratings_count=200, unconfirmed_count=40)
    pf = _signal(analyze_reviews(reviews, agg, today=TODAY), "platform_flags")
    assert pf.severity == "critical"
    assert pf.penalty > 10


def test_cross_platform_gap_penalised():
    other = RatingObservation(platform="google", rating=4.1, ratings_count=80,
                              source=Source(url="https://example.org", observed="2026-10-01", via="manual_check"))
    agg = AggregateInput(rating=4.9, ratings_count=300, other_platforms=[other])
    cp = _signal(analyze_reviews(generate("organic", seed=4), agg, today=TODAY), "cross_platform")
    assert cp.penalty == 15


def test_singleton_skew_toward_five_stars():
    reviews = [ReviewInput(text=f"Отзыв {i} про лечение канала", rating=5, author_reviews_count=1) for i in range(20)]
    reviews += [ReviewInput(text=f"Отзыв {i} про коронку", rating=3, author_reviews_count=10) for i in range(10)]
    sig = _signal(analyze_reviews(reviews, today=TODAY), "singletons")
    assert sig.severity == "warning"
