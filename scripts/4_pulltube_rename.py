#!/usr/bin/env python3
import argparse
import re
import sys
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional, Tuple

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

def get_youtube_links_path(project_name: str) -> Path:
    """Возвращает путь к файлу youtube_links.txt для указанного проекта"""
    return (
        Path.home()
        / "Downloads"
        / "download_all"
        / project_name
        / "1_parse_links"
        / "youtube_links.txt"
    )

PULLTUBE_DIR = Path.home() / "Downloads" / "PullTube"

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi"}


def read_links(file_path: Path) -> List[Tuple[str, str]]:
    """Read index:url pairs from the provided file.

    Expected line format:
    "B3 1 : https://www.youtube.com/watch?v=..."
    Returns list of tuples: (index, url)
    """
    if not file_path.exists():
        raise FileNotFoundError(f"Файл со ссылками не найден: {file_path}")

    pairs: List[Tuple[str, str]] = []
    pattern = re.compile(r"^\s*(?P<idx>[^:]+?)\s*:\s*(?P<url>https?://\S+)\s*$")
    with file_path.open("r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            m = pattern.match(line)
            if not m:
                # Skip lines that do not conform, but report once to stderr
                print(
                    f"Строка {line_num} имеет неожиданный формат и будет пропущена: {line}",
                    file=sys.stderr,
                )
                continue
            idx = m.group("idx").strip()
            url = m.group("url").strip()
            pairs.append((idx, url))
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


def collect_pulltube_files(directory: Path) -> List[Path]:
    if not directory.exists():
        raise FileNotFoundError(f"Папка PullTube не найдена: {directory}")
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


def rename_file_with_index(file_path: Path, index: str, dry_run: bool = False) -> Optional[Path]:
    new_name = f"{index} {file_path.name}"
    new_path = file_path.with_name(new_name)
    if dry_run:
        print(f"DRY-RUN: {file_path.name} -> {new_name}")
        return new_path
    file_path.rename(new_path)
    print(f"OK: {file_path.name} -> {new_name}")
    return new_path


def process(dry_run: bool = False, links_path: Optional[Path] = None, pulltube_dir: Optional[Path] = None, project_name: Optional[str] = None) -> None:
    if links_path is None:
        if project_name is None:
            project_name = get_project_name()
        links_file = get_youtube_links_path(project_name)
    else:
        links_file = links_path
    
    target_dir = pulltube_dir or PULLTUBE_DIR

    print(f"\n=== ПЕРЕИМЕНОВАНИЕ ВИДЕО ИЗ PULLTUBE ===")
    if project_name:
        print(f"Проект: {project_name}")
    print(f"Файл со ссылками: {links_file}")
    print(f"Папка PullTube: {target_dir}")
    if dry_run:
        print("Режим: DRY-RUN (только показ плана переименований)")

    pairs = read_links(links_file)
    files = collect_pulltube_files(target_dir)

    if not pairs:
        print("Файл ссылок пуст или не содержит корректных строк.")
        return
    if not files:
        print("В папке PullTube не найдено видеофайлов подходящих расширений.")
        return

    # Build a lookup to quickly re-check current files list for each iteration
    for idx, url in pairs:
        title = get_youtube_title(url)
        if not title:
            print(f"Пропуск: не удалось извлечь название для {idx} : {url}")
            continue

        match = find_best_match_file(files, title)
        if not match:
            print(f"Не найден соответствующий файл для: {idx} : {title}")
            continue

        if already_prefixed(match.name, idx):
            print(f"Уже префиксировано, пропуск: {match.name}")
            continue

        # Ensure target name doesn't already exist
        planned_new = match.with_name(f"{idx} {match.name}")
        if planned_new.exists():
            print(f"Целевое имя уже существует, пропуск: {planned_new.name}")
            continue

        new_path = rename_file_with_index(match, idx, dry_run=dry_run)
        if new_path is not None and not dry_run:
            # Update files list to reflect rename so duplicates won't match again
            files = [new_path if p == match else p for p in files]


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Переименовать видео из папки PullTube, добавив индекс из документа."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Только показать план переименований без изменений на диске",
    )
    parser.add_argument(
        "--links",
        type=str,
        default=None,
        help="Путь к файлу со ссылками (по умолчанию ищет в папке проекта)",
    )
    parser.add_argument(
        "--dir",
        type=str,
        default=None,
        help="Путь к папке PullTube (по умолчанию ~/Downloads/PullTube)",
    )
    parser.add_argument(
        "--project",
        type=str,
        default=None,
        help="Название проекта (если не указано, будет запрошено интерактивно)",
    )
    args = parser.parse_args()

    links_path = Path(args.links).expanduser() if args.links else None
    pulltube_dir = Path(args.dir).expanduser() if args.dir else None
    project_name = args.project

    process(dry_run=args.dry_run, links_path=links_path, pulltube_dir=pulltube_dir, project_name=project_name)


if __name__ == "__main__":
    main()


