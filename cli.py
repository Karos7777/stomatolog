"""Консольная версия DentBishkek.

    python cli.py                       # рейтинг доверия
    python cli.py show emmar            # доказательства по клинике
    python cli.py match "болит зуб ночью"
    python cli.py reviews отзывы.csv    # анализ отзывов из файла
    python cli.py cert "Master of Implantology" --issuer Straumann --year 2021 --grad 2008
    python cli.py audit                 # что было не так в старой версии
"""
import argparse
import sys

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from app.database import load_legacy_audit, repo
from app.importers import parse_reviews
from app.matching import match
from app.models import CredentialCheckRequest
from app.scoring import WEIGHTS, rank
from app.verification.credentials import check_credential
from app.verification.reviews import analyze_reviews

console = Console()
FLAG_STYLE = {"green": "green", "yellow": "yellow", "red": "bold red"}
SEV_STYLE = {"ok": "green", "info": "dim", "warning": "yellow", "critical": "bold red"}


def _score_style(v):
    if v is None:
        return "dim"
    return "green" if v >= 65 else "yellow" if v >= 50 else "red"


def _flags(flags):
    return "  ".join(f"[{FLAG_STYLE.get(f['level'], 'white')}]{f['text']}[/]" for f in flags[:3])


LIC_SHORT = {"verified": "[green]найдена[/]", "probable": "[green]вероятно[/]", "address_match": "[yellow]по адресу[/]",
             "ambiguous": "[yellow]много в здании[/]", "name_other_address": "[yellow]другой адрес[/]",
             "not_found": "[red]нет в реестре[/]", "not_checked": "—"}


def cmd_ranking(args) -> None:
    console.print(Panel.fit(
        "[bold]Рейтинг доверия стоматологий Бишкека[/bold]\n"
        f"[dim]{repo.meta.get('license_note', '')}[/dim]", border_style="cyan"))
    table = Table(show_header=True, header_style="bold")
    for col, kw in (("#", {"width": 4}), ("Клиника", {}), ("Индекс", {"justify": "center"}),
                    ("Рейтинг", {"justify": "center"}), ("Оценок", {"justify": "right"}),
                    ("Лицензия МЗ", {}), ("Флаги", {})):
        table.add_column(col, **kw)
    rows = [r for r in rank(repo.all(), repo.analyses()) if args.with_multi or not r["clinic"].multi_profile]
    for r in rows[:getattr(args, "top", 30)]:
        s, c = r["score"], r["clinic"]
        ti = s["trust_index"]
        flags = [f for f in s["flags"] if f["level"] != "green"]
        table.add_row(str(r["position"] or "—"), f"{c.name}\n[dim]{c.address}[/dim]",
                      f"[{_score_style(ti)}]{ti if ti is not None else 'нет данных'}[/]",
                      f"{s['rating']:g}★" if s["rating"] is not None else "—", str(s["volume"] or "—"),
                      LIC_SHORT[c.license.status], _flags(flags))
    console.print(table)
    console.print(f"[dim]Показано {min(len(rows), getattr(args, 'top', 30))} из {len(rows)}. "
                  "Индекс = " + " + ".join(f"{int(w * 100)}% {k}" for k, w in WEIGHTS.items())
                  + ". Подробно: python cli.py show <id>[/dim]")


def cmd_show(args) -> None:
    rows = rank(repo.all(), repo.analyses())
    r = next((x for x in rows if x["clinic"].id == args.clinic_id), None)
    if not r:
        console.print(f"[red]Нет клиники «{args.clinic_id}»[/red]")
        return
    c, s = r["clinic"], r["score"]
    console.print(Panel.fit(f"[bold]{c.name}[/bold]\n{c.address}\n{' · '.join(c.phones)}\n{c.gis_url or ''}",
                            border_style="cyan"))
    console.print(f"Индекс доверия: [{_score_style(s['trust_index'])}]{s['trust_index']}[/] · достоверность данных: {s['confidence']}")
    for key, comp in s["components"].items():
        console.print(f"\n[bold]{key}[/bold]: [{_score_style(comp['score'])}]{comp['score']}[/]")
        for reason in comp["reasons"]:
            console.print(f"  • {reason}")
    if c.ratings:
        t = Table(title="Откуда рейтинг", header_style="bold")
        for col in ("Площадка", "★", "Оценок", "Отзывов", "Способ", "Дата", "Источник"):
            t.add_column(col)
        for o in c.ratings:
            t.add_row(o.platform, f"{o.rating:g}", str(o.ratings_count or "—"), str(o.reviews_count or "—"),
                      o.source.via, o.source.observed, o.source.url)
        console.print(t)
    for check in s["components"]["credentials"]["checks"]:
        v = check["verdict"]
        console.print(f"\n[bold]{check['doctor']}[/bold] — «{check['claim']}»: [yellow]{v['verdict']}[/yellow]")
        console.print(f"  Доказывает: {v['proves']}\n  Не доказывает: {v['does_not_prove']}")
    lic = c.license
    console.print(f"\n[bold]Лицензия МЗ КР:[/bold] {lic.label}")
    for m in lic.matches:
        console.print(f"  {m.number} — {m.holder}, {m.address}, выдана {m.issued}; виды помощи: {', '.join(m.scope) or '—'}")
    if lic.scope_gaps:
        console.print(f"  [yellow]Нет в тексте лицензии: {', '.join(lic.scope_gaps)}[/]")
    for u in lic.unlicensed_at_address:
        console.print(f"  [bold red]МЗ: без лицензии по этому адресу — {u['name']} ({u['address']})[/]")
    for n in c.notes:
        console.print(f"[dim]• {n}[/dim]")


