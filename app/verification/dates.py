import re
from datetime import date, datetime, timedelta
from typing import Optional

_MONTHS = {
    "январ": 1, "феврал": 2, "март": 3, "апрел": 4, "ма": 5, "июн": 6,
    "июл": 7, "август": 8, "сентябр": 9, "октябр": 10, "ноябр": 11, "декабр": 12,
}
_RU_DATE = re.compile(r"(\d{1,2})\s+([а-яё]+)\s+(\d{4})", re.IGNORECASE)


def parse_date(value: Optional[str], today: Optional[date] = None) -> Optional[date]:
    """Понимает 2026-03-12, 12.03.2026, 12/03/2026, «12 марта 2026», «сегодня», «вчера»."""
    if not value:
        return None
    s = value.strip().lower()
    today = today or date.today()
    if s == "сегодня":
        return today
    if s == "вчера":
        return today - timedelta(days=1)
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S", "%d.%m.%y"):
        try:
            return datetime.strptime(s[:19] if "t" in s else s, fmt).date()
        except ValueError:
            continue
    m = _RU_DATE.search(s)
    if m:
        day, month_word, year = int(m.group(1)), m.group(2), int(m.group(3))
        # «мая»/«май» — короткий корень «ма» проверяем последним, чтобы не съесть «март»
        for stem, num in sorted(_MONTHS.items(), key=lambda kv: -len(kv[0])):
            if month_word.startswith(stem):
                try:
                    return date(year, num, day)
                except ValueError:
                    return None
    return None
