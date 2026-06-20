#!/usr/bin/env python3
"""
Скачивание YouTube/видео через yt-dlp (без Docker).
Читает ссылки из pulltube_links.txt, пропускает уже скачанные по video_id.
"""

import glob
import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

import yt_dlp

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


DEFAULT_VIDEO_DOWNLOAD_PAUSE_SECONDS = 4.0
DEFAULT_YTDLP_RETRY_COUNT = 3
DEFAULT_YTDLP_RETRY_BASE_SECONDS = 5.0

from path_utils import get_data_dir
from youtube_utils import youtube_url_kind

BASE_DIR = Path(os.getenv('BASE_DIR') or Path(__file__).resolve().parent.parent)
PROJECTS_ROOT = get_data_dir(__file__)
ENV_FILE = BASE_DIR / '.env'
if load_dotenv is not None and ENV_FILE.exists():
    load_dotenv(ENV_FILE, override=False)


# ── helpers ───────────────────────────────────────────────────────────────────

def is_shorts_url(url: str) -> bool:
    return '/shorts/' in url


def clean_url(url: str) -> str:
    """Убирает list= из URL если есть конкретное видео (v=), чтобы не качать плейлист."""
    parsed = urlparse(url)
    qs = parse_qs(parsed.query, keep_blank_values=True)
    if 'v' in qs and 'list' in qs:
        qs.pop('list')
        qs.pop('index', None)
        cleaned = parsed._replace(query=urlencode(qs, doseq=True))
        return urlunparse(cleaned)
    return url


def extract_video_id(url: str) -> str:
    for pat in [
        r'(?:v=|/)([0-9A-Za-z_-]{11})(?:[&?]|$)',
        r'youtu\.be/([0-9A-Za-z_-]{11})',
        r'embed/([0-9A-Za-z_-]{11})',
    ]:
        m = re.search(pat, url)
        if m:
            return m.group(1)
    return ''


def find_video_files(directory: str) -> list[str]:
    exts = ['*.mp4', '*.mkv', '*.webm', '*.avi', '*.mov', '*.flv', '*.m4v']
    files = []
    for ext in exts:
        files.extend(glob.glob(os.path.join(directory, ext)))
    return files


def video_already_downloaded(base_video_dir: str, video_id: str) -> bool:
    """Проверяет наличие видео по ID во всех папках (включая волны upd_*)."""
    if not video_id:
        return False
    search_dirs = [base_video_dir]
    if os.path.isdir(base_video_dir):
        search_dirs += [
            os.path.join(base_video_dir, d)
            for d in os.listdir(base_video_dir)
            if os.path.isdir(os.path.join(base_video_dir, d))
        ]
    for d in search_dirs:
        for ext in ['*.mp4', '*.mkv', '*.webm', '*.avi', '*.mov', '*.flv', '*.m4v']:
            if glob.glob(os.path.join(d, f'*{video_id}*{ext[1:]}')):
                return True
    return False


def _format_bytes(num: float | None) -> str:
    if not num:
        return "?"
    units = ["B", "KiB", "MiB", "GiB"]
    value = float(num)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f}{unit}"
        value /= 1024
    return f"{value:.1f}GiB"


def _format_speed(num: float | None) -> str:
    if not num:
        return "?"
    return f"{_format_bytes(num)}/s"


def _format_eta(seconds: int | float | None) -> str:
    if seconds is None:
        return "??:??"
    total = max(0, int(seconds))
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


class _YTDLPLogger:
    def debug(self, msg):
        text = (msg or "").strip()
        if text and not text.startswith("[debug]"):
            print(f"    {text}", flush=True)

    def warning(self, msg):
        text = (msg or "").strip()
        if text:
            print(f"    {text}", flush=True)

    def error(self, msg):
        text = (msg or "").strip()
        if text:
            print(f"    {text}", flush=True)


class _ProgressPrinter:
    def __init__(self):
        self.spinner_frames = "|/-\\"
        self.spinner_idx = 0
        self.active = False

    def clear(self):
        if self.active:
            print(flush=True)
            self.active = False

    def hook(self, data):
        status = data.get("status")
        if status == "downloading":
            downloaded = data.get("downloaded_bytes") or 0
            total = data.get("total_bytes") or data.get("total_bytes_estimate")
            percent = (downloaded / total * 100) if total else 0.0
            line = (
                f"[download] {percent:5.1f}% of {_format_bytes(total)} "
                f"at {_format_speed(data.get('speed'))} ETA {_format_eta(data.get('eta'))}"
            )
            if sys.stdout.isatty():
                frame = self.spinner_frames[self.spinner_idx % len(self.spinner_frames)]
                self.spinner_idx += 1
                print(f"\r    {frame} {line}", end="", flush=True)
                self.active = True
            else:
                print(f"    {line}", flush=True)
        elif status == "finished":
            self.clear()
            filename = data.get("filename")
            if filename:
                print(f"    [download] Готов файл: {os.path.basename(filename)}", flush=True)


