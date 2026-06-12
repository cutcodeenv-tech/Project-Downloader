#!/usr/bin/env python3
import argparse
import re
import sys
import unicodedata
import os
import csv
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime

try:
    # yt_dlp is preferred for reliable title extraction
    import yt_dlp  # type: ignore
except Exception:  # pragma: no cover
    yt_dlp = None  # fallback to requests/HTML

try:
    import requests  # type: ignore
except Exception:  # pragma: no cover
    requests = None


def get_project_name():
    """Запрашивает у пользователя название проекта"""
    while True:
        name = input('Введите название проекта: ').strip()
        if name:
            return name
        print('Ошибка: название проекта не может быть пустым.')

def get_project_video_dir(project_name: str) -> Path:
    """Возвращает путь к директории video для указанного проекта"""
    return Path("/Users/theseus/Projects/osnovateli_doc_framework/data") / project_name / "video"

def get_project_database_dir(project_name: str) -> Path:
    """Возвращает путь к директории database для указанного проекта"""
    return Path("/Users/theseus/Projects/osnovateli_doc_framework/data") / project_name / "database"

def get_youtube_links_csv_path(project_name: str) -> Path:
    """Возвращает путь к CSV файлу с YouTube ссылками для указанного проекта"""
    return get_project_database_dir(project_name) / f"osnovateli_doc_{project_name}_youtube_links.csv"

def get_renamed_videos_dir(project_name: str) -> Path:
    """Возвращает путь к директории для переименованных видео"""
    return Path("/Users/theseus/Projects/osnovateli_doc_framework/data") / project_name / "renamed_videos"

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi"}


def read_links_from_csv(file_path: Path) -> List[Tuple[str, str]]:
    """Читает ссылки из CSV файла проекта.
    
    Ожидаемый формат CSV:
    source_address,url
    B3_1,https://www.youtube.com/watch?v=...
    
    Возвращает список кортежей: (source_address, url)
    """
    if not file_path.exists():
        raise FileNotFoundError(f"CSV файл со ссылками не найден: {file_path}")

    pairs: List[Tuple[str, str]] = []
    try:
        with file_path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row_num, row in enumerate(reader, start=2):  # начинаем с 2, так как строка 1 - заголовок
                source_address = row.get('source_address', '').strip()
                url = row.get('url', '').strip()
                
                # Пропускаем строки upd_ и пустые
                if source_address and url and not source_address.startswith('upd_'):
                    pairs.append((source_address, url))
                elif source_address.startswith('upd_'):
                    print(f"Пропущена строка обновления: {source_address}")
                elif not source_address or not url:
                    print(f"Пропущена пустая строка {row_num}: source_address='{source_address}', url='{url}'")
    except Exception as e:
        print(f"Ошибка при чтении CSV файла: {e}", file=sys.stderr)
        raise
    
    return pairs


def normalize_text_for_match(text: str) -> str:
    """Normalize text to improve fuzzy matching between title and filenames.

    - Lowercase
    - NFKD normalize and remove diacritics
    - Replace non-alphanumeric with single spaces
    - Collapse multiple spaces
    """
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    # Remove common bracketed suffixes PullTube may add, keep generic normalization
    text = re.sub(r"[\W_]+", " ", text, flags=re.UNICODE)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def extract_youtube_title_with_ytdlp(url: str) -> Optional[str]:
    if yt_dlp is None:
        return None
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:  # type: ignore[attr-defined]
            info = ydl.extract_info(url, download=False)
            title = info.get("title") if isinstance(info, dict) else None
            if title:
                return str(title)
    except Exception as e:  # pragma: no cover
        print(f"yt-dlp не смог извлечь название: {e}", file=sys.stderr)
    return None


def extract_youtube_title_with_http(url: str) -> Optional[str]:
    if requests is None:
        return None
    try:
        resp = requests.get(url, timeout=20)
        if resp.status_code != 200:
            return None
        html = resp.text
        # Prefer OpenGraph title, then <title>
        og = re.search(r'<meta\s+property=["\']og:title["\']\s+content=["\']([^"\']+)["\']', html, re.I)
        if og:
            return og.group(1)
        t = re.search(r"<title>(.*?)</title>", html, re.I | re.S)
        if t:
            title = t.group(1)
            title = re.sub(r"\s+-\s+YouTube$", "", title).strip()
            return title
    except Exception as e:  # pragma: no cover
        print(f"HTTP метод не смог извлечь название: {e}", file=sys.stderr)
    return None


