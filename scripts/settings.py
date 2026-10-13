#!/usr/bin/env python3
"""Персистентные настройки пайплайна — settings.json в корне проекта.

Хранит только то, что пользователь явно поменял через меню «Настройки»;
при старте (apply_settings_to_env) прокидывает сохранённые значения в
os.environ через setdefault — то есть переменная окружения, заданная явно
перед запуском (BASE_DIR=... python3 core/main.py и т.п.), всегда важнее
сохранённой настройки.

Путевые настройки (PROJECTS_ROOT/ASSETS_DIR/ASSETS_MEDIA_DIR) в этом
пайплайне «запекаются» в константы при старте core/main.py — изменение
вступает в силу после перезапуска. Настройки-выборы (VIDEO_QUALITY,
WHISPER_MODEL) читаются на лету через os.getenv() везде, где используются,
и подхватываются сразу, без перезапуска, включая уже запущенными дочерними
скриптами (build_script_env копирует os.environ).
"""

import json
import os
from pathlib import Path

from path_utils import get_base_dir

SETTINGS_FIELDS = [
    {
        "key": "VIDEO_QUALITY",
        "label": "Качество скачивания видео с YouTube",
        "kind": "choice",
        "choices": [
            ("original", "Оригинал (макс. доступное качество)"),
            ("1080", "1080p"),
            ("720", "720p"),
        ],
        "default": "original",
        "restart_required": False,
    },
    {
        "key": "PROJECTS_ROOT",
        "label": "Папка для проектов (по умолчанию <проект программы>/data)",
        "kind": "path",
        "default": None,
        "restart_required": True,
    },
    {
        "key": "ASSETS_DIR",
        "label": "Папка с ассетами: шаблоны, шрифты, текстуры (по умолчанию <проект программы>/assets)",
        "kind": "path",
        "default": None,
        "restart_required": True,
    },
    {
        "key": "ASSETS_MEDIA_DIR",
        "label": "Папка с фоновым видео для анимации плёнки (по умолчанию <проект программы>/assets_media)",
        "kind": "path",
        "default": None,
        "restart_required": True,
    },
    {
        "key": "WHISPER_MODEL",
        "label": "Модель транскрипции озвучки",
        "kind": "choice",
        "choices": [
            ("mlx-community/whisper-large-v3-turbo", "turbo — быстрая и точная (Apple Silicon)"),
            ("mlx-community/whisper-small-mlx", "small — быстрее всех (Apple Silicon)"),
            ("mlx-community/whisper-large-v3-mlx", "large-v3 — точнее, медленнее (Apple Silicon)"),
            ("base", "base — запасной вариант без Apple Silicon"),
            ("large", "large — запасной вариант, самый медленный"),
        ],
        "default": "mlx-community/whisper-large-v3-turbo",
        "restart_required": False,
    },
]

SETTINGS_FIELDS += [
    {
        "key": "VIDEO_SECTION_SECONDS",
        "label": "Ссылка с ?t= — что скачивать",
        "kind": "choice",
        "choices": [
            ("0", "Видео целиком (таймкод только для справки)"),
            ("30", "Фрагмент 30 с от таймкода"),
            ("60", "Фрагмент 60 с от таймкода"),
            ("120", "Фрагмент 2 мин от таймкода"),
        ],
        "default": "0",
        "restart_required": False,
    },
    {
        "key": "BACKGROUND_VIDEO",
        "label": "YouTube-видео качать в фоне, параллельно остальным шагам",
        "kind": "choice",
        "choices": [("on", "Да"), ("off", "Нет, по очереди")],
        "default": "on",
        "restart_required": False,
    },
    {
        "key": "NOTIFY",
        "label": "Уведомлять об окончании прогона (macOS / Telegram)",
        "kind": "choice",
        "choices": [("on", "Да"), ("off", "Нет")],
        "default": "on",
        "restart_required": False,
    },
    {
        "key": "TELEGRAM_BOT_TOKEN",
        "label": "Telegram: токен бота для уведомлений",
        "kind": "secret",
        "default": None,
        "restart_required": False,
    },
    {
        "key": "TELEGRAM_CHAT_ID",
        "label": "Telegram: chat id для уведомлений",
        "kind": "text",
        "default": None,
        "restart_required": False,
    },
]

SETTINGS_FIELD_MAP = {field["key"]: field for field in SETTINGS_FIELDS}


def get_settings_path(current_file: str = __file__) -> Path:
    return get_base_dir(current_file) / "settings.json"


def load_settings(current_file: str = __file__) -> dict:
    path = get_settings_path(current_file)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_settings(data: dict, current_file: str = __file__) -> None:
    path = get_settings_path(current_file)
    clean = {k: v for k, v in data.items() if v}
    path.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")


def apply_settings_to_env(current_file: str = __file__) -> None:
    data = load_settings(current_file)
    for field in SETTINGS_FIELDS:
        value = data.get(field["key"])
        if field.get("kind") == "path":
            value = clean_path_value(str(value or ""))
        if value:
            os.environ.setdefault(field["key"], str(value))


def clean_path_value(value: str) -> str:
    """Снимает кавычки, которые появляются при перетаскивании папки в терминал."""
    value = (value or "").strip()
    while len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        value = value[1:-1].strip()
    return value


def set_setting(key: str, value: str, current_file: str = __file__) -> None:
    data = load_settings(current_file)
    value = clean_path_value(value)
    if value:
        data[key] = value
        os.environ[key] = value
    else:
        data.pop(key, None)
        os.environ.pop(key, None)
    save_settings(data, current_file)


SCAN_FOLDERS_KEY = "PROJECT_SCAN_FOLDERS"


def load_scan_folders(current_file: str = __file__) -> list:
    """Папки, в которых искать проекты помимо стандартного корня.

    Намеренно не в SETTINGS_FIELDS: это список, а apply_settings_to_env
    умеет прокидывать в окружение только строки.
    """
    folders = load_settings(current_file).get(SCAN_FOLDERS_KEY)
    if not isinstance(folders, list):
        return []
    return [str(item) for item in folders if str(item).strip()]


def save_scan_folders(folders: list, current_file: str = __file__) -> None:
    data = load_settings(current_file)
    cleaned = []
    for item in folders:
        item = str(item).strip()
        if item and item not in cleaned:
            cleaned.append(item)
    if cleaned:
        data[SCAN_FOLDERS_KEY] = cleaned
    else:
        data.pop(SCAN_FOLDERS_KEY, None)
    save_settings(data, current_file)


def add_scan_folder(folder, current_file: str = __file__) -> list:
    folder = str(Path(folder).expanduser().resolve())
    folders = load_scan_folders(current_file)
    if folder not in folders:
        folders.append(folder)
        save_scan_folders(folders, current_file)
    return folders


def remove_scan_folder(folder, current_file: str = __file__) -> list:
    folder = str(Path(folder).expanduser().resolve())
    folders = [item for item in load_scan_folders(current_file) if item != folder]
    save_scan_folders(folders, current_file)
    return folders