def resolve_video_quality(value: str | None) -> str:
    quality = (value or "").strip().lower()
    if quality in {"original", "1080", "720"}:
        return quality
    return "original"


def yt_dlp_format_for_quality(quality: str) -> str:
    quality = resolve_video_quality(quality)
    if quality == "1080":
        return "bestvideo[vcodec^=avc1][height<=1080]+bestaudio[ext=m4a]/bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]/best[ext=mp4][height<=1080]/best[height<=1080]"
    if quality == "720":
        return "bestvideo[vcodec^=avc1][height<=720]+bestaudio[ext=m4a]/bestvideo[ext=mp4][height<=720]+bestaudio[ext=m4a]/best[ext=mp4][height<=720]/best[height<=720]"
    return "bestvideo[vcodec^=avc1]+bestaudio[ext=m4a]/bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"


def _env_float(name: str, default: float) -> float:
    try:
        value = float((os.getenv(name) or "").strip())
        return value if value >= 0 else default
    except Exception:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        value = int((os.getenv(name) or "").strip())
        return value if value >= 1 else default
    except Exception:
        return default


def get_video_download_pause_seconds() -> float:
    return _env_float("VIDEO_DOWNLOAD_PAUSE_SECONDS", DEFAULT_VIDEO_DOWNLOAD_PAUSE_SECONDS)


def get_ytdlp_retry_count() -> int:
    return _env_int("YTDLP_RETRY_COUNT", DEFAULT_YTDLP_RETRY_COUNT)


def get_ytdlp_retry_base_seconds() -> float:
    return _env_float("YTDLP_RETRY_BASE_SECONDS", DEFAULT_YTDLP_RETRY_BASE_SECONDS)


def get_cookies_from_browser(cli_value: str | None = None) -> str:
    for value in (cli_value, os.getenv("COOKIES_FROM_BROWSER"), os.getenv("YTDLP_COOKIES_FROM_BROWSER")):
        cleaned = (value or "").strip()
        if cleaned:
            return cleaned
    return ""


def get_cookies_file(base_dir: str) -> str | None:
    configured = (os.getenv("COOKIES_FILE") or "").strip()
    if configured:
        path = Path(configured).expanduser().resolve()
        return str(path) if path.exists() else None
    default_path = Path(base_dir) / "cookies.txt"
    return str(default_path) if default_path.exists() else None


def is_ytdlp_rate_limited(text: str) -> bool:
    lowered = (text or "").lower()
    return (
        "429" in lowered
        or "too many requests" in lowered
        or "rate limit" in lowered
        or "http error 429" in lowered
    )


# ── download ─────────────────────────────────────────────────────────────────

