#!/usr/bin/env python3
"""
Автоматически обновляет cookies.txt для YouTube из локального браузера.
Работает на macOS и Windows через browser_cookie3.
"""

import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Iterable

from path_utils import get_base_dir

TARGET_DOMAINS = (
    "youtube.com",
    ".youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "accounts.google.com",
    ".google.com",
    "google.com",
)


def ensure_browser_cookie3():
    try:
        import browser_cookie3  # type: ignore
        return browser_cookie3
    except ImportError:
        print("browser_cookie3 не найден. Устанавливаю...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "browser-cookie3"])
            import browser_cookie3  # type: ignore
            return browser_cookie3
        except Exception as exc:
            print(f"⚠️  Не удалось установить browser_cookie3: {exc}")
            return None


def get_browser_priority() -> list[str]:
    env_browser = (os.getenv("COOKIE_BROWSER") or "").strip()
    if env_browser:
        return [item.strip() for item in env_browser.split(",") if item.strip()]

    system = platform.system()
    if system == "Darwin":
        return ["safari", "chrome", "brave", "chromium", "edge", "firefox", "opera", "vivaldi"]
    if system == "Windows":
        return ["edge", "chrome", "brave", "chromium", "firefox", "opera", "vivaldi"]
    return ["chrome", "chromium", "firefox", "edge", "brave", "opera", "vivaldi"]


def iter_relevant_cookies(cookie_jar: Iterable) -> list:
    relevant = []
    for cookie in cookie_jar:
        domain = (getattr(cookie, "domain", "") or "").lower()
        if any(target in domain for target in TARGET_DOMAINS):
            relevant.append(cookie)
    return relevant


def export_cookies_netscape(cookies: list, output_path: Path) -> None:
    lines = [
        "# Netscape HTTP Cookie File",
        "# This file is generated automatically. Do not edit.",
        "",
    ]

    for cookie in cookies:
        domain = cookie.domain or ""
        include_subdomains = "TRUE" if domain.startswith(".") else "FALSE"
        path = cookie.path or "/"
        secure = "TRUE" if cookie.secure else "FALSE"
        expires = str(int(cookie.expires or 0))
        name = cookie.name
        value = cookie.value

        if "HttpOnly" in getattr(cookie, "_rest", {}):
            domain = f"#HttpOnly_{domain}"

        lines.append("\t".join([domain, include_subdomains, path, secure, expires, name, value]))

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_browser_cookies(browser_cookie3, browser_name: str):
    loader = getattr(browser_cookie3, browser_name, None)
    if loader is None:
        raise RuntimeError(f"Браузер {browser_name} не поддерживается browser_cookie3")
    return loader()


def print_cookie_access_hint(browser_name: str, exc: Exception) -> None:
    if browser_name != "safari" or not isinstance(exc, PermissionError):
        return

    print("   Safari cookies защищены macOS. Дайте Full Disk Access приложению, из которого запущен скрипт:")
    print("   System Settings → Privacy & Security → Full Disk Access")
    print("   Добавьте Terminal/iTerm/VS Code/Cursor, затем полностью перезапустите это приложение.")
    print("   После этого проверьте Safari отдельно:")
    print("   COOKIE_BROWSER=safari python scripts/refresh_youtube_cookies.py")


def main() -> int:
    print("=== Обновление YouTube cookies ===")

    browser_cookie3 = ensure_browser_cookie3()
    if browser_cookie3 is None:
        print("⚠️  Пропускаю обновление cookies.")
        return 0

    output_path = get_base_dir(__file__) / "cookies.txt"

    last_error = None
    for browser_name in get_browser_priority():
        try:
            cookie_jar = load_browser_cookies(browser_cookie3, browser_name)
            cookies = iter_relevant_cookies(cookie_jar)
            if not cookies:
                print(f"⚠️  В браузере {browser_name} cookies для YouTube не найдены")
                continue

            export_cookies_netscape(cookies, output_path)
            print(f"✓ cookies.txt обновлен из браузера {browser_name}: {output_path}")
            return 0
        except Exception as exc:
            last_error = exc
            print(f"⚠️  Не удалось получить cookies из {browser_name}: {exc}")
            print_cookie_access_hint(browser_name, exc)

    if output_path.exists():
        print(f"⚠️  Использую существующий cookies.txt: {output_path}")
    else:
        print("⚠️  Не удалось автоматически обновить cookies.txt")
        if last_error is not None:
            print(f"   Последняя ошибка: {last_error}")
        print("   Проверьте, что вы залогинены в YouTube хотя бы в одном браузере.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
