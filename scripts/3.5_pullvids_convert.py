#!/usr/bin/env python3
"""
Скрипт для конвертации скачанных видео в формат MP4 через ffmpeg.
Обрабатывает все видеофайлы не в формате mp4 в директории video проекта.
"""

import os
import subprocess
import sys
from pathlib import Path
from path_utils import get_data_dir, resolve_project_name


def get_project_name():
    """Возвращает название проекта из окружения или запрашивает его у пользователя"""
    return resolve_project_name()


def check_ffmpeg():
    """Проверяет наличие ffmpeg в системе"""
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("❌ ffmpeg не найден! Установите ffmpeg: brew install ffmpeg")
        return False


def find_non_mp4_videos(video_dir):
    """
    Находит все видеофайлы в директории, которые не являются MP4.

    Returns:
        Список путей к файлам
    """
    video_path = Path(video_dir)
    if not video_path.exists():
        return []

    non_mp4_extensions = {'.mkv', '.webm', '.avi', '.mov', '.flv', '.wmv', '.m4v'}
    video_files = [
        str(file_path)
        for file_path in video_path.iterdir()
        if file_path.is_file() and file_path.suffix.lower() in non_mp4_extensions
    ]

    return sorted(video_files)


def convert_to_mp4(input_file, output_dir):
    """
    Конвертирует видеофайл в mp4 через ffmpeg.

    Returns:
        True если конвертация успешна, False иначе
    """
    if not os.path.exists(input_file):
        print(f"  ❌ Файл не найден: {input_file}")
        return False

    if input_file.lower().endswith('.mp4'):
        print(f"  ℹ️  Файл уже в формате MP4, конвертация не требуется")
        return True

    input_filename = os.path.basename(input_file)
    output_filename = os.path.splitext(input_filename)[0] + '.mp4'
    output_file = os.path.join(output_dir, output_filename)

    counter = 1
    while os.path.exists(output_file):
        output_filename = f"{os.path.splitext(input_filename)[0]}_{counter}.mp4"
        output_file = os.path.join(output_dir, output_filename)
        counter += 1

    print(f"  🔄 {os.path.basename(input_file)} -> {os.path.basename(output_file)}")

    try:
        cmd = [
            'ffmpeg',
            '-i', input_file,
            '-c:v', 'libx264',
            '-preset', 'medium',
            '-crf', '23',
            '-c:a', 'aac',
            '-b:a', '192k',
            '-movflags', '+faststart',
            '-y',
            output_file
        ]

        subprocess.run(cmd, capture_output=True, text=True, check=True)

        if os.path.exists(output_file) and os.path.getsize(output_file) > 0:
            print(f"  ✓ Готово: {os.path.basename(output_file)}")
            try:
                os.remove(input_file)
                print(f"  🗑️  Удален оригинал: {os.path.basename(input_file)}")
            except Exception as e:
                print(f"  ⚠️  Не удалось удалить оригинал: {e}")
            return True
        else:
            print(f"  ❌ Выходной файл не создан или пуст")
            return False

    except subprocess.CalledProcessError as e:
        print(f"  ❌ Ошибка при конвертации: {e}")
        if e.stderr:
            print(f"  Детали: {e.stderr[-500:]}")
        return False
    except Exception as e:
        print(f"  ❌ Неожиданная ошибка: {e}")
        return False


def main():
    """Основная функция скрипта"""
    print("=== КОНВЕРТАЦИЯ ВИДЕО В MP4 ===")

    data_dir = get_data_dir(__file__)

    if not check_ffmpeg():
        return

    project_name = os.getenv("PROJECT_NAME", "").strip() or get_project_name()

    project_dir = os.path.join(str(data_dir), project_name)
    video_dir = os.path.join(project_dir, 'video')

    if not os.path.exists(video_dir):
        print(f"❌ Директория с видео не найдена: {video_dir}")
        return

    print(f"📁 Директория с видео: {video_dir}")

    files_to_convert = find_non_mp4_videos(video_dir)

    if not files_to_convert:
        print("✅ Все видео уже в формате MP4, конвертация не требуется.")
        return

    print(f"📊 Файлов для конвертации: {len(files_to_convert)}")

    successful = 0
    failed = 0

    for idx, filepath in enumerate(files_to_convert, 1):
        print(f"\n[{idx}/{len(files_to_convert)}] {os.path.basename(filepath)}")
        if convert_to_mp4(filepath, video_dir):
            successful += 1
        else:
            failed += 1

    print(f"\n=== РЕЗУЛЬТАТЫ ===")
    print(f"✅ Успешно сконвертировано: {successful}")
    if failed:
        print(f"❌ Ошибок: {failed}")
    print(f"📁 Директория: {video_dir}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n[INFO] Операция отменена пользователем.")
        sys.exit(1)
