#!/usr/bin/env python3
"""Обзор материалов проекта одной HTML-страницей: строки сценария по
порядку, у каждой — её ссылки и что по ним уже лежит на диске (превью
картинок, видео, плашки, статьи, плёнки), а что не скачалось и почему.

Страница пишется в 00_Admin/review.html и ссылается на файлы проекта
относительными путями — открывается в любом браузере без сервера.
Пересобирается после каждого прогона и из меню проекта.

Ручной запуск: python3 project_review.py <путь к папке проекта>
"""

import csv
import html
import os
import re
import sys
import webbrowser
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from path_utils import project_subdir

CATEGORY_LABELS = {
    "image": "Картинка",
    "youtube": "YouTube",
    "motionarray": "MotionArray",
    "video": "Видео",
    "other": "Статья",
}

# Где искать результат по ссылке каждой категории (в порядке приоритета).
CATEGORY_DIRS = {
    "image": ["images_cropped", "images"],
    "youtube": ["renamed_videos"],
    "motionarray": ["renamed_videos", "video_motionarray"],
    "video": ["renamed_videos", "video_direct"],
    "other": ["articles"],
}

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
VIDEO_EXT = {".mp4", ".m4v", ".webm", ".mov", ".mkv"}
BROWSER_VIDEO_EXT = {".mp4", ".m4v", ".webm"}

_ADDRESS_RE = re.compile(r"^([A-Za-z]+)(\d+)_(\d+)$")


def _read_csv_rows(path: Path) -> list:
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))
    except (OSError, csv.Error):
        return []


def _latest_table(database_dir: Path):
    tables = sorted(database_dir.glob("input_gdoc*.csv"), key=lambda p: p.stat().st_mtime)
    if not tables:
        return []
    try:
        with open(tables[-1], "r", encoding="utf-8", newline="") as f:
            return list(csv.reader(f))
    except (OSError, csv.Error):
        return []


def _row_text(table: list, row_num: int) -> str:
    """Текст строки сценария: колонка «текст»/«text», иначе самая длинная
    ячейка без ссылок."""
    if not table or row_num < 1 or row_num > len(table):
        return ""
    header = [c.lower() for c in table[0]]
    row = table[row_num - 1]
    for i, name in enumerate(header):
        if ("текст" in name or "text" in name) and i < len(row) and row[i].strip():
            return row[i].strip()
    cells = [c.strip() for c in row if c.strip() and "http" not in c]
    return max(cells, key=len) if cells else ""


def _index_files(project_dir: Path, folder: str) -> list:
    root = project_subdir(project_dir, folder)
    if not root.is_dir():
        return []
    return [p for p in root.rglob("*") if p.is_file() and not p.name.startswith(".")]


def _files_for_address(files: list, address: str) -> list:
    """Файлы, имя которых начинается с адреса ячейки (B5_1.jpg, «B5_1 Название.mp4»),
    но не с более длинного адреса (B5_10)."""
    pattern = re.compile(rf"^{re.escape(address)}(?!\d)")
    return [p for p in files if pattern.match(p.name)]


def _load_errors(project_dir: Path) -> dict:
    by_name = defaultdict(list)
    errors_root = project_dir / "errors"
    for csv_path in sorted(errors_root.glob("stage_*/*.csv")):
        for row in _read_csv_rows(csv_path):
            name = (row.get("display_name") or "").strip()
            if name:
                by_name[name].append((row.get("reason") or "").strip() or csv_path.stem)
    return by_name


