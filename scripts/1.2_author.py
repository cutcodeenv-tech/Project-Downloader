#!/usr/bin/env python3
"""
Скрипт для создания PNG-файлов с подписью источника на основе данных из CSV.
Читает данные из файла, созданного скриптом 1.4_title_enricher.py.
"""

import csv
import re
from pathlib import Path
from typing import List, Tuple

from PIL import Image, ImageDraw, ImageFont


def get_project_name() -> str:
    """Спрашивает у пользователя название проекта."""
    while True:
        project_name = input("Введите название проекта: ").strip()
        if project_name:
            return project_name
        print("Название проекта не может быть пустым.")


def get_project_database_dir(project_name: str) -> Path:
    """Путь к папке database выбранного проекта."""
    return Path("/Users/theseus/Projects/osnovateli_doc_framework/data") / project_name / "database"


def get_project_author_dir(project_name: str) -> Path:
    """Путь к папке author выбранного проекта."""
    return Path("/Users/theseus/Projects/osnovateli_doc_framework/data") / project_name / "author"


def get_channels_csv_path(project_name: str) -> Path:
    """Путь к CSV файлу с каналами, созданному скриптом 1.4_title_enricher.py."""
    return get_project_database_dir(project_name) / f"osnovateli_doc_{project_name}_channels.csv"


def read_channels_from_csv(csv_file: Path) -> List[Tuple[str, str, str]]:
    """Читает данные из CSV файла с каналами.
    
    Ожидаемый формат CSV (создается скриптом 1.4_title_enricher.py):
    source_address,url,channel
    B8_6,https://youtu.be/...,IBTimes UK
    
    Возвращает список кортежей: (source_address, url, channel_name)
    """
    if not csv_file.exists():
        raise FileNotFoundError(f"CSV файл не найден: {csv_file}")

    data: List[Tuple[str, str, str]] = []
    with open(csv_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            source_address = row.get('source_address', '').strip()
            url = row.get('url', '').strip()
            channel_name = row.get('channel', '').strip()
            
            # Пропускаем строки upd_ и пустые
            if source_address and url and not source_address.startswith('upd_'):
                # Если канал не указан, используем заглушку
                if not channel_name:
                    channel_name = "Неизвестный канал"
                data.append((source_address, url, channel_name))
    return data


def create_author_images(channels_data: List[Tuple[str, str, str]], author_dir: Path) -> None:
    """Создает изображения на основе данных из CSV файла."""
    print("\nСоздаю изображения с источниками...")

    created_count = 0
    skipped_count = 0

    for idx, (source_address, url, channel_name) in enumerate(channels_data, 1):
        print(f"[{idx}/{len(channels_data)}] {source_address} - {channel_name}")

        source_text = format_source_text(channel_name)
        filename = f"{source_address}_author.png"
        output_path = author_dir / filename

        if output_path.exists():
            print(f"  Пропущено (файл уже существует)")
            skipped_count += 1
            continue

        try:
            create_author_image(source_address, source_text, output_path)
            created_count += 1
        except Exception as e:
            print(f"  Ошибка при создании изображения: {e}")

    print(f"\nСоздано изображений: {created_count}")
    print(f"Пропущено (файлы уже были): {skipped_count}")


def format_source_text(channel_name: str) -> str:
    """Форматирует текст в формат 'Источник: youtube канал «название канала»'."""
    channel_name = re.sub(r'\s+', ' ', channel_name.strip())
    return f"Источник: youtube-канал «{channel_name}»"


def create_author_image(source_address: str, source_text: str, output_path: Path):
    """Создает PNG изображение 1920x1080 с текстом в левом нижнем углу."""
    width, height = 1920, 1080
    image = Image.new('RGBA', (width, height), color=(0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    font_size = 30
    try:
        project_font_path = "/Users/theseus/Projects/osnovateli_doc_framework/assets/font/theater.bold-condensed.ttf"
        font = ImageFont.truetype(project_font_path, font_size)
    except Exception:
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Arial.ttf", font_size)
        except Exception:
            try:
                font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", font_size)
            except Exception:
                font = ImageFont.load_default()

    text_color = (255, 255, 255)
    margin = 50

    # Фиксированная позиция от низа страницы
    text_x = margin
    text_y = height - margin  # Фиксированное расстояние от низа

    # Используем anchor="ls" (left-bottom) чтобы текст привязывался к нижней границе
    # Это гарантирует, что текст всегда будет на одном уровне независимо от его высоты
    draw.text((text_x, text_y), source_text, fill=text_color, font=font, anchor="ls")

    image.save(output_path, 'PNG')
    print(f"Создано изображение: {output_path.name}")


def main():
    """Точка входа."""
    print("=== Создание изображений с источниками ===")

    project_name = get_project_name()

    database_dir = get_project_database_dir(project_name)
    author_dir = get_project_author_dir(project_name)
    csv_file = get_channels_csv_path(project_name)

    if not csv_file.exists():
        print(f"Файл {csv_file} не найден.")
        print(f"Сначала запустите скрипт 1.4_title_enricher.py для создания CSV файла с каналами.")
        return

    author_dir.mkdir(parents=True, exist_ok=True)

    print(f"\nЧитаю данные из {csv_file.name}...")
    try:
        channels_data = read_channels_from_csv(csv_file)
        print(f"Найдено записей: {len(channels_data)}")
    except Exception as e:
        print(f"Ошибка при чтении CSV файла: {e}")
        return

    if not channels_data:
        print("В CSV файле не найдено данных для обработки.")
        return

    create_author_images(channels_data, author_dir)

    print(f"\nГотово. Изображения лежат в {author_dir}")


if __name__ == "__main__":
    main()

