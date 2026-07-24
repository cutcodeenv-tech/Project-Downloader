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
