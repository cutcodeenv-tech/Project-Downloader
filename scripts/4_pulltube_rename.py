#!/usr/bin/env python3
import argparse
import re
import sys
import time
import unicodedata
import os
import csv
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime

try:
    import yt_dlp  # type: ignore
except Exception:  # pragma: no cover
    yt_dlp = None

try:
    import requests  # type: ignore
except Exception:  # pragma: no cover
    requests = None

from path_utils import get_data_dir
_DATA_DIR = get_data_dir(__file__)

REQUEST_TIMEOUT = 20
SESSION_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
}

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi"}


def get_project_video_dir(project_name: str) -> Path:
    return _DATA_DIR / project_name / "video"

def get_project_database_dir(project_name: str) -> Path:
    return _DATA_DIR / project_name / "database"

def get_youtube_links_csv_path(project_name: str) -> Path:
    return get_project_database_dir(project_name) / f"os_doc_{project_name}_youtube_links.csv"

def get_renamed_videos_dir(project_name: str) -> Path:
    return _DATA_DIR / project_name / "renamed_videos"

def framework_root() -> Path:
    return Path(__file__).resolve().parent.parent

def default_cookies_path() -> Path:
    return framework_root() / "cookies.txt"


def browser_cookie_tuple(spec: str) -> Tuple[str, ...]:
    s = spec.strip()
    if ":" in s:
        a, b = s.split(":", 1)
        b = b.strip()
        if b:
            return (a.strip(), b)
    return (s,)


def youtube_url_host(url: str) -> str:
    try:
        match = re.match(r"^https?://([^/]+)", url, flags=re.IGNORECASE)
        return match.group(1).lower().replace("www.", "") if match else ""
    except Exception:
        return ""


def is_youtube_watch_url(url: str) -> bool:
    host = youtube_url_host(url)
    return bool(host) and ("youtube.com" in host or host == "youtu.be")


def read_links_from_csv(file_path: Path) -> List[Tuple[str, str]]:
    if not file_path.exists():
        raise FileNotFoundError(f"CSV файл со ссылками не найден: {file_path}")

    pairs: List[Tuple[str, str]] = []
    try:
        with file_path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row_num, row in enumerate(reader, start=2):
                source_address = row.get('source_address', '').strip()
                url = row.get('url', '').strip()

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
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    text = re.sub(r"[\W_]+", " ", text, flags=re.UNICODE)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def extract_youtube_title_oembed(url: str, session: object) -> Optional[str]:
    """Fastest method — YouTube oEmbed, no auth required."""
    if requests is None or session is None:
        return None
    if not is_youtube_watch_url(url):
        return None
    try:
        oembed_url = (
            "https://www.youtube.com/oembed?format=json&url="
            + requests.utils.quote(url, safe="")
        )
        response = session.get(oembed_url, headers=SESSION_HEADERS, timeout=REQUEST_TIMEOUT)
        if response.status_code >= 400:
            return None
        title = response.json().get("title")
        if title:
            return str(title).strip()
    except Exception as e:
        print(f"oEmbed не смог извлечь название: {e}", file=sys.stderr)
    return None


def extract_youtube_title_with_ytdlp(
    url: str,
    cookies_file: Optional[Path] = None,
    cookies_from_browser: Optional[str] = None,
) -> Optional[str]:
    if yt_dlp is None:
        return None
    use_auth = bool(cookies_from_browser) or bool(cookies_file and cookies_file.is_file())
    ydl_opts = {
        "quiet": True,
        "no_warnings": not use_auth,
        "skip_download": True,
    }
    if cookies_from_browser:
        ydl_opts["cookiesfrombrowser"] = browser_cookie_tuple(cookies_from_browser)
    elif cookies_file is not None and cookies_file.is_file():
        ydl_opts["cookiefile"] = str(cookies_file)
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:  # type: ignore[attr-defined]
            info = ydl.extract_info(url, download=False)
            title = info.get("title") if isinstance(info, dict) else None
            if title:
                return str(title)
    except Exception as e:
        print(f"yt-dlp не смог извлечь название: {e}", file=sys.stderr)
    return None


def extract_youtube_title_with_http(url: str) -> Optional[str]:
    if requests is None:
        return None
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        if resp.status_code != 200:
            return None
        html = resp.text
        og = re.search(r'<meta\s+property=["\']og:title["\']\s+content=["\']([^"\']+)["\']', html, re.I)
        if og:
            return og.group(1)
        t = re.search(r"<title>(.*?)</title>", html, re.I | re.S)
        if t:
            title = t.group(1)
            title = re.sub(r"\s+-\s+YouTube$", "", title).strip()
            return title
    except Exception as e:
        print(f"HTTP метод не смог извлечь название: {e}", file=sys.stderr)
    return None


def get_youtube_title(
    url: str,
    session: Optional[object] = None,
    cookies_file: Optional[Path] = None,
    cookies_from_browser: Optional[str] = None,
) -> Optional[str]:
    title = extract_youtube_title_oembed(url, session)
    if title:
        return title
    title = extract_youtube_title_with_ytdlp(url, cookies_file=cookies_file, cookies_from_browser=cookies_from_browser)
    if title:
        return title
    return extract_youtube_title_with_http(url)


def collect_video_files(directory: Path) -> List[Path]:
    if not directory.exists():
        raise FileNotFoundError(f"Директория с видео не найдена: {directory}")

    files: List[Path] = []
    for p in directory.iterdir():
        if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS:
            files.append(p)
    return files


