"""Импорт отзывов из CSV, JSON или простого текста (в т.ч. скопированного со страницы 2ГИС)."""
import csv
import io
import json
import re
from typing import Any, Dict, List, Optional

from app.models import ReviewInput
from app.verification.dates import parse_date

ALIASES = {
    "text": ("text", "текст", "отзыв", "review", "comment", "комментарий", "body"),
    "rating": ("rating", "оценка", "звезды", "звёзды", "stars", "score"),
    "date": ("date", "дата", "created", "date_created", "created_at"),
    "author": ("author", "автор", "имя", "name", "user"),
    "author_reviews_count": ("author_reviews_count", "отзывов_у_автора", "reviews_by_author",
                             "author_reviews", "user_reviews_count"),
    "confirmed": ("confirmed", "подтвержден", "подтверждён", "verified", "is_verified"),
}

_RATING_RE = re.compile(r"(?<!\d)([1-5])(?:[.,]0)?\s*(?:★|⭐|\*|/\s*5|из\s*5|звезд|звёзд|stars?)", re.I)
_AUTHOR_COUNT_RE = re.compile(r"^(\d+)\s+(?:отзыв|оценк|review)", re.I)
_DATE_TOKEN_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2}|\d{1,2}[./]\d{1,2}[./]\d{2,4}|\d{1,2}\s+[а-яё]+\s+\d{4}|сегодня|вчера)", re.I)
_NAME_LINE_RE = re.compile(r"^[A-Za-zА-Яа-яЁёӨөҮүҢң.\-' ]{2,40}$")


def _pick(row: Dict[str, Any], field: str) -> Any:
    lowered = {str(k).strip().lower(): v for k, v in row.items()}
    for alias in ALIASES[field]:
        if alias in lowered and lowered[alias] not in (None, ""):
            return lowered[alias]
    return None


def _to_int(v: Any) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(float(str(v).replace(",", ".").strip()))
    except ValueError:
        m = re.search(r"\d+", str(v))
        return int(m.group()) if m else None


def _to_bool(v: Any) -> Optional[bool]:
    if v is None:
        return None
    s = str(v).strip().lower()
    if s in ("1", "true", "да", "yes", "подтвержден", "подтверждён"):
        return True
    if s in ("0", "false", "нет", "no", "неподтвержден", "неподтверждён"):
        return False
    return None


def _row_to_review(row: Dict[str, Any]) -> ReviewInput:
    rating = _to_int(_pick(row, "rating"))
    if rating is not None and not 1 <= rating <= 5:
        rating = None
    return ReviewInput(
        text=str(_pick(row, "text") or ""),
        rating=rating,
        date=str(_pick(row, "date")) if _pick(row, "date") is not None else None,
        author=str(_pick(row, "author")) if _pick(row, "author") is not None else None,
        author_reviews_count=_to_int(_pick(row, "author_reviews_count")),
        confirmed=_to_bool(_pick(row, "confirmed")),
    )


def parse_json(raw: str) -> List[ReviewInput]:
    data = json.loads(raw)
    if isinstance(data, dict):
        data = data.get("reviews") or data.get("items") or data.get("data") or []
    return [_row_to_review(r) for r in data if isinstance(r, dict)]


def parse_csv(raw: str) -> List[ReviewInput]:
    sample = raw[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(raw), dialect=dialect)
    return [_row_to_review(r) for r in reader]


def parse_text(raw: str) -> List[ReviewInput]:
    """Блоки, разделённые пустой строкой. В блоке понимаем строки-метаданные:
    имя автора, «3 отзыва», дату и оценку («5★», «4/5»). Остальное — текст отзыва.
    """
    blocks = re.split(r"\n\s*\n", raw.strip())
    result: List[ReviewInput] = []
    for block in blocks:
        lines = [l.strip() for l in block.strip().splitlines() if l.strip()]
        if not lines:
            continue
        author = rating = date = author_count = None
        text_lines: List[str] = []
        for pos, line in enumerate(lines):
            short = len(line) <= 60
            consumed = False
            if short:
                m = _AUTHOR_COUNT_RE.match(line)
                if m and author_count is None:
                    author_count, consumed = int(m.group(1)), True
                d = _DATE_TOKEN_RE.search(line)
                if d and date is None and parse_date(d.group(1)):
                    date, consumed = d.group(1), True
                r = _RATING_RE.search(line)
                if r and rating is None:
                    rating, consumed = int(r.group(1)), True
                if (not consumed and pos == 0 and len(lines) > 1 and author is None
                        and _NAME_LINE_RE.match(line) and len(line.split()) <= 3):
                    author, consumed = line, True
            if not consumed:
                text_lines.append(line)
        result.append(ReviewInput(text=" ".join(text_lines), rating=rating, date=date,
                                  author=author, author_reviews_count=author_count))
    return result


def parse_reviews(raw: str, fmt: str = "auto") -> List[ReviewInput]:
    raw = (raw or "").strip().lstrip("﻿")
    if not raw:
        return []
    if fmt == "json" or (fmt == "auto" and raw[0] in "[{"):
        return parse_json(raw)
    if fmt == "csv" or (fmt == "auto" and _looks_like_csv(raw)):
        return parse_csv(raw)
    return parse_text(raw)


def _looks_like_csv(raw: str) -> bool:
    header = raw.splitlines()[0].lower()
    if not any(sep in header for sep in (",", ";", "\t")):
        return False
    return any(alias in header for aliases in ALIASES.values() for alias in aliases)
