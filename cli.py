import sys
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.prompt import Prompt, Confirm, IntPrompt
from rich.text import Text
from rich import print as rprint

from app.database import db
from app.ranking import rank_dentists, calculate_mean_rating, calculate_bayesian_rating
from app.models import SmartMatchRequest

console = Console()

def print_header():
    console.print(Panel.fit(
        "[bold cyan]🦷 СТОМАТОЛОГ БИШКЕК — УМНЫЙ ПОИСК ЛУЧШЕГО ВРАЧА[/bold cyan]\n"
        "[dim]Интеллектуальная система подбора и рейтингов на основе отзывов 2ГИС и YDoc[/dim]",
        border_style="cyan"
    ))

def display_dentists_table(dentists):
    if not dentists:
        console.print("[yellow]Стоматологи по заданным критериям не найдены.[/yellow]")
        return

    global_mean = calculate_mean_rating(db.get_all())
    table = Table(title="🏆 Топ стоматологических клиник и врачей в Бишкеке", show_header=True, header_style="bold magenta")
    table.add_column("#", style="dim", width=3)
    table.add_column("Врач / Специалист", style="bold white", width=24)
    table.add_column("Клиника", style="cyan", width=22)
    table.add_column("Рейтинг", justify="center", style="yellow", width=12)
    table.add_column("Байес. балл", justify="center", style="bold green", width=11)
    table.add_column("Стаж", justify="center", width=7)
    table.add_column("Район", style="dim", width=20)
    table.add_column("Специализация", width=25)

    for idx, d in enumerate(dentists, 1):
        bayesian = calculate_bayesian_rating(d, global_mean)
        rating_str = f"⭐ {d.rating} ({d.reviews_count})"
        specs_str = ", ".join(d.specializations[:2])
        table.add_row(
            str(idx),
            f"{d.photo_badge} {d.name}",
            d.clinic,
            rating_str,
            f"{bayesian:.3f}",
            f"{d.experience_years} лет",
            d.district,
            specs_str
        )

    console.print(table)

def show_dentist_details(dentist):
    global_mean = calculate_mean_rating(db.get_all())
    bayesian = calculate_bayesian_rating(dentist, global_mean)

    content = f"""
[bold cyan]Клиника:[/bold cyan] {dentist.clinic}
[bold cyan]Специалист:[/bold cyan] {dentist.photo_badge} {dentist.name} ({dentist.title})
[bold cyan]Стаж работы:[/bold cyan] {dentist.experience_years} лет
[bold cyan]Рейтинг доверия:[/bold cyan] ⭐ {dentist.rating} / 5.0 (на базе {dentist.reviews_count} отзывов 2ГИС) | Байесовский балл: [bold green]{bayesian:.3f}[/bold green]
[bold cyan]Ценовой уровень:[/bold cyan] {dentist.price_level.upper()}
[bold cyan]Режим работы:[/bold cyan] {dentist.working_hours} {'[bold red](24/7 КРУГЛОСУТОЧНО)[/bold red]' if dentist.is_24_7 else ''}
[bold cyan]Адрес:[/bold cyan] {dentist.address} ({dentist.district})
[bold cyan]Контакты:[/bold cyan] 📞 {dentist.phone} | WhatsApp: https://wa.me/{dentist.whatsapp}
[bold cyan]2GIS Ссылка:[/bold cyan] {dentist.gis_url}

[bold yellow]🎓 Высшее образование и ординатура:[/bold yellow]
"""
    if dentist.education:
        content += f"  • ВУЗ: [bold white]{dentist.education.university}[/bold white] ({dentist.education.graduation_year})\n"
        content += f"  • Квалификация: {dentist.education.degree}\n"
        if dentist.education.residency:
            content += f"  • Ординатура: {dentist.education.residency} ({dentist.education.residency_years or ''})\n"
        if dentist.education.internships:
            content += "  • Стажировки: " + "; ".join(dentist.education.internships[:2]) + "\n"

    if dentist.certifications:
        content += "\n[bold yellow]📜 Верифицированные сертификаты и лицензии:[/bold yellow]\n"
        for c in dentist.certifications:
            content += f"  ✔ [bold]{c.title}[/bold] — {c.issuer} ({c.year}) [dim][ID: {c.cert_id}][/dim]\n"

    if dentist.equipment:
        content += "\n[bold yellow]🔬 Передовое оснащение клиники:[/bold yellow]\n"
        for eq in dentist.equipment:
            content += f"  • {eq}\n"

    content += "\n[bold green]💰 Прайс-лист на процедуры (в сомах):[/bold green]\n"
    if dentist.comprehensive_prices:
        for cat, items in dentist.comprehensive_prices.items():
            content += f"  [bold cyan]▸ {cat}:[/bold cyan]\n"
            for s_name, price in list(items.items())[:3]:
                content += f"    • {s_name}: [bold green]{price:,} сом[/bold green]\n"
    else:
        for s_name, price in dentist.services.items():
            content += f"  • {s_name}: [bold green]{price:,} сом[/bold green]\n"

    if dentist.audit:
        content += "\n[bold red]⚠️ Аудит рисков и реальные жалобы пациентов (2ГИС / Форумы):[/bold red]\n"
        for rf in dentist.audit.red_flags:
            content += f"  [bold red]• Предупреждение:[/bold red] {rf}\n"
        content += "\n  [bold yellow]Реальные претензии пациентов:[/bold yellow]\n"
        for nf in dentist.audit.negative_feedback:
            content += f"  ❌ {nf}\n"
        content += f"\n  [bold green]🛡️ Совет пациенту:[/bold green] {dentist.audit.safety_advice}\n"
        content += f"\n  [dim]ℹ️ Факт-чек сертификатов: {dentist.audit.commercial_certs_note}[/dim]\n"

    content += "\n[bold magenta]💬 Последние отзывы пациентов (2ГИС):[/bold magenta]\n"
    for r in dentist.sample_reviews[:2]:
        content += f"  💬 [bold]{r.author}[/bold] ({'⭐'*r.rating}, {r.date}): \"{r.text}\"\n"

    console.print(Panel(content, title=f"📋 Профиль специалиста: {dentist.name} - {dentist.clinic}", border_style="green"))

