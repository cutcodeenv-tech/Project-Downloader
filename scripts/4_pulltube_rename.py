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
from youtube_utils import youtube_url_kind, clean_url, extract_video_id
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
    oembed_url = (
        "https://www.youtube.com/oembed?format=json&url="
        + requests.utils.quote(url, safe="")
    )
    # На больших объёмах YouTube начинает отдавать 429 — делаем backoff и повтор.
    for attempt in range(3):
        try:
            response = session.get(oembed_url, headers=SESSION_HEADERS, timeout=REQUEST_TIMEOUT)
            if response.status_code == 429:
                if attempt < 2:
                    retry_after = (response.headers.get("Retry-After") or "").strip()
                    wait = min(float(retry_after), 60.0) if retry_after.isdigit() else min(2.0 * (attempt + 1), 30.0)
                    time.sleep(wait)
                    continue
                return None
            if response.status_code >= 400:
                return None
            title = response.json().get("title")
            if title:
                return str(title).strip()
            return None
        except Exception as e:
            print(f"oEmbed не смог извлечь название: {e}", file=sys.stderr)
            return None
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


def _strip_source_prefix(filename: str) -> str:
    """'B5_1 Title [id].mp4' -> 'Title [id].mp4' (убирает префикс источника)."""
    return re.sub(r'^[A-Za-z]+\d+(?:_\d+)? ', '', filename, count=1)


def find_file_by_video_id(files: List[Path], video_id: str) -> Optional[Path]:
    """Ищет скачанный файл по [id] в имени (yt-dlp кладёт '%(title)s [%(id)s].ext')."""
    if not video_id:
        return None
    tag = f"[{video_id}]"
    for f in files:
        if tag in f.name:
            return f
    return None


def find_best_match_file(files: List[Path], title: str, norm_by_path: Dict[Path, str]) -> Optional[Path]:
    norm_title = normalize_text_for_match(title)
    if not norm_title:
        return None
    candidates: List[Tuple[int, Path]] = []
    for f in files:
        # Нормализация имени берётся из кэша — иначе при 1000 файлов и 1000 ссылок
        # получаем 1_000_000 NFKD+regex нормализаций (O(N²)).
        norm_name = norm_by_path.get(f)
        if norm_name is None:
            norm_name = normalize_text_for_match(f.stem)
            norm_by_path[f] = norm_name
        if norm_title in norm_name:
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

    # Нормализуем имена файлов один раз (см. find_best_match_file).
    norm_by_path: Dict[Path, str] = {f: normalize_text_for_match(f.stem) for f in files}

    rename_log_data = []
    successful_renames = 0
    failed_renames = 0

    def _log(source_address, original, new_name, url, title, status):
        rename_log_data.append({
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'source_address': source_address,
            'original_filename': original,
            'new_filename': new_name,
            'youtube_url': url,
            'youtube_title': title,
            'status': status,
        })

    # Группируем ячейки по видео; каналы/шортсы/плейлисты пропускаем.
    groups: Dict[str, Dict] = {}
    skipped_nonvideo = 0
    for source_address, url in pairs:
        if youtube_url_kind(url) != 'video':
            skipped_nonvideo += 1
            print(f"⏭️  Пропуск (не одиночное видео): {source_address} -> {url}")
            continue
        cleaned = clean_url(url)
        vid = extract_video_id(cleaned)
        key = vid or cleaned
        group = groups.setdefault(key, {'url': cleaned, 'vid': vid, 'cells': []})
        group['cells'].append(source_address)

    if skipped_nonvideo:
        print(f"\n⏭️  Пропущено ссылок (каналы/шортсы/плейлисты): {skipped_nonvideo}")

    for key, group in groups.items():
        cells = group['cells']
        url = group['url']
        vid = group['vid']
        dup_note = f"  (повторов: {len(cells)})" if len(cells) > 1 else ""
        print(f"\n🔍 Видео {vid or url}{dup_note} → ячейки: {', '.join(cells)}")

        # base_name — имя файла без префикса источника; canonical — готовая копия для copy.
        base_name: Optional[str] = None
        canonical: Optional[Path] = None  # уже переименованный файл (для copy)
        src_in_video: Optional[Path] = None  # свежий файл из video/ (для move)

        # 1) Идемпотентность: уже переименованная копия этого видео в renamed_videos.
        if vid and renamed_dir.exists():
            for f in renamed_dir.iterdir():
                if f.is_file() and f"[{vid}]" in f.name and f.suffix.lower() in VIDEO_EXTENSIONS:
                    canonical = f
                    base_name = _strip_source_prefix(f.name)
                    break

        # 2) Иначе берём свежий файл из video/: сначала по [id], потом по названию.
        if canonical is None:
            src_in_video = find_file_by_video_id(files, vid)
            if src_in_video is None:
                title = get_youtube_title(
                    url, session=http_session,
                    cookies_file=cookies_file, cookies_from_browser=cookies_from_browser,
                )
                time.sleep(0.12)
                if not title:
                    print("❌ Не удалось извлечь название")
                    for sa in cells:
                        _log(sa, '', '', url, '', 'FAILED - не удалось извлечь название')
                        failed_renames += 1
                    continue
                src_in_video = find_best_match_file(files, title, norm_by_path)
            if src_in_video is None:
                print("❌ Соответствующий файл не найден")
                for sa in cells:
                    _log(sa, '', '', url, '', 'FAILED - файл не найден')
                    failed_renames += 1
                continue
            base_name = src_in_video.name
            print(f"📁 Файл: {src_in_video.name}")

        # 3) Распределяем по всем ячейкам: первой — move, остальным — копии.
        for source_address in cells:
            new_name = f"{source_address} {base_name}"
            target_file = renamed_dir / new_name
            if target_file.exists():
                print(f"⏭️  Уже есть: {new_name}")
                canonical = canonical or target_file
                continue
            try:
                if not dry_run:
                    renamed_dir.mkdir(parents=True, exist_ok=True)
                if src_in_video is not None:
                    # первый файл — перемещаем
                    original = src_in_video.name
                    if dry_run:
                        print(f"DRY-RUN move: {src_in_video.name} -> {new_name}")
                    else:
                        shutil.move(str(src_in_video), str(target_file))
                        print(f"OK move: -> {new_name}")
                        files.remove(src_in_video)
                    canonical = target_file
                    src_in_video = None
                else:
                    # остальные ячейки — копируем из готовой версии
                    if canonical is None:
                        print(f"❌ Нет исходного файла для копии: {new_name}")
                        _log(source_address, '', new_name, url, base_name, 'FAILED - нет файла для копии')
                        failed_renames += 1
                        continue
                    if dry_run:
                        print(f"DRY-RUN copy: {canonical.name} -> {new_name}")
                    else:
                        shutil.copy2(str(canonical), str(target_file))
                        print(f"OK copy: -> {new_name}")
                    original = canonical.name
                _log(source_address, original, new_name, url, base_name, 'SUCCESS')
                successful_renames += 1
            except Exception as e:
                print(f"❌ Ошибка: {e}")
                _log(source_address, base_name or '', new_name, url, base_name, f'FAILED - {str(e)}')
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
