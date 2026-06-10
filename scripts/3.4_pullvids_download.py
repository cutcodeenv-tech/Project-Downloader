#!/usr/bin/env python3
"""
Скрипт для скачивания YouTube видео через pull-vids (docker)
Читает список ссылок из pulltube_links.txt и скачивает их в директорию проекта
"""

import os
import subprocess
import sys
import glob
import time
import re
from pathlib import Path


def get_project_name():
    """Запрашивает название проекта у пользователя"""
    while True:
        project_name = input("Введите название проекта: ").strip()
        if project_name:
            return project_name
        print("❌ Название проекта не может быть пустым!")


def extract_video_id(url):
    """
    Извлекает ID видео из YouTube URL
    
    Args:
        url: YouTube URL
    
    Returns:
        ID видео или None
    """
    # Паттерны для различных форматов YouTube URL
    patterns = [
        r'(?:v=|/)([0-9A-Za-z_-]{11}).*',  # Стандартный формат
        r'(?:embed/)([0-9A-Za-z_-]{11})',  # Embed формат
        r'(?:watch\?v=)([0-9A-Za-z_-]{11})',  # Watch формат
        r'youtu\.be/([0-9A-Za-z_-]{11})',  # Короткий формат
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    
    return None


def check_video_exists(video_dir, video_id):
    """
    Проверяет существование видео файла с данным ID
    
    Args:
        video_dir: Директория с видео
        video_id: ID видео для поиска
    
    Returns:
        True если файл существует, False иначе
    """
    if not video_id:
        return False
    
    video_extensions = ['*.mp4', '*.mkv', '*.webm', '*.avi', '*.mov', '*.flv', '*.wmv', '*.m4v']
    
    for ext in video_extensions:
        pattern = os.path.join(video_dir, f'*{video_id}*{ext[1:]}')
        matching_files = glob.glob(pattern)
        if matching_files:
            return True
    
    return False


def get_existing_videos_count(video_dir):
    """
    Подсчитывает количество видео файлов в директории
    
    Args:
        video_dir: Директория с видео
    
    Returns:
        Количество видео файлов
    """
    if not os.path.exists(video_dir):
        return 0
    
    video_extensions = ['*.mp4', '*.mkv', '*.webm', '*.avi', '*.mov', '*.flv', '*.wmv', '*.m4v']
    video_files = []
    
    for ext in video_extensions:
        pattern = os.path.join(video_dir, ext)
        video_files.extend(glob.glob(pattern))
    
    return len(video_files)


def read_pulltube_links(pulltube_file):
    """Читает ссылки из pulltube_links.txt"""
    if not os.path.exists(pulltube_file):
        return []
    
    try:
        with open(pulltube_file, 'r', encoding='utf-8') as f:
            links = [line.strip() for line in f if line.strip()]
        return links
    except Exception as e:
        print(f"❌ Ошибка при чтении файла: {e}")
        return []


def check_docker():
    """Проверяет наличие docker и docker-compose"""
    try:
        subprocess.run(['docker', '--version'], capture_output=True, check=True)
        print("✓ Docker найден")
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("❌ Docker не найден! Установите Docker Desktop")
        return False
    
    try:
        subprocess.run(['docker', 'compose', 'version'], capture_output=True, check=True)
        print("✓ Docker Compose найден")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("❌ Docker Compose не найден!")
        return False


def check_cookies_file(base_dir):
    """Проверяет наличие cookies.txt для YouTube аутентификации"""
    cookies_file = os.path.join(base_dir, 'cookies.txt')
    if os.path.exists(cookies_file):
        print(f"✓ Найден файл cookies.txt для аутентификации YouTube")
        return cookies_file
    else:
        print(f"⚠️  Файл cookies.txt не найден")
        print(f"   Если YouTube заблокирует скачивание, экспортируйте cookies из браузера")
        return None


def check_ffmpeg():
    """Проверяет наличие ffmpeg в системе"""
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("⚠️  ffmpeg не найден! Конвертация видео будет недоступна")
        print("   Установите ffmpeg: brew install ffmpeg")
        return False


def find_latest_video(directory, before_time=None):
    """
    Находит последний добавленный видео файл в директории
    
    Args:
        directory: Директория для поиска
        before_time: Искать файлы, созданные после этого времени
    
    Returns:
        Путь к найденному файлу или None
    """
    video_extensions = ['*.mp4', '*.mkv', '*.webm', '*.avi', '*.mov', '*.flv', '*.wmv', '*.m4v']
    video_files = []
    
    for ext in video_extensions:
        pattern = os.path.join(directory, ext)
        video_files.extend(glob.glob(pattern))
    
    if not video_files:
        return None
    
    # Фильтруем файлы по времени если указано
    if before_time:
        video_files = [f for f in video_files if os.path.getmtime(f) > before_time]
    
    if not video_files:
        return None
    
    # Возвращаем самый новый файл
    latest_file = max(video_files, key=os.path.getmtime)
    return latest_file


def convert_to_mp4(input_file, output_dir):
    """
    Конвертирует видео файл в mp4 через ffmpeg
    
    Args:
        input_file: Путь к исходному файлу
        output_dir: Директория для сохранения результата
    
    Returns:
        True если конвертация успешна, False иначе
    """
    if not os.path.exists(input_file):
        print(f"  ❌ Файл не найден: {input_file}")
        return False
    
    # Если файл уже mp4, ничего не делаем
    if input_file.lower().endswith('.mp4'):
        print(f"  ℹ️  Файл уже в формате MP4, конвертация не требуется")
        return True
    
    # Генерируем имя выходного файла
    input_filename = os.path.basename(input_file)
    output_filename = os.path.splitext(input_filename)[0] + '.mp4'
    output_file = os.path.join(output_dir, output_filename)
    
    # Если выходной файл уже существует, добавляем суффикс
    counter = 1
    while os.path.exists(output_file):
        output_filename = f"{os.path.splitext(input_filename)[0]}_{counter}.mp4"
        output_file = os.path.join(output_dir, output_filename)
        counter += 1
    
    print(f"  🔄 Конвертация в MP4: {os.path.basename(input_file)} -> {os.path.basename(output_file)}")
    
    try:
        # Команда ffmpeg с оптимальными параметрами
        cmd = [
            'ffmpeg',
            '-i', input_file,
            '-c:v', 'libx264',  # Видеокодек H.264
            '-preset', 'medium',  # Баланс скорости и качества
            '-crf', '23',  # Качество (18-28, меньше = лучше)
            '-c:a', 'aac',  # Аудиокодек AAC
            '-b:a', '192k',  # Битрейт аудио
            '-movflags', '+faststart',  # Оптимизация для потоковой передачи
            '-y',  # Перезаписывать выходной файл
            output_file
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True
        )
        
        # Проверяем, что файл создан
        if os.path.exists(output_file) and os.path.getsize(output_file) > 0:
            print(f"  ✓ Конвертация завершена: {os.path.basename(output_file)}")
            
            # Удаляем оригинальный файл
            try:
                os.remove(input_file)
                print(f"  🗑️  Удален оригинальный файл: {os.path.basename(input_file)}")
            except Exception as e:
                print(f"  ⚠️  Не удалось удалить оригинал: {e}")
            
            return True
        else:
            print(f"  ❌ Выходной файл не создан или пуст")
            return False
            
    except subprocess.CalledProcessError as e:
        print(f"  ❌ Ошибка при конвертации: {e}")
        if e.stderr:
            print(f"  Детали ошибки: {e.stderr[-500:]}")  # Последние 500 символов
        return False
    except Exception as e:
        print(f"  ❌ Неожиданная ошибка при конвертации: {e}")
        return False


def download_video(url, output_dir, cookies_file=None, pull_vids_dir=None, convert_to_mp4_flag=False):
    """
    Скачивает видео через pull-vids docker-compose и конвертирует в mp4
    
    Args:
        url: URL видео для скачивания
        output_dir: Директория для сохранения видео
        cookies_file: Путь к файлу cookies (опционально)
        pull_vids_dir: Директория с pull-vids (где docker-compose.yml)
        convert_to_mp4_flag: Конвертировать в mp4 после скачивания
    
    Returns:
        True если успешно, False иначе
    """
    # Создаем выходную директорию
    os.makedirs(output_dir, exist_ok=True)
    
    # Запоминаем время перед скачиванием для поиска нового файла
    before_download_time = time.time()
    
    # Команда docker-compose
    cmd = [
        'docker', 'compose', 'run', '--rm',
        '-v', f'{output_dir}:/downloads',
    ]
    
    # Добавляем volume с cookies если файл существует
    if cookies_file and os.path.exists(cookies_file):
        cmd.extend(['-v', f'{cookies_file}:/cookies.txt'])
        cmd.extend(['pull-vids', '--cookies', '/cookies.txt', '-o', '/downloads', url])
    else:
        cmd.extend(['pull-vids', '-o', '/downloads', url])
    
    # Запускаем в директории pull-vids
    try:
        print(f"  📥 Скачивание видео...")
        result = subprocess.run(
            cmd,
            cwd=pull_vids_dir,
            check=True,
            text=True
        )
        
        if result.returncode != 0:
            return False
        
        print(f"  ✓ Видео скачано")
        
        # Если нужна конвертация, ищем скачанный файл и конвертируем
        if convert_to_mp4_flag:
            # Даем время на завершение записи файла
            time.sleep(1)
            
            # Ищем новый файл
            downloaded_file = find_latest_video(output_dir, before_download_time)
            
            if downloaded_file:
                print(f"  📁 Найден файл: {os.path.basename(downloaded_file)}")
                
                # Конвертируем в mp4
                if convert_to_mp4(downloaded_file, output_dir):
                    return True
                else:
                    print(f"  ⚠️  Конвертация не удалась, но файл скачан")
                    return True  # Всё равно считаем успехом, файл же скачан
            else:
                print(f"  ⚠️  Не удалось найти скачанный файл для конвертации")
                return True  # Файл скачан, просто не нашли его
        
        return True
        
    except subprocess.CalledProcessError as e:
        print(f"  ❌ Ошибка при скачивании: {e}")
        return False
    except Exception as e:
        print(f"  ❌ Неожиданная ошибка: {e}")
        return False


def main():
    """Основная функция скрипта"""
    print("=== СКРИПТ СКАЧИВАНИЯ ВИДЕО ЧЕРЕЗ PULL-VIDS ===")
    
    # Базовые пути
    base_dir = '/Users/theseus/Projects/osnovateli_doc_framework'
    data_dir = os.path.join(base_dir, 'data')
    pull_vids_dir = os.path.join(base_dir, 'scripts', 'pull-vids')
    
    # Проверяем наличие pull-vids
    if not os.path.exists(pull_vids_dir):
        print(f"❌ Директория pull-vids не найдена: {pull_vids_dir}")
        return
    
    docker_compose_file = os.path.join(pull_vids_dir, 'docker-compose.yml')
    if not os.path.exists(docker_compose_file):
        print(f"❌ Файл docker-compose.yml не найден в {pull_vids_dir}")
        return
    
    print(f"✓ Найдена директория pull-vids: {pull_vids_dir}")
    
    # Проверяем Docker
    if not check_docker():
        return
    
    # Проверяем ffmpeg
    has_ffmpeg = check_ffmpeg()
    if has_ffmpeg:
        print("✓ ffmpeg найден - конвертация в MP4 будет выполнена")
    
    # Проверяем cookies
    cookies_file = check_cookies_file(base_dir)
    
    # Запрашиваем название проекта
    project_name = get_project_name()
    
    # Проверяем существование проекта
    project_dir = os.path.join(data_dir, project_name)
    database_dir = os.path.join(project_dir, 'database')
    
    if not os.path.exists(database_dir):
        print(f"❌ Проект {project_name} не найден в {data_dir}")
        print("Сначала запустите скрипт 0_structure.py для создания структуры проекта")
        return
    
    # Читаем pulltube_links.txt
    pulltube_file = os.path.join(database_dir, 'pulltube_links.txt')
    
    if not os.path.exists(pulltube_file):
        print(f"❌ Файл {pulltube_file} не найден!")
        print("Сначала запустите скрипт 3.2_pulltube.py для создания файла со ссылками")
        return
    
    links = read_pulltube_links(pulltube_file)
    
    if not links:
        print("❌ В файле pulltube_links.txt не найдено ссылок!")
        return
    
    print(f"✓ Найдено ссылок в pulltube_links.txt: {len(links)}")
    
    # Директория для сохранения видео
    video_dir = os.path.join(project_dir, 'video')
    os.makedirs(video_dir, exist_ok=True)
    print(f"📁 Директория для видео: {video_dir}")
    
    # Проверяем уже скачанные видео
    existing_count = get_existing_videos_count(video_dir)
    if existing_count > 0:
        print(f"📦 Уже скачано видео: {existing_count}")
    
    # Фильтруем ссылки, пропуская уже скачанные
    links_to_download = []
    links_skipped = []
    
    for url in links:
        video_id = extract_video_id(url)
        if video_id and check_video_exists(video_dir, video_id):
            links_skipped.append(url)
        else:
            links_to_download.append(url)
    
    if links_skipped:
        print(f"⏭️  Пропущено (уже скачаны): {len(links_skipped)}")
    
    if not links_to_download:
        print("\n✅ Все видео уже скачаны! Нечего обрабатывать.")
        return
    
    print(f"📊 Будет скачано новых роликов: {len(links_to_download)}")
    
    # Скачиваем видео
    print(f"\n=== СКАЧИВАНИЕ ВИДЕО ===")
    successful = 0
    failed = 0
    converted = 0
    
    for idx, url in enumerate(links_to_download, 1):
        print(f"\n[{idx}/{len(links_to_download)}] Обработка: {url}")
        
        if download_video(url, video_dir, cookies_file, pull_vids_dir, convert_to_mp4_flag=has_ffmpeg):
            print(f"  ✅ Успешно обработано")
            successful += 1
            if has_ffmpeg:
                converted += 1
        else:
            print(f"  ❌ Не удалось скачать")
            failed += 1
    
    # Итоги
    print(f"\n=== РЕЗУЛЬТАТЫ ===")
    print(f"Всего ссылок в списке: {len(links)}")
    if links_skipped:
        print(f"Пропущено (уже скачаны): {len(links_skipped)}")
    print(f"Успешно скачано новых: {successful}")
    if has_ffmpeg and converted > 0:
        print(f"Сконвертировано в MP4: {converted}")
    if failed > 0:
        print(f"Ошибок: {failed}")
    print(f"Обработано: {len(links_to_download)}")
    print(f"\n📁 Все видео сохранены в: {video_dir}")
    
    # Финальная статистика
    total_videos = get_existing_videos_count(video_dir)
    print(f"📦 Всего видео в директории: {total_videos}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n[INFO] Операция отменена пользователем.")
        sys.exit(1)
