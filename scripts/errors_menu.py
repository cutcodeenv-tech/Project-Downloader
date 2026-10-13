#!/usr/bin/env python3
"""Меню «Ошибки проекта»: собирает все ошибки скачивания/обработки по
проекту (00_Admin/errors/stage_<N>/<step_id>.csv, см. error_log.py) в один дашборд
по стадиям + плоский навигируемый список, и даёт исправить каждую ошибку
на месте — повторной попыткой, открытием ссылки/папки или удалением из
списка. Повтор всегда одно осознанное нажатие — никакого автоматического
зацикливания на «плохих» ссылках.

UI-примитивы (select_option/ask_confirm) и ретраи, чья логика живёт в
core/main.py (stage_images, direct_video, stage_author), передаются сюда
извне — этот модуль не импортирует core.main (обратная зависимость), по
той же схеме, что и остальные модули в scripts/.
"""

import csv
import hashlib
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from path_utils import get_data_dir, project_subdir
import error_log
from progress_ui import console

STAGE_TITLES = {
    "1": "Структура и метаданные проекта",
    "2": "Скачивание и подготовка материала",
    "3": "Упаковка",
    "unknown": "Без стадии",
}

STEP_TITLES = {
    "stage_images": "Скачать изображения",
    "pullvids_download": "Скачать YouTube видео (yt-dlp)",
    "direct_video": "Скачать видео по ссылкам",
    "gazety_direct": "Сгенерировать газеты по ссылкам",
    "screenshots": "Статьи на рваной бумаге",
    "smart_cropping": "Кроп 16:9",
    "stage_author": "Создать PNG-плашки источников",
}

STEP_OUTPUT_FOLDER = {
    "stage_images": "images",
    "pullvids_download": "video",
    "direct_video": "video_direct",
    "gazety_direct": "gazety_direct",
    "screenshots": "articles",
    "smart_cropping": "images_cropped",
    "stage_author": "author",
}

MOTIONARRAY_STEP_ID = "motionarray"
STEP_TITLES[MOTIONARRAY_STEP_ID] = "MotionArray (переименование)"


def _project_dir(project_name: str) -> Path:
    return get_data_dir(__file__) / project_name


def _load_module(filename: str, modname: str):
    """Грузит скрипт с именем, недопустимым для обычного import (начинается
    с цифры/содержит точку — '3.4_pullvids_download.py' и т.п.)."""
    path = SCRIPT_DIR / filename
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _slug_for_url(url: str) -> str:
    return "gazeta-" + hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]


def _retry_article(url: str, output_path: Path):
    import website_animate
    slug = _slug_for_url(url)
    ok, reason = website_animate.extract_article(url, slug)
    if not ok:
        return False, f"извлечение текста: {reason}"
    ok, reason = website_animate.compose_article(slug)
    if not ok:
        return False, f"компоновка: {reason}"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ok, reason = website_animate.render_article(slug, output_path)
    if not ok:
        return False, f"рендер: {reason}"
    return True, ""


def _retry_pullvids_download(project_name: str, row: dict):
    mod = _load_module("3.4_pullvids_download.py", "_errors_menu_pullvids")
    project_dir = _project_dir(project_name)
    video_dir = str(project_subdir(project_dir, "video"))
    cookies_file = None
    default_cookies = Path(SCRIPT_DIR).parent / "cookies.txt"
    if default_cookies.exists():
        cookies_file = str(default_cookies)
    ok = mod.download_video(row["url"], video_dir, cookies_file)
    return (True, "") if ok else (False, "повтор не удался")


def _retry_smart_cropping(project_name: str, row: dict):
    mod = _load_module("2.1_smart_cropping.py", "_errors_menu_smart_cropping")
    project_dir = _project_dir(project_name)
    cropped_dir = project_subdir(project_dir, "images_cropped")
    cropped_dir.mkdir(parents=True, exist_ok=True)
    input_path = row["url"]  # для smart_cropping в этой колонке лежит локальный путь, не URL
    output_path = cropped_dir / f"{row['display_name']}.jpg"
    ok = mod.smart_crop_image(input_path, str(output_path))
    return (True, "") if ok else (False, "повтор кропа не удался")