def get_youtube_title(url: str) -> Optional[str]:
    title = extract_youtube_title_with_ytdlp(url)
    if title:
        return title
    return extract_youtube_title_with_http(url)


def collect_video_files(directory: Path) -> List[Path]:
    """Собирает все видеофайлы из указанной директории"""
    if not directory.exists():
        raise FileNotFoundError(f"Директория с видео не найдена: {directory}")
    
    files: List[Path] = []
    for p in directory.iterdir():
        if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS:
            files.append(p)
    return files


def already_prefixed(name: str, index: str) -> bool:
    # Avoid double-prefixing if the file already has the exact index prefix
    return name.startswith(f"{index} ")


def find_best_match_file(files: List[Path], title: str) -> Optional[Path]:
    norm_title = normalize_text_for_match(title)
    candidates: List[Tuple[int, Path]] = []
    for f in files:
        base = f.stem
        norm_name = normalize_text_for_match(base)
        if norm_title and norm_title in norm_name:
            # prefer longer filenames (often include extras, e.g., channel, resolution)
            candidates.append((len(norm_name), f))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def save_rename_log(project_name: str, rename_data: List[Dict]) -> None:
    """Сохраняет лог переименований в CSV файл"""
    database_dir = get_project_database_dir(project_name)
    log_file = database_dir / f"osnovateli_doc_{project_name}_rename_log.csv"
    
    # Создаем директорию если не существует
    database_dir.mkdir(parents=True, exist_ok=True)
    
    # Определяем, нужно ли писать заголовки
    file_exists = log_file.exists()
    
    with log_file.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=['timestamp', 'source_address', 'original_filename', 'new_filename', 'youtube_url', 'youtube_title', 'status'])
        
        if not file_exists:
            writer.writeheader()
        
        for data in rename_data:
            writer.writerow(data)

def move_and_rename_file(source_file: Path, target_dir: Path, new_name: str, dry_run: bool = False) -> Optional[Path]:
    """Перемещает файл в целевую директорию с новым именем"""
    target_file = target_dir / new_name
    
    if dry_run:
        print(f"DRY-RUN: {source_file.name} -> {new_name}")
        return target_file
    
    # Создаем целевую директорию если не существует
    target_dir.mkdir(parents=True, exist_ok=True)
    
    # Перемещаем файл
    shutil.move(str(source_file), str(target_file))
    print(f"OK: {source_file.name} -> {new_name}")
    return target_file


