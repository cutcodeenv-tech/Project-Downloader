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
        "label": "Модель Whisper для транскрипции озвучки",
        "kind": "choice",
        "choices": [
            ("tiny", "tiny — самая быстрая, менее точная"),
            ("base", "base"),
            ("small", "small"),
            ("medium", "medium"),
            ("large", "large — самая точная, самая медленная"),
        ],
        "default": "base",
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
        if value:
            os.environ.setdefault(field["key"], str(value))


def set_setting(key: str, value: str, current_file: str = __file__) -> None:
    data = load_settings(current_file)
    value = (value or "").strip()
    if value:
        data[key] = value
        os.environ[key] = value
    else:
        data.pop(key, None)
        os.environ.pop(key, None)
    save_settings(data, current_file)