def run_interactive_wizard():
    console.print("\n[bold cyan]🎯 Мастер умного подбора идеального стоматолога[/bold cyan]")
    console.print("[dim]Ответьте на 4 вопроса, и система вычислит лучшее совпадение.[/dim]\n")

    problems = [
        "1. Лечение кариеса, каналов, пломбирование",
        "2. Исправление прикуса (брекеты, элайнеры)",
        "3. Имплантация зубов, костная пластика",
        "4. Удаление зуба (в т.ч. сложные зубы мудрости)",
        "5. Детский стоматолог (без боли и страха)",
        "6. Эстетика, виниры, отбеливание зубов",
        "7. Срочно: острая зубная боль прямо сейчас (24/7)"
    ]
    for p in problems:
        console.print(f"  {p}")
    choice = Prompt.ask("\nВыберите вашу проблему", choices=["1", "2", "3", "4", "5", "6", "7"], default="1")
    problem_map = {
        "1": "кариес",
        "2": "брекеты",
        "3": "имплант",
        "4": "удаление",
        "5": "дети",
        "6": "виниры",
        "7": "острая боль срочно"
    }
    selected_problem = problem_map[choice]

    districts = [
        "1. Любой район Бишкека",
        "2. Центр / Первомайский",
        "3. Октябрьский / Южные микрорайоны",
        "4. 7-й микрорайон",
        "5. Асанбай",
        "6. Свердловский / Восток-5",
        "7. Ленинский"
    ]
    console.print("\n[bold]Район города:[/bold]")
    for d in districts:
        console.print(f"  {d}")
    dist_choice = Prompt.ask("Выберите район", choices=["1", "2", "3", "4", "5", "6", "7"], default="1")
    district_map = {
        "1": "Все",
        "2": "Центр / Первомайский",
        "3": "Октябрьский / Южные мкрн",
        "4": "7-й микрорайон",
        "5": "Асанбай",
        "6": "Свердловский / Восток-5",
        "7": "Ленинский"
    }
    selected_district = district_map[dist_choice]

    console.print("\n[bold]Ценовая категория:[/bold]")
    console.print("  1. Любая\n  2. Эконом (семейная доступность)\n  3. Комфорт (оптимальное соотношение)\n  4. Премиум (высокие технологии)")
    price_choice = Prompt.ask("Выберите бюджет", choices=["1", "2", "3", "4"], default="1")
    price_map = {"1": "Все", "2": "эконом", "3": "комфорт", "4": "премиум"}
    selected_price = price_map[price_choice]

    console.print("\n[bold]Главный приоритет при выборе:[/bold]")
    console.print("  1. Максимальная репутация и рейтинг врача\n  2. Выгодная стоимость\n  3. Высокие технологии (микроскоп, 3D КТ, сканер)\n  4. Близость к дому")
    prio_choice = Prompt.ask("Выберите приоритет", choices=["1", "2", "3", "4"], default="1")
    prio_map = {"1": "reputation", "2": "price", "3": "technology", "4": "proximity"}
    selected_prio = prio_map[prio_choice]

    req = SmartMatchRequest(
        problem=selected_problem,
        district=selected_district,
        price_level=selected_price,
        priority=selected_prio
    )

    all_dentists = db.get_all()
    ranked = rank_dentists(all_dentists, req)

    console.print("\n" + "="*60)
    console.print(f"[bold green]🏆 РЕЗУЛЬТАТ ПОДБОРА: ТОП РЕКОМЕНДАЦИЙ ДЛЯ ВАС[/bold green]")
    console.print("="*60 + "\n")

    top3 = ranked[:3]
    for idx, match in enumerate(top3, 1):
        d = match.dentist
        badge_title = f"🥇 №1 САМЫЙ ЛУЧШИЙ ВЫБОР ({match.score}% СОВПАДЕНИЕ)" if idx == 1 else f"🥈 Вариант #{idx} ({match.score}% совпадение)"
        
        info = f"""
[bold white]{d.name}[/bold white] — [cyan]{d.clinic}[/cyan] ({d.title})
📍 {d.address} ({d.district})
⭐ Рейтинг: {d.rating} ({d.reviews_count} отзывов) | Опыт: {d.experience_years} лет
💰 Уровень цен: {d.price_level.upper()} | 📞 Тел: {d.phone}

[bold yellow]Почему подходит именно вам:[/bold yellow]
"""
        for r in match.reasons:
            info += f"  ✔ {r}\n"

        info += f"\n👉 Записаться в WhatsApp: [link=https://wa.me/{d.whatsapp}?text=Здравствуйте!_Хочу_записаться_через_рекомендацию_стоматолога]wa.me/{d.whatsapp}[/link]"

        console.print(Panel(info, title=badge_title, border_style="gold1" if idx == 1 else "blue"))