def process(dry_run: bool = False, project_name: Optional[str] = None) -> None:
    """Основная функция обработки видео"""
    if project_name is None:
        project_name = get_project_name()
    
    # Получаем пути к директориям проекта
    upd_subdir = os.getenv("UPD_SUBDIR", "").strip()
    base_video_dir = get_project_video_dir(project_name)
    video_dir = base_video_dir / upd_subdir if upd_subdir else base_video_dir
    csv_file = get_youtube_links_csv_path(project_name)
    renamed_dir = get_renamed_videos_dir(project_name)
    
    print(f"\n=== ПЕРЕМЕЩЕНИЕ И ПЕРЕИМЕНОВАНИЕ ВИДЕО ===")
    print(f"Проект: {project_name}")
    print(f"Директория с видео: {video_dir}")
    print(f"CSV файл со ссылками: {csv_file}")
    print(f"Директория для переименованных видео: {renamed_dir}")
    if dry_run:
        print("Режим: DRY-RUN (только показ плана переименований)")
    else:
        print("⚠️  ВНИМАНИЕ: Файлы будут ПЕРЕМЕЩЕНЫ (не скопированы)!")

    # Проверяем существование необходимых файлов и директорий
    if not csv_file.exists():
        print(f"❌ CSV файл не найден: {csv_file}")
        print("Сначала запустите скрипт 1_parse_links.py для создания CSV файла с ссылками.")
        return
    
    if not video_dir.exists():
        print(f"❌ Директория с видео не найдена: {video_dir}")
        print("Убедитесь, что видеофайлы находятся в правильной директории.")
        return

    # Читаем ссылки из CSV
    try:
        pairs = read_links_from_csv(csv_file)
    except Exception as e:
        print(f"❌ Ошибка при чтении CSV файла: {e}")
        return

    # Собираем видеофайлы
    try:
        files = collect_video_files(video_dir)
    except Exception as e:
        print(f"❌ Ошибка при сборе видеофайлов: {e}")
        return

    if not pairs:
        print("CSV файл пуст или не содержит корректных ссылок.")
        return
    if not files:
        print("В директории с видео не найдено файлов подходящих расширений.")
        return

    print(f"\n📊 Найдено ссылок в CSV: {len(pairs)}")
    print(f"📊 Найдено видеофайлов: {len(files)}")

    # Список для лога переименований
    rename_log_data = []
    successful_renames = 0
    failed_renames = 0

    # Обрабатываем каждую ссылку
    for source_address, url in pairs:
        print(f"\n🔍 Обрабатываю: {source_address} -> {url}")
        
        # Получаем название видео с YouTube
        title = get_youtube_title(url)
        if not title:
            print(f"❌ Не удалось извлечь название для {source_address}")
            rename_log_data.append({
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'source_address': source_address,
                'original_filename': '',
                'new_filename': '',
                'youtube_url': url,
                'youtube_title': '',
                'status': 'FAILED - не удалось извлечь название'
            })
            failed_renames += 1
            continue

        print(f"📺 Название: {title}")

        # Ищем соответствующий файл
        match = find_best_match_file(files, title)
        if not match:
            print(f"❌ Не найден соответствующий файл для: {source_address}")
            rename_log_data.append({
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'source_address': source_address,
                'original_filename': '',
                'new_filename': '',
                'youtube_url': url,
                'youtube_title': title,
                'status': 'FAILED - файл не найден'
            })
            failed_renames += 1
            continue

        print(f"📁 Найден файл: {match.name}")

        # Проверяем, не переименован ли уже файл
        if already_prefixed(match.name, source_address):
            print(f"⏭️  Файл уже имеет префикс, пропуск: {match.name}")
            continue

        # Создаем новое имя файла
        new_name = f"{source_address} {match.name}"
        
        # Проверяем, не существует ли уже файл с таким именем
        target_file = renamed_dir / new_name
        if target_file.exists():
            print(f"⚠️  Файл с именем {new_name} уже существует, пропуск")
            continue

        # Перемещаем и переименовываем файл
        try:
            result_file = move_and_rename_file(match, renamed_dir, new_name, dry_run=dry_run)
            if result_file:
                rename_log_data.append({
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'source_address': source_address,
                    'original_filename': match.name,
                    'new_filename': new_name,
                    'youtube_url': url,
                    'youtube_title': title,
                    'status': 'SUCCESS'
                })
                successful_renames += 1
                
                # Удаляем файл из списка, чтобы избежать повторного использования
                files.remove(match)
        except Exception as e:
            print(f"❌ Ошибка при перемещении файла: {e}")
            rename_log_data.append({
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'source_address': source_address,
                'original_filename': match.name,
                'new_filename': new_name,
                'youtube_url': url,
                'youtube_title': title,
                'status': f'FAILED - {str(e)}'
            })
            failed_renames += 1

    # Сохраняем лог переименований
    if rename_log_data:
        save_rename_log(project_name, rename_log_data)
        print(f"\n📝 Лог переименований сохранен в CSV файл")

    # Выводим итоговую статистику
    print(f"\n=== РЕЗУЛЬТАТЫ ===")
    print(f"✅ Успешно перемещено и переименовано: {successful_renames}")
    print(f"❌ Ошибок: {failed_renames}")
    print(f"📁 Переименованные видео перемещены в: {renamed_dir}")
    
    if not dry_run and successful_renames > 0:
        print(f"\n🎉 Перемещение и переименование завершено! Проверьте директорию: {renamed_dir}")
        print(f"💾 Исходные файлы перемещены из: {video_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Переместить и переименовать видео из директории проекта, добавив префикс из CSV файла."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Только показать план переименований без изменений на диске",
    )
    parser.add_argument(
        "--project",
        type=str,
        default=None,
        help="Название проекта (если не указано, будет запрошено интерактивно)",
    )
    args = parser.parse_args()

    project_name = args.project

    process(dry_run=args.dry_run, project_name=project_name)


if __name__ == "__main__":
    main()


