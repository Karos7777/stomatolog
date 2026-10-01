import sys
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from app.database import db
from app.ranking import rank_dentists
from app.models import SmartMatchRequest

cases = [
    ("брекеты", "Ортодонтия"),
    ("имплант", "Имплантация"),
    ("дети", "Детская стоматология"),
    ("острая боль срочно ночью", "Скорая помощь 24/7"),
    ("виниры", "Эстетика / Виниры"),
    ("кариес", "Терапия / Кариес")
]

print("=== ТЕСТИРОВАНИЕ АЛГОРИТМА ПОИСКА СТОМАТОЛОГА ===")
for p, desc in cases:
    res = rank_dentists(db.get_all(), SmartMatchRequest(problem=p))
    top = res[0]
    print(f"[{desc}] '{p}' -> №1: {top.dentist.name} ({top.dentist.clinic}) | Match: {top.score}%")
    for r in top.reasons[:2]:
        print(f"   ✔ {r}")