def already_prefixed(name: str, index: str) -> bool:
    return name.startswith(f"{index} ")


def find_best_match_file(files: List[Path], title: str) -> Optional[Path]:
    norm_title = normalize_text_for_match(title)
    candidates: List[Tuple[int, Path]] = []
    for f in files:
        base = f.stem
        norm_name = normalize_text_for_match(base)
        if norm_title and norm_title in norm_name:
            candidates.append((len(norm_name), f))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def save_rename_log(project_name: str, rename_data: List[Dict]) -> None:
    database_dir = get_project_database_dir(project_name)
    log_file = database_dir / f"os_doc_{project_name}_rename_log.csv"
    database_dir.mkdir(parents=True, exist_ok=True)
    file_exists = log_file.exists()
    with log_file.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=['timestamp', 'source_address', 'original_filename', 'new_filename', 'youtube_url', 'youtube_title', 'status'])
        if not file_exists:
            writer.writeheader()
        for data in rename_data:
            writer.writerow(data)


def move_and_rename_file(source_file: Path, target_dir: Path, new_name: str, dry_run: bool = False) -> Optional[Path]:
    target_file = target_dir / new_name
    if dry_run:
        print(f"DRY-RUN: {source_file.name} -> {new_name}")
        return target_file
    target_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source_file), str(target_file))
    print(f"OK: {source_file.name} -> {new_name}")
    return target_file


def process(
    dry_run: bool = False,
    project_name: Optional[str] = None,
    cookies_file: Optional[Path] = None,
    cookies_from_browser: Optional[str] = None,
) -> None:
    if project_name is None:
        project_name = os.getenv("PROJECT_NAME", "").strip()
    if not project_name:
        while True:
            project_name = input('Введите название проекта: ').strip()
            if project_name:
                break
            print('Ошибка: название проекта не может быть пустым.')

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

    if cookies_from_browser:
        print(f"yt-dlp: cookies из браузера ({cookies_from_browser})")
    elif cookies_file is not None and cookies_file.is_file():
        print(f"Файл cookies для yt-dlp: {cookies_file}")
    elif cookies_file is not None:
        print(f"⚠️  Файл cookies не найден: {cookies_file}")
        cookies_file = None
    else:
        print("⚠️  Нет cookies для yt-dlp (oEmbed обычно достаточен). При сбоях: --cookies-from-browser firefox")

    if not csv_file.exists():
        print(f"❌ CSV файл не найден: {csv_file}")
        return

    if not video_dir.exists():
        print(f"❌ Директория с видео не найдена: {video_dir}")
        return

    try:
        pairs = read_links_from_csv(csv_file)
    except Exception as e:
        print(f"❌ Ошибка при чтении CSV файла: {e}")
        return

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

    http_session = requests.Session() if requests is not None else None

    rename_log_data = []
    successful_renames = 0
    failed_renames = 0

    for source_address, url in pairs:
        print(f"\n🔍 Обрабатываю: {source_address} -> {url}")

        title = get_youtube_title(
            url,
            session=http_session,
            cookies_file=cookies_file,
            cookies_from_browser=cookies_from_browser,
        )
        time.sleep(0.12)

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

        if already_prefixed(match.name, source_address):
            print(f"⏭️  Файл уже имеет префикс, пропуск: {match.name}")
            continue

        new_name = f"{source_address} {match.name}"
        target_file = renamed_dir / new_name
        if target_file.exists():
            print(f"⚠️  Файл с именем {new_name} уже существует, пропуск")
            continue

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

    if rename_log_data:
        save_rename_log(project_name, rename_log_data)
        print(f"\n📝 Лог переименований сохранен в CSV файл")

    print(f"\n=== РЕЗУЛЬТАТЫ ===")
    print(f"✅ Успешно перемещено и переименовано: {successful_renames}")
    print(f"❌ Ошибок: {failed_renames}")
    print(f"📁 Переименованные видео перемещены в: {renamed_dir}")

    if not dry_run and successful_renames > 0:
        print(f"\n🎉 Перемещение и переименование завершено! Проверьте директорию: {renamed_dir}")
        print(f"💾 Исходные файлы перемещены из: {video_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Переместить и переименовать видео из директории проекта, добавив префикс из CSV файла."
    )
    parser.add_argument("--dry-run", action="store_true", help="Только показать план переименований без изменений на диске")
    parser.add_argument("--project", type=str, default=None, help="Название проекта")
    parser.add_argument("--cookies", type=Path, default=None, help="Netscape cookies.txt для yt-dlp")
    parser.add_argument(
        "--cookies-from-browser",
        metavar="SPEC",
        default=None,
        help="Читать cookies из браузера (например: firefox или chrome:Profile). Надёжнее cookies.txt",
    )
    args = parser.parse_args()

    cfb = (args.cookies_from_browser or "").strip() or None

    if cfb:
        cookies_path = None
    elif args.cookies is not None:
        cookies_path = args.cookies.expanduser().resolve()
        if not cookies_path.is_file():
            print(f"❌ Файл cookies не найден: {cookies_path}", file=sys.stderr)
            sys.exit(1)
    else:
        dc = default_cookies_path()
        cookies_path = dc if dc.is_file() else None

    process(
        dry_run=args.dry_run,
        project_name=args.project,
        cookies_file=cookies_path,
        cookies_from_browser=cfb,
    )


if __name__ == "__main__":
    main()