def show_antifake_guide():
    guide = """
[bold yellow]1. Разница между дипломом ВУЗа и сертификатом семинара:[/bold yellow]
  • Красивые сертификаты на английском языке с гербами и логотипами брендов (Straumann, Osstem, Damon) — это подтверждение посещения [bold]2-3 дневных коммерческих мастер-классов[/bold] от производителей.
  • Они не дают права проводить хирургические операции, если у врача нет диплома государственного медицинского ВУЗа (КГМА/КРСУ) и государственной клинической ординатуры.

[bold yellow]2. Проверка разрешения Минздрава КР:[/bold yellow]
  • Терапевт по закону Кыргызской Республики НЕ имеет права оперировать, ставить импланты или брекеты без профильной ординатуры по хирургии/ортодонтии.
  • Всегда спрашивайте лицензию МЗ КР на данный вид помощи.

[bold yellow]3. Паспорт имплантата с заводским стикером:[/bold yellow]
  • После установки импланта клиника ОБЯЗАНА выдать пациенту паспорт с наклеенным штрих-кодом завода (Швейцария/Южная Корея).
  • Если вам не выдали паспорт с наклейкой — требуйте его немедленно, иначе есть риск установки подделки!

[bold yellow]4. Договор и кассовый чек:[/bold yellow]
  • Отсутствие чека и договора лишает вас правовой защиты при осложнениях. Не соглашайтесь на оплату «на карту врачу» без выдачи фискального чека клиники.
"""
    console.print(Panel(guide, title="🛡️ Памятка по проверке сертификатов и лицензий в Бишкеке", border_style="yellow"))

def main_cli():
    print_header()

    while True:
        console.print("\n[bold cyan]Главное меню:[/bold cyan]")
        console.print("1. 🎯 Подобрать лучшего стоматолога (Интерактивный мастер)")
        console.print("2. 📋 Показать общий рейтинг всех стоматологов Бишкека")
        console.print("3. 🔍 Поиск по названию клиники, врачу, ВУЗу или услуге")
        console.print("4. 🚑 Срочная круглосуточная стоматология (24/7)")
        console.print("5. ℹ️ Профиль врача (диплом, сертификаты, цены, жалобы)")
        console.print("6. 🛡️ Анти-фейк аудит: как проверить сертификаты и не дать себя обмануть")
        console.print("7. 🌐 Запустить Веб-интерфейс с интерактивной картой")
        console.print("0. 🚪 Выход")

        choice = Prompt.ask("\nВаш выбор", choices=["0", "1", "2", "3", "4", "5", "6", "7"], default="1")

        if choice == "0":
            console.print("[dim]До свидания! Здоровых вам улыбок![/dim]")
            sys.exit(0)
        elif choice == "1":
            run_interactive_wizard()
        elif choice == "2":
            all_dentists = db.get_all()
            display_dentists_table(all_dentists)
        elif choice == "3":
            q = Prompt.ask("Введите поисковый запрос (например: брекеты, Солошенко, КГМА, Zeiss, чистка)")
            found = db.search_and_filter(query=q)
            display_dentists_table(found)
        elif choice == "4":
            found = db.search_and_filter(only_24_7=True)
            display_dentists_table(found)
            if found:
                show_dentist_details(found[0])
        elif choice == "5":
            all_dentists = db.get_all()
            for idx, d in enumerate(all_dentists, 1):
                console.print(f"  {idx}. {d.name} ({d.clinic})")
            d_idx = IntPrompt.ask("Введите номер врача", default=1)
            if 1 <= d_idx <= len(all_dentists):
                show_dentist_details(all_dentists[d_idx - 1])
            else:
                console.print("[red]Неверный номер.[/red]")
        elif choice == "6":
            show_antifake_guide()
        elif choice == "7":
            console.print("[green]Для запуска веб-интерфейса запустите команду:[/green] [bold white]python main.py[/bold white]")
            console.print("[green]И откройте в браузере: [/green] [bold underline]http://127.0.0.1:8000[/bold underline]")

if __name__ == "__main__":
    main_cli()
