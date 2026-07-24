#!/usr/bin/env python3
"""Манифест зависимостей: для собранного файла (плёнка/видео/...) записывает,
из каких исходников он собран (путь + mtime + размер) — чтобы при правках
можно было понять, что устарело, без ручного удаления файлов вручную.

Манифест — файл "<output>.manifest.json" рядом с самим выходным файлом.
Формат простой и общий, годится для любого шага пайплайна: просто передаёшь
output_path и список input-путей, которые в него вошли.
"""

import json
from pathlib import Path

_SUFFIX = ".manifest.json"


def _manifest_path(output_path) -> Path:
    return Path(str(output_path) + _SUFFIX)


def _stat_input(path) -> dict:
    p = Path(path)
    try:
        st = p.stat()
        return {"path": str(p), "mtime": st.st_mtime, "size": st.st_size}
    except OSError:
        return {"path": str(p), "mtime": None, "size": None}


def write_manifest(output_path, input_paths) -> Path:
    manifest_path = _manifest_path(output_path)
    data = {"output": str(output_path), "inputs": [_stat_input(p) for p in input_paths]}
    manifest_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest_path


def is_stale(output_path) -> bool:
    """True, если выходного файла нет, или хоть один исходник из манифеста
    изменился/пропал с момента сборки. Файлы без манифеста (например, из
    старых прогонов до появления этой системы) НЕ считаются устаревшими —
    чтобы не сносить то, что уже есть в проекте."""
    output_path = Path(output_path)
    if not output_path.exists():
        return True
    manifest_path = _manifest_path(output_path)
    if not manifest_path.exists():
        return False
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return True
    for inp in data.get("inputs", []):
        path = inp.get("path")
        try:
            st = Path(path).stat()
        except OSError:
            return True  # исходник исчез
        if st.st_mtime != inp.get("mtime") or st.st_size != inp.get("size"):
            return True
    return False


def find_stale(directory, output_glob="*") -> list:
    """Ищет в directory все файлы с манифестом (output_glob по самому
    output-файлу, не по .manifest.json) и возвращает пути устаревших."""
    directory = Path(directory)
    if not directory.exists():
        return []
    stale = []
    for manifest_path in sorted(directory.glob(f"{output_glob}{_SUFFIX}")):
        output_name = manifest_path.name[: -len(_SUFFIX)]
        output_path = directory / output_name
        if is_stale(output_path):
            stale.append(output_path)
    return stale


def clear_stale(directory, output_glob="*") -> list:
    """Удаляет устаревшие output-файлы и их манифесты (чтобы штатный
    idempotent-скрипт пересобрал их на следующем запуске). Возвращает
    список удалённых output-путей."""
    removed = []
    for output_path in find_stale(directory, output_glob):
        output_path = Path(output_path)
        manifest_path = _manifest_path(output_path)
        output_path.unlink(missing_ok=True)
        manifest_path.unlink(missing_ok=True)
        removed.append(output_path)
    return removed
