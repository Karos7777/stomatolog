"""DentBishkek: стоматологии Бишкека с доказательствами."""
import subprocess
from pathlib import Path

RELEASE = "2.2 от 04.10.2026"   # видно в подвале сайта и при запуске: так легко понять, какая версия открыта


def app_version() -> str:
    """«2.1 от 01.10.2026 · d9a2608»; без git (скачали zip) — только номер версии."""
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=Path(__file__).resolve().parent.parent,
                             capture_output=True, text=True, timeout=3).stdout.strip()
    except Exception:
        sha = ""
    return f"{RELEASE} · {sha}" if sha else RELEASE
