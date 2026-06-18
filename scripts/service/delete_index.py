#!/usr/bin/env python3
"""
Сервисный скрипт для удаления индексов из имен файлов в директории renamed_videos
Удаляет префиксы формата "B3_1 ", "B4_2 ", добавленные скриптами pulltube_rename и motionarray_rename
"""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from path_utils import get_data_dir, resolve_project_name


def get_project_name():
    """Возвращает название проекта из окружения или запрашивает его у пользователя"""
    return resolve_project_name()


def get_renamed_videos_dir(project_name: str) -> Path:
    """Возвращает путь к директории renamed_videos для указанного проекта"""
    return get_data_dir(__file__) / project_name / "renamed_videos"


def remove_index_from_filename(filename: str) -> str:
    """
    Удаляет индекс из имени файла используя регулярное выражение.

    Паттерн индекса: [буква][цифра(ы)]_[цифра(ы)] в начале имени файла, за которым следует пробел
    Примеры: "B3_1 ", "B99_2 ", "A1_1 "

    Args:
        filename: Имя файла с индексом (например, "B3_1 video_name.mp4")

    Returns:
        Имя файла без индекса (например, "video_name.mp4")
    """
    # Паттерн: буква, одна или более цифр, подчеркивание, одна или более цифр, пробел в начале строки
    pattern = r'^[A-Za-z]\d+_\d+\s+'
    return re.sub(pattern, '', filename)


def process_directory(renamed_dir: Path, dry_run: bool = False) -> None:
    """
    Обрабатывает все файлы в директории renamed_videos, удаляя индексы из имен файлов.

    Args:
        renamed_dir: Путь к директории renamed_videos
        dry_run: Если True, только показывает план переименований без изменений
    """
    if not renamed_dir.exists():
        print(f"❌ Директория не найдена: {renamed_dir}")
        return

    files = [f for f in renamed_dir.iterdir() if f.is_file()]

    if not files:
        print(f"❌ Директория пуста: {renamed_dir}")
        return

    print(f"\n📁 Найдено файлов: {len(files)}")

    renamed_count = 0
    skipped_count = 0

    for file_path in files:
        old_name = file_path.name
        new_name = remove_index_from_filename(old_name)

        # Если имя не изменилось - файл не имеет индекса
        if old_name == new_name:
            skipped_count += 1
            continue

        new_path = file_path.parent / new_name

        # Проверяем, не существует ли уже файл с новым именем
        if new_path.exists():
            print(f"⚠️  Пропускаю (файл уже существует): {old_name}")
            skipped_count += 1
            continue

        if dry_run:
            print(f"DRY-RUN: {old_name} -> {new_name}")
        else:
            try:
                file_path.rename(new_path)
                print(f"✓ {old_name} -> {new_name}")
                renamed_count += 1
            except Exception as e:
                print(f"❌ Ошибка при переименовании {old_name}: {e}")

    print(f"\n=== РЕЗУЛЬТАТЫ ===")
    print(f"✅ Переименовано файлов: {renamed_count}")
    print(f"⏭️  Пропущено файлов: {skipped_count}")


def main():
    """Основная функция скрипта"""
    print("=== УДАЛЕНИЕ ИНДЕКСОВ ИЗ ИМЕН ФАЙЛОВ ===")

    # Получаем название проекта
    project_name = get_project_name()

    # Получаем путь к директории renamed_videos
    renamed_dir = get_renamed_videos_dir(project_name)

    print(f"\nПроект: {project_name}")
    print(f"Директория: {renamed_dir}")
    print("\nВНИМАНИЕ: Файлы будут переименованы!\n")

    # Запрашиваем подтверждение
    confirm = input("Продолжить? (yes/no): ").strip().lower()

    if confirm not in ['yes', 'y', 'да']:
        print("Операция отменена.")
        return

    # Обрабатываем директорию
    process_directory(renamed_dir, dry_run=False)


if __name__ == "__main__":
    main()
