"""Собрать стоматологов Бишкека с YDoc (ydoc.kg): образование, проверенные документы, отзывы.

    python -m tools.crawl_ydoc            # все анкеты стоматологов, 1 запрос в секунду
    python -m tools.crawl_ydoc --reuse    # не скачивать заново анкеты, которые уже есть в data/ydoc_doctors.json

Что берём с каждой публичной анкеты врача:
  • специальности и стаж;
  • образование (вуз, год, специальность, тип: базовое / ординатура / курсы) и отметку
    YDoc «Документы проверены» — площадка сверяет сканы дипломов;
  • места работы (название, адрес, координаты) — по ним врач привязывается к клинике из 2ГИС;
  • отзывы: дата, оценка и как YDoc их подтвердил (запись на приём, звонок пациенту).
    Тексты отзывов не сохраняем — их на YDoc часто записывает колл-центр со слов пациента.
"""
import argparse
import html
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path
from typing import Callable, Dict, List, Optional

BASE = "https://ydoc.kg"
LIST_URL = BASE + "/bishkek/{slug}/?page={page}"
# Общий список «Стоматолог» содержит только врачей с этим тегом. Врачи, у которых указано лишь «Детский стоматолог»,
# «Стоматолог-ортодонт» или «Стоматолог-эндодонтист», в нём не появляются, поэтому обходим списки по каждой специальности.
# «ortoped» (без «стоматолог») не берём: там травматологи-ортопеды, а не стоматологи.
LIST_SLUGS = ("stomatolog", "detskiy-stomatolog", "ortodont", "stomatolog-hirurg", "stomatolog-implantolog",
              "stomatolog-ortoped", "stomatolog-endodontist", "stomatolog-gigienist", "chelyustno-licevoy-hirurg",
              "paradontolog", "gnatolog", "detskiy-ortodont", "detskiy-stomatolog-ortoped", "detskiy-stomatolog-hirurg",
              "detskiy-chelyustno-licevoy-hirurg", "detskiy-paradontolog")
OUT = Path(__file__).resolve().parent.parent / "data" / "ydoc_doctors.json"
UA = "DentBishkek/2.0 (personal non-commercial research; github.com/Karos7777/stomatolog)"


def _get(url: str, opener: Callable = urllib.request.urlopen) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with opener(req, timeout=40) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).replace("​", "").strip()


def doctor_links(list_html: str) -> List[str]:
    return list(dict.fromkeys(re.findall(r'href="(/bishkek/vrach/[^"#?]+/)', list_html)))


def _verified(page: str) -> Dict[str, Optional[bool]]:
    m = re.search(r'data-documents-verified-open="([^"]+)"', page)
    if not m:
        return {"education": False, "category": False, "science": False, "category_expires": None}
    raw = html.unescape(m.group(1))

    def flag(name):
        f = re.search(name + r":\s*(true|false)", raw)
        return bool(f and f.group(1) == "true")
    exp = re.search(r"categoryExpiresDate:\s*'([^']*)'", raw)
    return {"education": flag("isEducationConfirmed"), "category": flag("isCategoryConfirmed"),
            "science": flag("isScienceConfirmed"), "category_expires": (exp.group(1) or None) if exp else None}


def _educations(page: str) -> List[Dict]:
    block = re.search(r'id=educations>(.*?)(?:id=rating|id=otzivi|id=documents)', page, re.S)
    if not block:
        return []
    out = []
    for item in re.finditer(r'b-doctor-details__data-title[^>]*>(.*?)</div>.*?b-doctor-details__item-description[^>]*>(.*?)</div></div>',
                            block.group(1), re.S):
        desc = item.group(2)
        parts = [_text(p) for p in re.findall(r'<div class="text-body-\d[^"]*"[^>]*>(.*?)(?=</div>|$)', desc, re.S)]
        year = next((int(p) for p in parts if re.fullmatch(r"(19|20)\d\d", p)), None)
        rest = [p for p in parts if not re.fullmatch(r"(19|20)\d\d", p)]
        # Значок diplom-blue.png стоит у ЛЮБОГО базового образования — это не отметка о проверке.
        # Что проверено, видно только из блока «Документы проверены» (_verified, _document_types).
        out.append({"institution": _text(item.group(1)), "year": year,
                    "specialty": rest[0] if len(rest) > 1 else None,
                    "kind": rest[-1] if rest else None})
    return out


def _workplaces(page: str) -> List[Dict]:
    m = re.search(r":lpu-address-list='(.*?)'\s", page, re.S)
    if not m:
        return []
    try:
        data = json.loads(html.unescape(m.group(1)))
    except json.JSONDecodeError:
        return []
    out = []
    for w in data:
        lpu = w.get("lpu") or {}
        specs = sorted({(wp.get("spec") or {}).get("name") for wp in w.get("workplaces", []) if wp.get("spec")})
        out.append({"lpu_id": w.get("lpu_id"), "name": lpu.get("name"), "address": (w.get("address") or "").replace("​", ""),
                    "lat": w.get("lat"), "lng": w.get("lon"), "specialties": specs,
                    "price_from": (w.get("tabs_data") or {}).get("price")})
    return out