def download_video(url: str, output_dir: str, cookies_file: str | None, cookies_from_browser: str | None = None) -> bool:
    os.makedirs(output_dir, exist_ok=True)
    ytdlp_bin = shutil.which("yt-dlp")
    if not ytdlp_bin:
        print("  ❌ yt-dlp не найден в PATH")
        return False
    video_quality = resolve_video_quality(os.getenv("VIDEO_QUALITY"))
    retry_count = get_ytdlp_retry_count()
    retry_base_sleep = get_ytdlp_retry_base_seconds()
    browser_spec = get_cookies_from_browser(cookies_from_browser)

    def build_cmd() -> list[str]:
        cmd = [
            ytdlp_bin,
            "--format", yt_dlp_format_for_quality(video_quality),
            "--merge-output-format", "mp4",
            "--output", os.path.join(output_dir, "%(title)s [%(id)s].%(ext)s"),
            "--no-playlist",
            "--newline",
        ]
        if browser_spec:
            cmd += ["--cookies-from-browser", browser_spec]
        if cookies_file and os.path.exists(cookies_file):
            cmd += ["--cookies", cookies_file]
        cmd.append(url)
        return cmd

    print(f"  🎞️ Качество: {video_quality}")
    if browser_spec:
        print(f"  🍪 cookies-from-browser: {browser_spec}")
    elif cookies_file and os.path.exists(cookies_file):
        print(f"  🍪 cookies.txt: {os.path.basename(cookies_file)}")

    for attempt in range(1, retry_count + 1):
        lines: list[str] = []
        proc = subprocess.Popen(
            build_cmd(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                lines.append(line)
                print(line, flush=True)
        proc.wait()

        if proc.returncode == 0:
            print('  ✓ Скачано')
            return True

        joined_output = "\n".join(lines)
        if attempt < retry_count and is_ytdlp_rate_limited(joined_output):
            sleep_for = retry_base_sleep * attempt
            print(f"  ⚠️ 429 / rate limit. Повтор через {sleep_for:.1f} сек ({attempt}/{retry_count})")
            time.sleep(sleep_for)
            continue

        print(f'  ❌ yt-dlp завершился с кодом {proc.returncode}')
        return False

    return False


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--cookies-from-browser", dest="cookies_from_browser", default=None)
    args = parser.parse_args()

    print('=== СКАЧИВАНИЕ ВИДЕО ЧЕРЕЗ YT-DLP ===')

    base_dir = os.getenv('BASE_DIR') or str(Path(__file__).resolve().parent.parent)
    data_dir = str(PROJECTS_ROOT)
    project_name = os.getenv('PROJECT_NAME', '').strip()
    if not project_name:
        project_name = input('Введите название проекта: ').strip()
    if not project_name:
        print('❌ Название проекта не указано')
        return

    project_dir = os.path.join(data_dir, project_name)
    database_dir = os.path.join(project_dir, 'database')

    if not os.path.isdir(database_dir):
        print(f'❌ Проект не найден: {project_dir}')
        return

    print(f'✓ yt-dlp: {yt_dlp.version.__version__}')

    # cookies
    cookies_file = get_cookies_file(base_dir)
    if cookies_file and os.path.exists(cookies_file):
        print(f'✓ cookies.txt найден')
    else:
        print('⚠️  cookies.txt не найден (может потребоваться для YouTube)')
        cookies_file = None

    cookies_from_browser = get_cookies_from_browser(args.cookies_from_browser)
    if cookies_from_browser:
        print(f'✓ Используем cookies из браузера: {cookies_from_browser}')

    # файл со ссылками: сначала самый свежий pulltube_links_*.txt, иначе pulltube_links.txt
    timestamped = sorted(glob.glob(os.path.join(database_dir, 'pulltube_links_*.txt')), reverse=True)
    if timestamped:
        links_file = timestamped[0]
        print(f'📋 Файл ссылок (правки): {os.path.basename(links_file)}')
    else:
        links_file = os.path.join(database_dir, 'pulltube_links.txt')

    if not os.path.exists(links_file):
        print(f'❌ Файл ссылок не найден: {links_file}')
        return

    with open(links_file, encoding='utf-8') as f:
        all_links = [l.strip() for l in f if l.strip()]

    if not all_links:
        print('❌ Файл ссылок пуст')
        return

    print(f'📊 Ссылок в файле: {len(all_links)}')

    # директория для видео
    upd_subdir = os.getenv('UPD_SUBDIR', '').strip()
    base_video_dir = os.path.join(project_dir, 'video')
    renamed_dir = os.path.join(project_dir, 'renamed_videos')
    video_dir = os.path.join(base_video_dir, upd_subdir) if upd_subdir else base_video_dir
    os.makedirs(video_dir, exist_ok=True)
    if upd_subdir:
        print(f'📁 Волна правок: {upd_subdir}')
    else:
        print(f'📁 Директория: {video_dir}')

    # фильтрация: каналы/плейлисты/шортсы, дубликаты, уже скачанные, очистка list=
    to_download = []
    skipped = []
    skipped_shorts = []
    skipped_nonvideo = []
    seen_vids = set()
    for url in all_links:
        kind = youtube_url_kind(url)
        if kind == 'shorts':
            skipped_shorts.append(url)
            continue
        if kind != 'video':
            # канал / плейлист / прочее — не качаем
            skipped_nonvideo.append(url)
            continue
        url = clean_url(url)
        vid_id = extract_video_id(url)
        if vid_id and vid_id in seen_vids:
            # та же ссылка встречается несколько раз — качаем один раз
            continue
        if vid_id:
            seen_vids.add(vid_id)
        # уже скачано (в video/ или уже переименовано в renamed_videos/) — пропускаем
        already = vid_id and (
            video_already_downloaded(base_video_dir, vid_id)
            or video_already_downloaded(renamed_dir, vid_id)
        )
        if already:
            skipped.append(url)
        else:
            to_download.append(url)

    if skipped_shorts:
        print(f'⏭️  Шортсы (пропускаем): {len(skipped_shorts)}')

    if skipped_nonvideo:
        print(f'⏭️  Каналы/плейлисты (пропускаем): {len(skipped_nonvideo)}')

    if skipped:
        print(f'⏭️  Уже скачаны (пропускаем): {len(skipped)}')
    if not to_download:
        print('\n✅ Все видео уже скачаны!')
        return

    print(f'📥 Новых для скачивания: {len(to_download)}')

    # скачивание
    ok_count = 0
    fail_count = 0
    pause_seconds = get_video_download_pause_seconds()
    for idx, url in enumerate(to_download, 1):
        print(f'\n[{idx}/{len(to_download)}] {url}')
        if download_video(url, video_dir, cookies_file, cookies_from_browser):
            ok_count += 1
        else:
            fail_count += 1
        if idx < len(to_download) and pause_seconds > 0:
            print(f'  ⏳ Пауза перед следующим видео: {pause_seconds:.1f} сек')
            time.sleep(pause_seconds)

    print(f'\n=== ИТОГО ===')
    print(f'Скачано: {ok_count}  |  Ошибок: {fail_count}  |  Пропущено: {len(skipped)}')
    print(f'📁 {video_dir}')


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\n[INFO] Отменено пользователем.')
        sys.exit(1)