def cmd_match(args) -> None:
    res = match(rank(repo.all(), repo.analyses()), args.problem, args.now)
    console.print(f"Распознано: {', '.join(res['topics']) or 'направление не распознано'}"
                  + (" · только 24/7" if res["need_24_7"] else ""))
    for i, r in enumerate(res["results"][:7], 1):
        console.print(f"[bold]{i}. {r['clinic'].name}[/bold] — соответствие {r['fit']} "
                      f"(индекс {r['score']['trust_index']}) [dim]{r['clinic'].address}[/dim]")
        for reason in r["reasons"]:
            console.print(f"   • {reason}")


def cmd_reviews(args) -> None:
    with open(args.file, encoding="utf-8") as f:
        reviews = parse_reviews(f.read())
    a = analyze_reviews(reviews)
    console.print(Panel.fit(f"[bold]Индекс подлинности: [{_score_style(a.authenticity_index)}]{a.authenticity_index}[/][/bold]\n"
                            f"{a.verdict_text}\nОтзывов: {a.total} · подозрительных: {a.suspicious_count} · "
                            f"рейтинг {a.raw_mean_rating} → {a.cleaned_mean_rating} без них", border_style="cyan"))
    for sig in a.signals:
        console.print(f"[{SEV_STYLE[sig.severity]}]■ {sig.title}[/] (−{sig.penalty}) {sig.explanation}")
        for e in sig.evidence[:3]:
            console.print(f"    [dim]{e}[/dim]")


def cmd_cert(args) -> None:
    v = check_credential(CredentialCheckRequest(
        title=args.title, issuer=args.issuer, year=args.year, document_id=args.id,
        holder_graduation_year=args.grad, holder_experience_years=args.exp, holder_specialty=args.specialty,
        evidence_level=args.level))
    console.print(Panel.fit(f"[bold]{v.verdict}[/bold] — {v.claim_type_label}\n{v.evidence_label}", border_style="cyan"))
    console.print(f"Доказывает: {v.proves}\nНе доказывает: {v.does_not_prove}")
    for f in v.red_flags:
        console.print(f"[bold red]✖ {f}[/]")
    for w in v.warnings:
        console.print(f"[yellow]! {w}[/]")
    for h in v.how_to_verify:
        console.print(f"→ {h}")
    for link in v.verify_links:
        console.print(f"  {link['title']}: {link['url']}")


def cmd_audit(_args) -> None:
    a = load_legacy_audit()
    console.print(Panel.fit(a["summary"], border_style="red"))
    for e in a["entries"]:
        console.print(f"[bold]{e['name']}[/bold] — [yellow]{a['verdict_labels'][e['verdict']]}[/yellow]")
        for issue in e["issues"]:
            console.print(f"   • {issue}")


def main_cli(argv=None) -> None:
    ap = argparse.ArgumentParser(description="DentBishkek: стоматологии Бишкека с доказательствами")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("ranking")
    p.add_argument("--top", type=int, default=30); p.add_argument("--with-multi", action="store_true")
    p = sub.add_parser("show"); p.add_argument("clinic_id")
    p = sub.add_parser("match"); p.add_argument("problem"); p.add_argument("--now", action="store_true", help="нужно 24/7")
    p = sub.add_parser("reviews"); p.add_argument("file")
    p = sub.add_parser("cert")
    p.add_argument("title"); p.add_argument("--issuer"); p.add_argument("--year", type=int); p.add_argument("--id")
    p.add_argument("--grad", type=int, help="год окончания вуза"); p.add_argument("--exp", type=int, help="заявленный стаж")
    p.add_argument("--specialty"); p.add_argument("--level", type=int, default=1, choices=[0, 1, 2, 3, 4])
    sub.add_parser("audit")
    args = ap.parse_args(argv)
    if args.cmd is None:
        args.top, args.with_multi = 30, False
    {"show": cmd_show, "match": cmd_match, "reviews": cmd_reviews, "cert": cmd_cert,
     "audit": cmd_audit}.get(args.cmd, cmd_ranking)(args)


if __name__ == "__main__":
    main_cli()