def _retry_gazety_direct(project_name: str, row: dict):
    project_dir = _project_dir(project_name)
    gazety_root = project_subdir(project_dir, "gazety_direct")
    slug = _slug_for_url(row["url"])
    output_path = gazety_root / slug / f"{slug}.mov"
    return _retry_article(row["url"], output_path)


def _retry_screenshots(project_name: str, row: dict):
    project_dir = _project_dir(project_name)
    articles_dir = project_subdir(project_dir, "articles")
    output_path = articles_dir / f"{row['display_name']}.mov"
    return _retry_article(row["url"], output_path)


SCRIPT_RETRY_HANDLERS = {
    "pullvids_download": _retry_pullvids_download,
    "smart_cropping": _retry_smart_cropping,
    "gazety_direct": _retry_gazety_direct,
    "screenshots": _retry_screenshots,
}


def _reveal_folder(path: Path) -> bool:
    if sys.platform != "darwin" or not shutil.which("open"):
        console.print("[warn]Открытие Finder поддерживается только на macOS.[/]")
        return False
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["open", str(path)])
    return True


def _open_url(url: str) -> bool:
    if sys.platform != "darwin" or not shutil.which("open"):
        console.print("[warn]Открытие ссылок поддерживается только на macOS.[/]")
        return False
    subprocess.run(["open", url])
    return True


