#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import asyncio
import re
from pathlib import Path
from typing import List, Tuple, Optional

from playwright.async_api import async_playwright

LINE_RE = re.compile(
    r"^\s*([A-Za-zА-Яа-я]+?\d+)\s+(\d+)\s*:\s*(\S+)\s*$"
)
# Примеры матчей:
# "B10 3 : https://site" -> cell="B10", idx="3", url="https://site"


def default_outdir() -> Path:
    # По умолчанию — ~/Downloads/download_all/os_ya/5_stiils_links
    return Path.home() / "Downloads" / "download_all" / "os_ya" / "5_stiils_links"


def normalize_url(u: str) -> Optional[str]:
    u = (u or "").strip()
    if not u:
        return None
    if not re.match(r"^https?://", u, flags=re.I):
        u = "https://" + u
    return u


async def auto_scroll(page, step: int = 800, delay_ms: int = 120, max_steps: int = 25):
    # Лёгкий прогон вниз для Lazy-контента
    for _ in range(max_steps):
        prev = await page.evaluate("() => document.scrollingElement.scrollTop")
        await page.mouse.wheel(0, step)
        await page.wait_for_timeout(delay_ms)
        curr = await page.evaluate("() => document.scrollingElement.scrollTop")
        if curr == prev:
            break


async def shot_one(browser, url: str, out_path: Path, width: int, height: int, wait_until: str, delay_ms: int, timeout_ms: int):
    context = await browser.new_context(viewport={"width": width, "height": height})
    page = await context.new_page()
    try:
        resp = await page.goto(url, wait_until=wait_until, timeout=timeout_ms)
        if delay_ms:
            await page.wait_for_timeout(delay_ms)
        await auto_scroll(page)
        await page.screenshot(path=str(out_path), full_page=True)  # всегда full_page
        status = resp.status if resp else None
        print(f"[OK] {url} → {out_path.name} (status: {status})")
        return True
    except Exception as e:
        print(f"[ERR] {url}: {e}")
        return False
    finally:
        await context.close()


async def run(items: List[Tuple[str, str, str, str]], outdir: Path, width: int, height: int, wait_until: str, delay_ms: int, concurrency: int, timeout_ms: int, error_log_path: Path):
    outdir.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(concurrency)
    errors = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        async def worker(cell: str, idx: str, url: str, raw_line: str):
            name = f"{cell}_{idx}.png"
            target = outdir / name
            async with sem:
                ok = await shot_one(browser, url, target, width, height, wait_until, delay_ms, timeout_ms)
                if not ok:
                    errors.append(raw_line)

        tasks = [worker(cell, idx, url, raw_line) for (cell, idx, url, raw_line) in items]
        await asyncio.gather(*tasks)
        await browser.close()

    # Записываем ошибки
    if errors:
        with open(error_log_path, "a", encoding="utf-8") as f:
            for line in errors:
                f.write(line + "\n")
        print(f"[INFO] Ошибки записаны в {error_log_path}")


def parse_input(path: Path) -> List[Tuple[str, str, str, str]]:
    """
    Возвращает список кортежей (cell, idx, url, raw_line).
    Пропускает пустые/некорректные строки.
    """
    rows: List[Tuple[str, str, str, str]] = []
    for i, raw in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), start=1):
        raw_strip = raw.strip()
        if not raw_strip:
            continue
        m = LINE_RE.match(raw_strip)
        if not m:
            print(f"[WARN] Строка {i} не распознана и будет пропущена: {raw_strip}")
            continue
        cell, idx, url = m.group(1), m.group(2), m.group(3)
        url = normalize_url(url)
        if not url:
            print(f"[WARN] Строка {i}: невалидная ссылка '{m.group(3)}' — пропуск.")
            continue
        rows.append((cell, idx, url, raw_strip))
    return rows


def main():
    ap = argparse.ArgumentParser(description="Скриншоты сайтов с именованием по ячейкам (B10_3, B10_4, ...)")
    ap.add_argument("--input", help="Путь к текстовому файлу со строками вида 'B10 3 : https://...'.")
    ap.add_argument("--outdir", default=str(default_outdir()), help="Папка для сохранения скринов (по умолчанию ~/Downloads/download_all/os_ya/5_stiils_links).")
    ap.add_argument("--width", type=int, default=1600, help="Ширина вьюпорта, по умолчанию 1600.")
    ap.add_argument("--height", type=int, default=1000, help="Высота вьюпорта, по умолчанию 1000.")
    ap.add_argument("--wait-until", choices=["load", "domcontentloaded", "networkidle", "commit"], default="networkidle", help="Стадия ожидания загрузки (по умолчанию networkidle).")
    ap.add_argument("--delay", type=int, default=250, help="Задержка перед скрином в мс (по умолчанию 250).")
    ap.add_argument("--concurrency", type=int, default=4, help="Параллельных вкладок (по умолчанию 4).")
    ap.add_argument("--timeout", type=int, default=45000, help="Таймаут загрузки страницы, мс (по умолчанию 45000).")
    args = ap.parse_args()

    # Если не передан --input, спросить путь у пользователя
    input_path = args.input
    while not input_path:
        input_path = input("Введите путь к текстовому файлу со ссылками: ").strip()
    input_path = Path(input_path)
    if not input_path.exists():
        raise SystemExit(f"Не найден файл: {input_path}")

    items = parse_input(input_path)
    if not items:
        raise SystemExit("Не найдено ни одной корректной строки с ссылкой.")

    outdir = Path(args.outdir)
    error_log_path = outdir / "Still_links_errors.txt"

    asyncio.run(
        run(
            items=items,
            outdir=outdir,
            width=args.width,
            height=args.height,
            wait_until=args.wait_until,
            delay_ms=args.delay,
            concurrency=args.concurrency,
            timeout_ms=args.timeout,
            error_log_path=error_log_path,
        )
    )


if __name__ == "__main__":
    main()