def collect(project_dir: Path, project_name: str) -> dict:
    database_dir = project_subdir(project_dir, "database")
    category_by_address = {}
    for category in CATEGORY_LABELS:
        for row in _read_csv_rows(database_dir / f"os_doc_{project_name}_{category}_links.csv"):
            address = (row.get("source_address") or "").strip()
            if address and not address.startswith("upd_"):
                category_by_address[address] = category

    links = []
    for row in _read_csv_rows(database_dir / f"os_doc_{project_name}_all_links.csv"):
        address = (row.get("source_address") or "").strip()
        url = (row.get("url") or "").strip()
        if address and url and not address.startswith("upd_"):
            links.append((address, url))

    files_by_folder = {}
    def files_in(folder):
        if folder not in files_by_folder:
            files_by_folder[folder] = _index_files(project_dir, folder)
        return files_by_folder[folder]

    errors = _load_errors(project_dir)
    author_files = files_in("author")
    filmstrip_files = files_in("filmstrips") + files_in("filmstrip_videos")
    table = _latest_table(database_dir)

    rows = defaultdict(list)
    for address, url in links:
        m = _ADDRESS_RE.match(address)
        row_num = int(m.group(2)) if m else 0
        category = category_by_address.get(address, "other")
        found = []
        for folder in CATEGORY_DIRS.get(category, []):
            found = _files_for_address(files_in(folder), address)
            if found:
                break
        rows[row_num].append({
            "address": address,
            "url": url,
            "category": category,
            "files": found,
            "author": _files_for_address(author_files, address),
            "errors": errors.get(address, []),
        })

    blocks = []
    for row_num in sorted(rows):
        block_files = [p for p in filmstrip_files if re.match(rf"^B{row_num}_p\d+", p.name)]
        blocks.append({
            "row": row_num,
            "text": _row_text(table, row_num),
            "items": sorted(rows[row_num], key=lambda it: it["address"]),
            "filmstrips": sorted(block_files),
        })
    return {"blocks": blocks}


def _rel(path: Path, out_dir: Path) -> str:
    """Относительная ссылка от папки страницы до файла проекта."""
    rel = os.path.relpath(path, out_dir)
    return "/".join(quote(part) for part in Path(rel).parts)


def _preview(path: Path, out_dir: Path) -> str:
    href = _rel(path, out_dir)
    ext = path.suffix.lower()
    if ext in IMAGE_EXT:
        return f'<a href="{href}" target="_blank"><img loading="lazy" src="{href}" alt=""></a>'
    if ext in BROWSER_VIDEO_EXT:
        return f'<video src="{href}#t=1" preload="metadata" controls muted></video>'
    return f'<a class="file" href="{href}" target="_blank">{html.escape(path.name)}</a>'


STYLE = """
:root { --bg:#f6f6f4; --card:#fff; --text:#1d1d1f; --muted:#6e6e73; --line:#e3e3e0;
  --ok:#1f8a4c; --bad:#c62f2f; --warn:#b26b00; --accent:#0b6bcb; }
@media (prefers-color-scheme: dark) { :root { --bg:#161617; --card:#1f1f21; --text:#ececee;
  --muted:#9a9aa0; --line:#2f2f33; --ok:#4cc27f; --bad:#ff6b6b; --warn:#f0a43a; --accent:#5aa9ff; } }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--text); font:14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
header { position:sticky; top:0; z-index:2; background:var(--bg); border-bottom:1px solid var(--line); padding:14px 20px; }
h1 { margin:0 0 6px; font-size:20px; }
.stats { display:flex; flex-wrap:wrap; gap:8px 18px; color:var(--muted); }
.stats b { color:var(--text); }
.stats .bad b { color:var(--bad); }
label.toggle { margin-left:auto; cursor:pointer; color:var(--text); }
main { padding:16px 20px 60px; max-width:1400px; }
.block { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:14px 16px; margin-bottom:14px; }
.block h2 { margin:0 0 4px; font-size:15px; }
.block .text { color:var(--muted); margin:0 0 10px; white-space:pre-wrap; }
.items { display:grid; grid-template-columns:repeat(auto-fill, minmax(min(230px, 100%), 1fr)); gap:10px; }
.item { border:1px solid var(--line); border-radius:8px; padding:8px; min-width:0; }
.item.missing { border-color:var(--bad); }
.item .head { display:flex; gap:6px; align-items:baseline; font-size:12px; }
.item .addr { font-weight:600; }
.item .cat { color:var(--muted); }
.item .state { margin-left:auto; font-weight:600; }
.ok { color:var(--ok); } .bad { color:var(--bad); } .warn { color:var(--warn); }
.item a.url { display:block; font-size:12px; color:var(--accent); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; margin:4px 0; }
.item img, .item video, .films img, .films video { width:100%; aspect-ratio:16/9; object-fit:cover; border-radius:6px; background:var(--line); display:block; }
.item .reason { font-size:12px; color:var(--bad); }
.item a.file { font-size:12px; color:var(--accent); word-break:break-all; }
.films { display:grid; grid-template-columns:repeat(auto-fill, minmax(min(230px, 100%), 1fr)); gap:10px; margin-top:10px; }
body.only-problems .block:not(.has-problems), body.only-problems .item:not(.missing) { display:none; }
@media (max-width:600px) { header, main { padding-left:16px; padding-right:16px; } }
"""