def _reviews(page: str) -> List[Dict]:
    out = []
    for card in re.finditer(r'<div class="b-review-card [^"]*" data-review-id=(\d+)(.*?)(?=<div class="b-review-card |id=documents|$)', page, re.S):
        body = card.group(2)
        when = re.search(r'content=(\d{4}-\d{2}-\d{2}) itemprop=datePublished', body)
        value = re.search(r'<meta content=(\d+) itemprop=ratingValue>', body)
        statuses = re.search(r':verification-statuses="\[(.*?)\]"', body, re.S)
        origin = re.search(r'review-origin=(\w+)', body)
        out.append({
            "id": card.group(1),
            "date": when.group(1) if when else None,
            "rating": round(int(value.group(1)) / 20) if value else None,
            "verified": "Отзыв проверен" in body,
            "verification": [_text(s) for s in re.findall(r"'([^']+)'", html.unescape(statuses.group(1)))] if statuses else [],
            "origin": origin.group(1) if origin else None,
            "negative": "b-review-card_negative" in card.group(0)[:200],
        })
    return out


def _intro(page: str) -> str:
    """Шапка анкеты: от имени врача до «Обновлено» — чтобы не зацепить врачей из боковых блоков."""
    start = page.find("<h1>")
    end = page.find("Обновлено", start)
    return page[start:end if end > start else start + 20000] if start >= 0 else ""


def parse_profile(page: str, url: str) -> Dict:
    intro = _intro(page)
    name = re.search(r"<h1><span[^>]*itemprop=name>\s*([^<]+?)\s*<", page)
    title = re.search(r"<title>([^,<]+)", page)
    exp = re.search(r"Стаж (\d+) (?:год|года|лет)", intro)
    specs = [_text(s) for s in re.findall(r'class="?b-doctor-intro__spec[^>]*>(.*?)</a>', intro, re.S)]
    agg_count = re.search(r'itemprop=ratingCount[^>]*content="?(\d+)|content="?(\d+)"? itemprop=ratingCount', page)
    docs_block = page[page.find("id=documents"):] if "id=documents" in page else ""
    doc_types = re.findall(r'<div class="text-body-1 text--text text-center">([^<]+)</div>', docs_block)
    doc_types += re.findall(r'b-popup-gallery__preview" title="([^"]+)"', docs_block)
    updated = re.search(r"Обновлено (\d{2}\.\d{2}\.\d{4})", page)
    workplaces = _workplaces(page)
    return {
        "url": BASE + url if url.startswith("/") else url,
        "name": _text(name.group(1)) if name else (title.group(1).strip() if title else None),
        "specialties": [s[:1].upper() + s[1:] for s in specs] or sorted({s for w in workplaces for s in w["specialties"]}),
        "experience_years": int(exp.group(1)) if exp else None,
        "documents_verified": _verified(intro or docs_block),
        "education": _educations(page),
        "document_types": sorted(set(d.strip() for d in doc_types if d.strip())),
        "hidden_documents": docs_block.count("Врач скрыл документ"),
        "workplaces": workplaces,
        "reviews": _reviews(page),
        "rating_count": int(next(g for g in agg_count.groups() if g)) if agg_count else None,
        "profile_updated": updated.group(1) if updated else None,
    }


def list_links(slug: str, opener: Callable, pause: float, max_pages: int) -> List[str]:
    links: List[str] = []
    for page in range(1, max_pages + 1):
        try:
            found = doctor_links(_get(LIST_URL.format(slug=slug, page=page), opener))
        except urllib.error.HTTPError as exc:
            if exc.code == 404:   # у специальности нет такого списка или страницы закончились
                break
            raise
        new = [l for l in found if l not in links]
        if not new:
            break
        links += new
        time.sleep(pause)
    return links


def crawl(opener: Callable = urllib.request.urlopen, pause: float = 1.0, max_pages: int = 40,
          known: Optional[Dict[str, Dict]] = None, slugs=LIST_SLUGS) -> List[Dict]:
    """known — уже скачанные анкеты по полному URL: их не запрашиваем повторно."""
    known = known or {}
    links: List[str] = []
    for slug in slugs:
        before = len(links)
        links += [l for l in list_links(slug, opener, pause, max_pages) if l not in links]
        print(f"  {slug}: +{len(links) - before} (всего {len(links)})", file=sys.stderr)
    doctors, fresh = [], 0
    for i, link in enumerate(links, 1):
        if BASE + link in known:
            doctors.append(known[BASE + link])
            continue
        try:
            doctors.append(parse_profile(_get(BASE + link, opener), link))
        except Exception as exc:  # noqa: BLE001 — одна битая анкета не должна останавливать сбор
            print(f"  ! {link}: {exc}", file=sys.stderr)
        fresh += 1
        if fresh % 50 == 0:
            print(f"  скачано {fresh}, просмотрено {i}/{len(links)}", file=sys.stderr)
        time.sleep(pause)
    return doctors


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pause", type=float, default=1.0, help="пауза между запросами, сек")
    ap.add_argument("--reuse", action="store_true", help="не скачивать заново анкеты из data/ydoc_doctors.json")
    args = ap.parse_args(argv)
    known = {}
    if args.reuse and OUT.exists():
        known = {d["url"]: d for d in json.loads(OUT.read_text(encoding="utf-8"))["doctors"]}
    doctors = crawl(pause=args.pause, known=known)
    OUT.write_text(json.dumps({"meta": {"source": "https://ydoc.kg/bishkek/ (списки по специальностям стоматологии)",
                                        "fetched": date.today().isoformat(), "doctors": len(doctors)},
                               "doctors": doctors}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"Собрано {len(doctors)} анкет → {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
