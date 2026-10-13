#!/usr/bin/env python3
"""Загрузка исходной таблицы проекта: локальный файл или Google-таблица."""
import csv
import re
from pathlib import Path

SUPPORTED_SUFFIXES = (".csv", ".xlsx", ".xlsm")
LETTER_RE = re.compile(r"^[A-Za-z]{1,2}$")


def column_letter(index: int) -> str:
    letter = ""
    index += 1
    while index > 0:
        index, rem = divmod(index - 1, 26)
        letter = chr(ord("A") + rem) + letter
    return letter


def letter_to_index(letter: str) -> int:
    index = 0
    for char in letter.upper():
        index = index * 26 + (ord(char) - ord("A") + 1)
    return index - 1


def find_local_source(project_dir) -> Path:
    project_dir = Path(project_dir)
    if not project_dir.is_dir():
        return None
    candidates = [
        path for path in project_dir.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES and not path.name.startswith((".", "~$"))
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def read_table(path) -> list:
    path = Path(path)
    suffix = path.suffix.lower()

    if suffix == ".xls":
        raise ValueError(f"Формат .xls не поддерживается: {path.name}. Сохраните файл как .xlsx.")

    if suffix == ".csv":
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            return [list(row) for row in csv.reader(f)]

    if suffix in (".xlsx", ".xlsm"):
        try:
            import openpyxl
        except ImportError:
            raise ImportError("Для чтения Excel нужен openpyxl: pip install openpyxl")
        workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
        try:
            sheet = workbook.active
            return [
                ["" if cell is None else str(cell) for cell in row]
                for row in sheet.iter_rows(values_only=True)
            ]
        finally:
            workbook.close()

    raise ValueError(f"Неподдерживаемый формат таблицы: {path.name}")


def build_header_index(rows: list, header_row: int = 1) -> dict:
    headers = {}
    if rows and 1 <= header_row <= len(rows):
        for idx, value in enumerate(rows[header_row - 1]):
            key = str(value).strip().lower()
            if key and key not in headers:
                headers[key] = idx
    return headers


def resolve_column(spec, headers: dict) -> tuple:
    """Одна спека ('B' или 'Материалы') → (индекс, буква, как задано)."""
    spec = str(spec).strip()
    if LETTER_RE.match(spec):
        index = letter_to_index(spec)
    elif spec.lower() in headers:
        index = headers[spec.lower()]
    else:
        available = ", ".join(sorted(headers)) or "(строка заголовков пуста)"
        raise ValueError(f"Колонка {spec!r} не найдена. Доступные заголовки: {available}")
    return index, column_letter(index), spec


def resolve_columns(rows: list, specs: list, header_row: int = 1) -> list:
    """Спеки → тройки (индекс, буква, как задано), без повторов колонок."""
    headers = build_header_index(rows, header_row)
    resolved = []
    seen = set()
    for spec in specs:
        if not str(spec).strip():
            continue
        index, letter, original = resolve_column(spec, headers)
        if index in seen:
            continue
        seen.add(index)
        resolved.append((index, letter, original))
    return resolved


def describe_columns(resolved: list) -> str:
    return ", ".join(
        letter if LETTER_RE.match(spec) else f"{spec}→{letter}"
        for _, letter, spec in resolved
    )


def parse_columns_spec(spec) -> list:
    if isinstance(spec, (list, tuple)):
        return [str(part).strip() for part in spec if str(part).strip()]
    return [part.strip() for part in str(spec or "").split(",") if part.strip()]
