#!/usr/bin/env python3
"""Лог ошибок скачивания, разложенный по стадиям пайплайна:

    data/<проект>/errors/stage_<N>/<step_id>.csv

По одному файлу на шаг — сразу видно, на какой стадии и что именно не
скачалось. Колонки: display_name (предполагаемое имя файла), url, reason,
logged_at.
"""

import csv
import os
from datetime import datetime
from pathlib import Path

from path_utils import get_data_dir

_DATA_DIR = get_data_dir(__file__)


def project_dir(project_name: str) -> Path:
    return _DATA_DIR / project_name


def stage_errors_dir(project_name: str, stage_number=None) -> Path:
    stage_number = stage_number or os.getenv("STAGE_NUMBER") or "unknown"
    d = project_dir(project_name) / "errors" / f"stage_{stage_number}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def log_download_error(project_name: str, step_id: str, display_name: str, url: str,
                        reason: str = "", stage_number=None) -> Path:
    """Добавляет строку в errors/stage_<N>/<step_id>.csv (создаёт файл при
    первой записи). Возвращает путь к файлу."""
    path = stage_errors_dir(project_name, stage_number) / f"{step_id}.csv"
    file_exists = path.exists()
    with open(path, "a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["display_name", "url", "reason", "logged_at"])
        writer.writerow([display_name, url, reason, datetime.now().isoformat(timespec="seconds")])
    return path


def iter_stage_error_files(project_name: str):
    """Обходит все errors/stage_*/*.csv проекта: (stage_number, step_id, path)."""
    errors_root = project_dir(project_name) / "errors"
    if not errors_root.exists():
        return
    for stage_dir in sorted(errors_root.glob("stage_*")):
        stage_number = stage_dir.name.replace("stage_", "", 1)
        for csv_path in sorted(stage_dir.glob("*.csv")):
            yield stage_number, csv_path.stem, csv_path


def load_errors(project_name: str) -> list[dict]:
    """Плоский список всех ошибок проекта — {stage, step_id, display_name,
    url, reason, logged_at}. Дедуплицирует по (step_id, display_name): если
    пайплайн перезапускался несколько раз, оставляет только самую свежую
    запись по logged_at, а не все накопившиеся."""
    latest: dict[tuple[str, str], dict] = {}
    for stage_number, step_id, csv_path in iter_stage_error_files(project_name):
        try:
            with open(csv_path, "r", encoding="utf-8", newline="") as f:
                for row in csv.DictReader(f):
                    display_name = (row.get("display_name") or "").strip()
                    if not display_name:
                        continue
                    key = (step_id, display_name)
                    entry = {
                        "stage": stage_number,
                        "step_id": step_id,
                        "display_name": display_name,
                        "url": (row.get("url") or "").strip(),
                        "reason": (row.get("reason") or "").strip(),
                        "logged_at": (row.get("logged_at") or "").strip(),
                    }
                    prev = latest.get(key)
                    if prev is None or entry["logged_at"] >= prev["logged_at"]:
                        latest[key] = entry
        except (OSError, csv.Error):
            continue
    return sorted(latest.values(), key=lambda e: (e["stage"], e["step_id"], e["display_name"]))


def remove_error(project_name: str, stage_number, step_id: str, display_name: str) -> bool:
    """Убирает строку(и) с этим display_name из errors/stage_<N>/<step_id>.csv
    (успешный повтор или явное «пропустить»). Возвращает True, если что-то
    удалено."""
    path = project_dir(project_name) / "errors" / f"stage_{stage_number}" / f"{step_id}.csv"
    if not path.exists():
        return False
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
    except (OSError, csv.Error):
        return False

    kept = [r for r in rows if (r.get("display_name") or "").strip() != display_name]
    if len(kept) == len(rows):
        return False

    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["display_name", "url", "reason", "logged_at"])
        for r in kept:
            writer.writerow([r.get("display_name", ""), r.get("url", ""), r.get("reason", ""), r.get("logged_at", "")])
    return True