def render(project_name: str, data: dict, out_path: Path) -> str:
    out_dir = out_path.parent
    total = ready = missing = 0
    per_category = defaultdict(lambda: [0, 0])
    parts = []
    for block in data["blocks"]:
        items_html = []
        block_missing = False
        for item in block["items"]:
            total += 1
            per_category[item["category"]][0] += 1
            has_file = bool(item["files"])
            if has_file:
                ready += 1
                per_category[item["category"]][1] += 1
                state = '<span class="state ok">✓</span>'
                preview = _preview(item["files"][0], out_dir)
            else:
                missing += 1
                block_missing = True
                state = '<span class="state bad">нет</span>'
                preview = ""
            reasons = "".join(f'<div class="reason">{html.escape(r)}</div>' for r in item["errors"][:2])
            author = '<div class="cat">+ плашка источника</div>' if item["author"] else ""
            url = html.escape(item["url"], quote=True)
            items_html.append(
                f'<div class="item{"" if has_file else " missing"}">'
                f'<div class="head"><span class="addr">{html.escape(item["address"])}</span>'
                f'<span class="cat">{CATEGORY_LABELS.get(item["category"], item["category"])}</span>{state}</div>'
                f'<a class="url" href="{url}" target="_blank" title="{url}">{html.escape(item["url"])}</a>'
                f"{preview}{reasons}{author}</div>"
            )
        films = "".join(_preview(p, out_dir) for p in block["filmstrips"]
                        if p.suffix.lower() in IMAGE_EXT | BROWSER_VIDEO_EXT)
        title = f"Строка {block['row']}" if block["row"] else "Без строки"
        parts.append(
            f'<section class="block{" has-problems" if block_missing else ""}">'
            f"<h2>{title}</h2>"
            + (f'<p class="text">{html.escape(block["text"])}</p>' if block["text"] else "")
            + f'<div class="items">{"".join(items_html)}</div>'
            + (f'<div class="films">{films}</div>' if films else "")
            + "</section>"
        )

    cats = "".join(
        f"<span>{CATEGORY_LABELS.get(c, c)}: <b>{done}/{count}</b></span>"
        for c, (count, done) in sorted(per_category.items())
    )
    generated = datetime.now().strftime("%d.%m.%Y %H:%M")
    body = "".join(parts) or "<p>Ссылок пока нет — сначала распарсьте таблицу.</p>"
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Обзор: {html.escape(project_name)}</title>
<style>{STYLE}</style></head>
<body>
<header>
  <h1>{html.escape(project_name)}</h1>
  <div class="stats">
    <span>Готово: <b>{ready}/{total}</b></span>
    <span class="bad">Не хватает: <b>{missing}</b></span>
    {cats}
    <span>обновлено {generated}</span>
    <label class="toggle"><input type="checkbox" id="problems"> только проблемы</label>
  </div>
</header>
<main>{body}</main>
<script>
document.getElementById("problems").addEventListener("change", e =>
  document.body.classList.toggle("only-problems", e.target.checked));
</script>
</body></html>
"""


def build_review(project_dir, project_name: str = "") -> Path:
    project_dir = Path(project_dir)
    project_name = project_name or project_dir.name
    out_path = project_subdir(project_dir, "database").parent / "review.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render(project_name, collect(project_dir, project_name), out_path), encoding="utf-8")
    return out_path


def open_in_browser(path: Path) -> None:
    webbrowser.open(path.resolve().as_uri())


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Использование: python3 project_review.py <папка проекта>")
        sys.exit(1)
    result = build_review(Path(sys.argv[1]).expanduser())
    print(f"✓ {result}")
    open_in_browser(result)
