import sys
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import webbrowser
import threading
import time
import uvicorn

def open_browser():
    time.sleep(1.2)
    url = "http://127.0.0.1:8000"
    print(f"\n[🚀] Открытие веб-интерфейса в браузере: {url}")
    webbrowser.open(url)

def main():
    if len(sys.argv) > 1 and sys.argv[1] in ["--cli", "-c", "cli"]:
        from cli import main_cli
        main_cli()
    else:
        print("="*60)
        print("🦷 СТОМАТОЛОГ БИШКЕК: Запуск системы поиска лучшего стоматолога")
        print("="*60)
        print("📍 Город: Бишкек, Кыргызстан")
        print("🌐 Веб-сервер запускается на: http://127.0.0.1:8000")
        print("💻 Для консольного режима запустите: python main.py --cli")
        print("="*60 + "\n")
        
        # Start browser in background
        threading.Thread(target=open_browser, daemon=True).start()
        
        # Start FastAPI application
        uvicorn.run("app.api:app", host="127.0.0.1", port=8000, log_level="info")

if __name__ == "__main__":
    main()
