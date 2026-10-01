import sys
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import socket
import webbrowser
import threading
import time
import uvicorn

from app import app_version


def free_port(start: int = 8000, tries: int = 20) -> int:
    """Первый свободный порт. Если 8000 занят старой копией сайта, новая откроется рядом, а не «молча» старая."""
    for port in range(start, start + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return start


def open_browser(url: str):
    time.sleep(1.2)
    print(f"\n[🚀] Открытие веб-интерфейса в браузере: {url}")
    webbrowser.open(url)


def main():
    if len(sys.argv) > 1 and sys.argv[1] in ["--cli", "-c", "cli"]:
        from cli import main_cli
        main_cli(sys.argv[2:])
    else:
        port = free_port()
        url = f"http://127.0.0.1:{port}"
        print("="*60)
        print("🦷 DentBishkek: стоматологии Бишкека с доказательствами")
        print("="*60)
        print(f"🔖 Версия: {app_version()} (она же внизу страницы)")
        print(f"🌐 Веб-сервер запускается на: {url}")
        if port != 8000:
            print("⚠️  Порт 8000 занят — скорее всего, там всё ещё работает СТАРАЯ копия сайта.")
            print("    Закройте старое окно терминала (или нажмите в нём Ctrl+C), чтобы не путаться.")
        print("💻 Для консольного режима запустите: python main.py --cli")
        print("="*60 + "\n")

        # Start browser in background
        threading.Thread(target=open_browser, args=(url,), daemon=True).start()

        # Start FastAPI application
        uvicorn.run("app.api:app", host="127.0.0.1", port=port, log_level="info")

if __name__ == "__main__":
    main()
