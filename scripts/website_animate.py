#!/usr/bin/env python3
"""
Статьи для пайплайна: извлечение текста статьи (paper_pipeline/shot.mjs —
puppeteer-core + реальный Chrome, DOM-эвристики og:title/og:description/<p>)
и рендер на рваной бумаге с подсветкой заголовка (paper_pipeline/compose.mjs
— Lottie-шаблон рваной бумаги + hyperframes render). Полностью
детерминированно — никакого ИИ на рантайме.

Тот же интерфейс, что был у прежнего скрипта скриншотов: читает
database/os_doc_{project}_other_links.csv (source_address, url), кладёт
результат в articles/<волна>/{source_address}.mov (QuickTime Animation,
альфа-канал — фон вне рваной бумаги прозрачный, для композитинга поверх
любого фона в монтаже).
"""

import csv
import os
import subprocess
from pathlib import Path

from path_utils import get_data_dir, get_base_dir, project_subdir
from progress_ui import render_bar, StatusBoard
from error_log import log_download_error

_DATA_DIR = get_data_dir(__file__)
_BASE_DIR = get_base_dir(__file__)
_PAPER_DIR = _BASE_DIR / "paper_pipeline"

STEP_ID = "screenshots"
EXTRACT_TIMEOUT_S = 90
COMPOSE_TIMEOUT_S = 60
RENDER_TIMEOUT_S = 240


def get_project_database_dir(project_name: str) -> Path:
    return project_subdir(_DATA_DIR / project_name, "database")


def get_project_articles_dir(project_name: str) -> Path:
    return project_subdir(_DATA_DIR / project_name, "articles")


def get_other_links_csv_path(project_name: str) -> Path:
    return get_project_database_dir(project_name) / f"os_doc_{project_name}_other_links.csv"


def read_links_from_csv(file_path: Path) -> list:
    if not file_path.exists():
        raise FileNotFoundError(f"CSV файл со ссылками не найден: {file_path}")
    pairs = []
    with file_path.open("r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            source_address = (row.get("source_address") or "").strip()
            url = (row.get("url") or "").strip()
            if source_address and url and not source_address.startswith("upd_"):
                pairs.append((source_address, url))
    return pairs


def _run(cmd: list, timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(_PAPER_DIR), capture_output=True, text=True, timeout=timeout)


def extract_article(url: str, slug: str) -> tuple[bool, str]:
    proc = _run(["node", str(_PAPER_DIR / "shot.mjs"), "--url", url, "--slug", slug], EXTRACT_TIMEOUT_S)
    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout or "shot.mjs: неизвестная ошибка").strip().splitlines()[-1][:200]
    return True, ""


def compose_article(slug: str) -> tuple[bool, str]:
    proc = _run(["node", str(_PAPER_DIR / "compose.mjs"), "--slug", slug], COMPOSE_TIMEOUT_S)
    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout or "compose.mjs: неизвестная ошибка").strip().splitlines()[-1][:200]
    return True, ""


def render_article(slug: str, output_path: Path) -> tuple[bool, str]:
    render_dir = _PAPER_DIR / "renders" / slug
    prores_path = render_dir / f"_render-{slug}.mov"
    proc = _run(
        ["npx", "--yes", "hyperframes", "render", str(render_dir), "--format", "mov", "--fps", "25", "-o", str(prores_path)],
        RENDER_TIMEOUT_S,
    )
    if proc.returncode != 0 or not prores_path.exists():
        return False, (proc.stderr or proc.stdout or "hyperframes render: неизвестная ошибка").strip().splitlines()[-1][:200]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    proc2 = subprocess.run(
        ["ffmpeg", "-y", "-i", str(prores_path), "-c:v", "qtrle", "-pix_fmt", "argb", str(output_path)],
        capture_output=True, text=True, timeout=RENDER_TIMEOUT_S,
    )
    prores_path.unlink(missing_ok=True)
    if proc2.returncode != 0 or not output_path.exists():
        return False, "ffmpeg: не удалось перекодировать в qtrle/argb"
    return True, ""


def process(project_name: str) -> None:
    print("\n=== СТАТЬИ: рваная бумага + подсветка заголовка ===")
    print(f"Проект: {project_name}")

    csv_file = get_other_links_csv_path(project_name)
    upd_subdir = os.getenv("UPD_SUBDIR", "").strip()
    base_articles_dir = get_project_articles_dir(project_name)
    articles_dir = base_articles_dir / upd_subdir if upd_subdir else base_articles_dir

    if not csv_file.exists():
        print(f"❌ CSV файл не найден: {csv_file}")
        return

    pairs = read_links_from_csv(csv_file)
    if not pairs:
        print("❌ Нет ссылок для обработки")
        return

    articles_dir.mkdir(parents=True, exist_ok=True)

    todo = []
    for source_address, url in pairs:
        filename = f"{source_address}.mov"
        already = (articles_dir / filename).exists() or (
            upd_subdir and (base_articles_dir / filename).exists()
        )
        if not already and upd_subdir:
            for item in base_articles_dir.iterdir():
                if item.is_dir() and (item / filename).exists():
                    already = True
                    break
        if not already:
            todo.append((source_address, url))

    skipped = len(pairs) - len(todo)
    if skipped:
        print(f"⏭️  Уже готовы (пропускаем): {skipped}")
    if not todo:
        print("✅ Все статьи уже обработаны")
        return

    print(f"📥 К обработке: {len(todo)}")

    total = len(todo)
    board = StatusBoard(2)
    ok = fail = 0

    for idx, (source_address, url) in enumerate(todo, 1):
        overall = (idx - 1) / total
        board.render([
            f"[{idx}/{total}] {source_address}: {url[:60]}",
            f"Всего:  [{render_bar(overall)}] {overall * 100:5.1f}%  (готово: {ok}, ошибок: {fail})",
        ])

        try:
            success, reason = extract_article(url, source_address)
            if not success:
                raise RuntimeError(f"извлечение текста: {reason}")

            success, reason = compose_article(source_address)
            if not success:
                raise RuntimeError(f"компоновка: {reason}")

            output_path = articles_dir / f"{source_address}.mov"
            success, reason = render_article(source_address, output_path)
            if not success:
                raise RuntimeError(f"рендер: {reason}")

            ok += 1
        except subprocess.TimeoutExpired:
            fail += 1
            board.log(f"  ❌ {source_address}: таймаут")
            log_download_error(project_name, STEP_ID, source_address, url, reason="timeout")
        except Exception as exc:
            fail += 1
            board.log(f"  ❌ {source_address}: {exc}")
            log_download_error(project_name, STEP_ID, source_address, url, reason=str(exc))

    overall = 1.0
    board.render([
        f"[{total}/{total}] готово",
        f"Всего:  [{render_bar(overall)}] {overall * 100:5.1f}%  (готово: {ok}, ошибок: {fail})",
    ])
    board.close()

    print(f"\nГотово: {ok}, ошибок: {fail}, пропущено (уже есть): {skipped}")
    if fail:
        print(f"Ошибки: 00_Admin/errors/stage_*/{STEP_ID}.csv")
    print(f"📁 {articles_dir}")


def main() -> int:
    project_name = os.getenv("PROJECT_NAME", "").strip()
    if not project_name:
        project_name = input("Введите название проекта: ").strip()
    if not project_name:
        print("❌ Название проекта не указано")
        return 1
    process(project_name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