def _load_motionarray_errors(project_name: str) -> list:
    project_dir = _project_dir(project_name)
    log_path = project_subdir(project_dir, "database") / f"osnovateli_doc_{project_name}_motionarray_rename_log.csv"
    if not log_path.exists():
        return []
    latest: dict[str, dict] = {}
    try:
        with open(log_path, "r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                status = (row.get("status") or "").strip()
                if "FAILED" not in status.upper():
                    continue
                display_name = (row.get("source_address") or "").strip()
                if not display_name:
                    continue
                entry = {
                    "stage": "2",
                    "step_id": MOTIONARRAY_STEP_ID,
                    "display_name": display_name,
                    "url": (row.get("motionarray_url") or "").strip(),
                    "reason": status,
                    "logged_at": (row.get("timestamp") or "").strip(),
                }
                prev = latest.get(display_name)
                if prev is None or entry["logged_at"] >= prev["logged_at"]:
                    latest[display_name] = entry
    except (OSError, csv.Error):
        return []
    return sorted(latest.values(), key=lambda e: e["display_name"])


def _print_dashboard(errors: list) -> None:
    from rich.panel import Panel
    from rich.table import Table
    from rich import box

    by_stage: dict[str, dict[str, int]] = {}
    for e in errors:
        by_stage.setdefault(e["stage"], {}).setdefault(e["step_id"], 0)
        by_stage[e["stage"]][e["step_id"]] += 1

    for stage_number in sorted(by_stage, key=lambda s: (s == "unknown", s)):
        title = STAGE_TITLES.get(stage_number, f"Стадия {stage_number}")
        table = Table(box=box.SIMPLE, show_header=False, pad_edge=False)
        table.add_column("step")
        table.add_column("count", justify="right")
        for step_id, count in sorted(by_stage[stage_number].items()):
            step_title = STEP_TITLES.get(step_id, step_id)
            table.add_row(step_title, f"[err]{count}[/]")
        console.print(Panel(table, title=f"Стадия {stage_number} — {title}", title_align="left",
                             border_style="accent", box=box.ROUNDED))


def _load_image_links(project_name: str) -> dict:
    """source_address -> url, из database/os_doc_<project>_image_links.csv —
    у ошибок кропа в колонке url лежит локальный путь (кроп работает с уже
    скачанным файлом, без сети), но у файла всё равно есть URL, с которого
    его когда-то скачали — подтягиваем его отсюда, чтобы «открыть в
    браузере» была всегда, а не только у сетевых ошибок."""
    project_dir = _project_dir(project_name)
    csv_path = project_subdir(project_dir, "database") / f"os_doc_{project_name}_image_links.csv"
    if not csv_path.exists():
        return {}
    mapping = {}
    try:
        with open(csv_path, "r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                src = (row.get("source_address") or "").strip()
                url = (row.get("url") or "").strip()
                if src and url:
                    mapping[src] = url
    except (OSError, csv.Error):
        pass
    return mapping


def _resolve_link_url(e: dict, image_links: dict) -> str:
    """Ссылка, которую можно открыть в браузере, для любого типа ошибки —
    если в колонке url уже настоящая ссылка, используем её как есть; для
    кропа (там локальный путь) ищем оригинал по display_name."""
    url = e["url"]
    if url.startswith("http://") or url.startswith("https://"):
        return url
    if e["step_id"] == "smart_cropping":
        return image_links.get(e["display_name"], "")
    return ""


def _error_label(e: dict) -> str:
    step_title = STEP_TITLES.get(e["step_id"], e["step_id"])
    reason = e["reason"] or "без причины"
    return f"[Стадия {e['stage']} · {step_title}] {e['display_name']} — {reason}"


def _handle_error_item(project_name, e, select_option, ask_confirm, core_retry_handlers):
    retryable = e["step_id"] in SCRIPT_RETRY_HANDLERS or e["step_id"] in core_retry_handlers
    link_url = e.get("link_url", "")

    while True:
        options = []
        if retryable:
            options.append(("Повторить попытку", "retry"))
        if link_url:
            options.append(("Открыть ссылку в браузере", "open_url"))
        folder_name = STEP_OUTPUT_FOLDER.get(e["step_id"])
        if folder_name:
            options.append(("Показать папку в Finder", "reveal"))
        if e["step_id"] != MOTIONARRAY_STEP_ID:
            options.append(("Пропустить (убрать из списка)", "skip"))
        options.append(("Назад", "back"))

        choice = select_option(_error_label(e), options)
        if choice == "back":
            return

        if choice == "retry":
            handler = SCRIPT_RETRY_HANDLERS.get(e["step_id"]) or core_retry_handlers.get(e["step_id"])
            console.print(f"[accent]→[/] Повторяю: {e['display_name']}…")
            try:
                ok, reason = handler(project_name, e)
            except Exception as exc:
                ok, reason = False, str(exc)
            if ok:
                error_log.remove_error(project_name, e["stage"], e["step_id"], e["display_name"])
                console.print(f"[ok]✓[/] Готово: {e['display_name']}")
                return
            error_log.remove_error(project_name, e["stage"], e["step_id"], e["display_name"])
            error_log.log_download_error(project_name, e["step_id"], e["display_name"], e["url"],
                                          reason=reason, stage_number=e["stage"])
            e["reason"] = reason
            console.print(f"[err]✗[/] Не получилось: {reason}")
            continue

        if choice == "open_url":
            _open_url(link_url)
            continue

        if choice == "reveal":
            project_dir = _project_dir(project_name)
            folder = project_subdir(project_dir, folder_name)
            _reveal_folder(folder)
            continue

        if choice == "skip":
            if not ask_confirm(f"Убрать «{e['display_name']}» из списка ошибок без повтора?", default=False):
                continue
            error_log.remove_error(project_name, e["stage"], e["step_id"], e["display_name"])
            console.print(f"[muted]Пропущено: {e['display_name']}[/]")
            return


def run_errors_menu(select_project_name, select_option, ask_confirm, core_retry_handlers=None):
    core_retry_handlers = core_retry_handlers or {}
    project_name = select_project_name()

    while True:
        errors = error_log.load_errors(project_name) + _load_motionarray_errors(project_name)
        if not errors:
            console.print("[ok]Ошибок не найдено — всё чисто.[/]")
            return

        image_links = _load_image_links(project_name)
        for e in errors:
            e["link_url"] = _resolve_link_url(e, image_links)

        _print_dashboard(errors)

        options = [(_error_label(e), i) for i, e in enumerate(errors)]
        options.append(("Назад", "back"))
        choice = select_option(f"Ошибки проекта «{project_name}»", options)
        if choice == "back":
            return

        _handle_error_item(project_name, errors[choice], select_option, ask_confirm, core_retry_handlers)
