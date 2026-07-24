#!/usr/bin/env python3
"""Газеты · ноды — извлечение текста статей и финальный рендер по одной/всем.

Вызывается как job-команда из web/app.py (/api/gzn/*), печатает
"=== Шаг N/M: ... ===" строки, которые парсит _parse_job_line_locked
в web/app.py — так прогресс попадает в общий job-бар.

Состояние проекта: <project_dir>/gazety_nodes/state.json — разложенный граф
(Источник → Заголовок/Текст/Картинка → Рендер, см. web/templates/index.html):
{
  "queue": [{"url","status":"queued|done|error","error"}],
  "images": [{"id","filename","ext","w","h"}],
  "articles": [{
    "id","name","url","source","kicker","status","error","renderedPath","template",
    "headline","deck","headlineStyle":{"font","size","color"},
    "paragraphs":[...],"textStyle":{"font","size","color"},
    "image": null|{"imageId","scale","offsetX","offsetY","anchorIndex","side"},
    "settings":{"scale","x","y","animate"}
  }]
}
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

BASE_DIR = Path(os.environ.get("BASE_DIR") or Path(__file__).resolve().parent.parent)
PAPER = BASE_DIR / "paper_pipeline"
TEMPLATE_ORDER = ["2", "3", "4", "5"]


def _projects_root() -> Path:
    root = os.environ.get("PROJECTS_ROOT")
    return Path(root).expanduser().resolve() if root else BASE_DIR / "data"


def _project_dir(project: str) -> Path:
    return _projects_root() / project


def _state_path(project: str) -> Path:
    return _project_dir(project) / "gazety_nodes" / "state.json"


def _load_state(project: str) -> dict:
    p = _state_path(project)
    if not p.exists():
        return {"queue": [], "articles": [], "images": []}
    try:
        state = json.loads(p.read_text("utf-8"))
    except (OSError, ValueError):
        return {"queue": [], "articles": [], "images": []}
    state.setdefault("images", [])
    return state


def _save_state(project: str, state: dict) -> None:
    p = _state_path(project)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, ensure_ascii=False, indent=2), "utf-8")


def _slugify(text: str, maxlen: int = 40) -> str:
    s = re.sub(r"[^a-z0-9а-яё]+", "-", (text or "").lower(), flags=re.IGNORECASE)
    return s.strip("-")[:maxlen] or "article"


def _short_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]


def _article_slug(project: str, url: str) -> str:
    return f"gzn-{_slugify(project, 20)}-{_short_hash(url)}"


_LEAD_IMAGE_CTYPES = {"image/jpeg": ".jpg", "image/jpg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
_LEAD_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def _import_lead_image(project: str, state: dict, url: str) -> str | None:
    """Скачивает лид-картинку статьи (og:image из shot.mjs) в gazety_nodes/images
    и регистрирует её в state["images"]. Сама картинка подключается к статье
    выключенной — включает пользователь в ноде «Картинка»."""
    if not url:
        return None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            data = resp.read(12 * 1024 * 1024)
    except Exception as exc:  # сеть/404/таймаут — не повод валить извлечение статьи
        print(f"⚠ картинку статьи скачать не удалось: {exc}")
        return None
    ext = _LEAD_IMAGE_CTYPES.get(ctype) or os.path.splitext(urllib.parse.urlparse(url).path)[1].lower()
    if ext not in _LEAD_IMAGE_EXTS or len(data) < 1024:
        return None
    if ext == ".jpeg":
        ext = ".jpg"
    image_id = "gzn-img-" + hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]
    images_dir = _project_dir(project) / "gazety_nodes" / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    path = images_dir / f"{image_id}{ext}"
    path.write_bytes(data)
    # отсекаем иконки/спейсеры по реальным размерам, а не по весу файла:
    # однотонная, но вполне пригодная картинка может весить пару килобайт
    w = h = 0
    try:
        from PIL import Image
        with Image.open(path) as im:
            w, h = im.size
        if w < 400 or h < 250:
            path.unlink(missing_ok=True)
            return None
    except Exception:
        pass
    images = state.setdefault("images", [])
    if not any(i.get("id") == image_id for i in images):
        images.append({
            "id": image_id, "ext": ext, "w": w, "h": h,
            "filename": os.path.basename(urllib.parse.urlparse(url).path) or f"lead{ext}",
        })
    print(f"  картинка импортирована (выключена): {image_id}{ext}")
    return image_id


def cmd_extract(project: str) -> int:
    state = _load_state(project)
    queue = state.setdefault("queue", [])
    articles = state.setdefault("articles", [])
    pending = [item for item in queue if item.get("status") != "done"]
    if not pending:
        print("Нет новых ссылок для обработки")
        return 0

    n = len(pending)
    ok = fail = 0
    for i, item in enumerate(pending, start=1):
        url = item["url"]
        print(f"\n=== Шаг {i}/{n}: {url} ===")
        slug = _article_slug(project, url)
        render_dir = PAPER / "renders" / slug
        try:
            subprocess.run(
                ["node", str(PAPER / "shot.mjs"), "--url", url, "--slug", slug],
                check=True, cwd=str(PAPER),
            )
        except subprocess.CalledProcessError as exc:
            print(f"✗ ошибка извлечения статьи: {exc}")
            item["status"] = "error"
            item["error"] = "не удалось извлечь статью"
            fail += 1
            _save_state(project, state)
            continue

        content_path = render_dir / "source" / "content.json"
        try:
            content = json.loads(content_path.read_text("utf-8"))
        except (OSError, ValueError):
            print("✗ не удалось прочитать content.json")
            item["status"] = "error"
            item["error"] = "не удалось прочитать content.json"
            fail += 1
            _save_state(project, state)
            continue

        headline = content.get("headline") or slug
        template = TEMPLATE_ORDER[len(articles) % len(TEMPLATE_ORDER)]
        lead_image_id = _import_lead_image(project, state, content.get("imageUrl") or "")
        article = {
            "id": slug,
            "name": headline[:40],
            "url": url,
            "source": content.get("source") or "",
            "kicker": content.get("kicker") or "",
            "headline": headline,
            "headlineStyle": {"font": "SFProText-Heavy", "size": 1.0, "color": "#FC3026"},
            "deck": content.get("deck") or "",
            "paragraphs": content.get("paragraphs") or [],
            "textStyle": {"font": "SFProText-Light", "size": 1.0, "color": "#221e18"},
            # картинка из статьи импортируется всегда, но по умолчанию выключена
            "image": ({"imageId": lead_image_id, "scale": 0.45, "offsetX": 0, "offsetY": 0,
                       "anchorIndex": 0, "side": "left", "enabled": False} if lead_image_id else None),
            "template": template,
            "settings": {"scale": 1.0, "x": 0, "y": 0, "animate": True},
            "status": "previewed",
            "error": None,
            "renderedPath": None,
        }
        articles.append(article)
        item["status"] = "done"
        item["error"] = None
        ok += 1
        print(f"✓ превью готово: {headline}")
        _precompose(project, state, article)
        _save_state(project, state)

    print(f"\n=== Готово: {ok} ок, {fail} ошибок ===")
    return 0 if fail < n else 1


def _resolve_image_path(project: str, state: dict, image_id: str) -> str:
    img = next((i for i in state.get("images", []) if i.get("id") == image_id), None)
    if not img:
        return ""
    p = _project_dir(project) / "gazety_nodes" / "images" / f"{image_id}{img.get('ext', '')}"
    return str(p) if p.exists() else ""


def _compose_style_args(project: str, article: dict, state: dict) -> list:
    """Флаги для нод "Заголовок"/"Текст" (+ подключённых к ним нод "Настройки")
    и опциональной ноды "Картинка" — общие для превью (_precompose) и рендера."""
    hstyle = article.get("headlineStyle") or {}
    tstyle = article.get("textStyle") or {}
    args = [
        "--headline-color", str(hstyle.get("color") or "#FC3026"),
        "--headline-font", str(hstyle.get("font") or "SFProText-Heavy"),
        "--headline-size", str(hstyle.get("size", 1.0)),
        "--text-font", str(tstyle.get("font") or "SFProText-Light"),
        "--text-size", str(tstyle.get("size", 1.0)),
        "--text-color", str(tstyle.get("color") or "#221e18"),
    ]
    image = article.get("image")
    if image and image.get("imageId") and image.get("enabled"):
        path = _resolve_image_path(project, state, image["imageId"])
        if path:
            args += [
                "--image", path,
                "--image-scale", str(image.get("scale", 0.45)),
                "--image-offset-x", str(image.get("offsetX", 0)),
                "--image-offset-y", str(image.get("offsetY", 0)),
                "--image-anchor", str(image.get("anchorIndex", 0)),
                "--image-side", str(image.get("side") or "left"),
            ]
    return args


def _precompose(project: str, state: dict, article: dict) -> None:
    """Готовит "бумагу" (animation.json + images) сразу после извлечения текста,
    чтобы живое превью в браузере показывало реальную вырезанную/застывшую
    торн-бумагу, а не сырой (анимированный, не на всю рамку) шаблон.
    Не запускает hyperframes/ffmpeg — это дешёвая часть compose.mjs (без рендера видео).
    """
    slug = article["id"]
    render_dir = PAPER / "renders" / slug
    src_dir = render_dir / "source"
    src_dir.mkdir(parents=True, exist_ok=True)
    content = {
        "source": article.get("source") or "",
        "kicker": article.get("kicker") or "",
        "headline": article.get("headline") or article.get("name") or slug,
        "deck": article.get("deck") or "",
        "paragraphs": article.get("paragraphs") or [],
    }
    (src_dir / "content.json").write_text(json.dumps(content, ensure_ascii=False), "utf-8")
    try:
        subprocess.run(
            ["node", str(PAPER / "compose.mjs"), "--slug", slug,
             "--template", str(article.get("template") or "2"),
             *_compose_style_args(project, article, state)],
            check=True, cwd=str(PAPER), capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        print(f"⚠ не удалось подготовить фон для превью: {exc}")


def _render_one(project: str, state: dict, article: dict, out_dir: Path) -> None:
    slug = article["id"]
    render_dir = PAPER / "renders" / slug
    src_dir = render_dir / "source"
    src_dir.mkdir(parents=True, exist_ok=True)
    content = {
        "source": article.get("source") or "",
        "kicker": article.get("kicker") or "",
        "headline": article.get("headline") or article.get("name") or slug,
        "deck": article.get("deck") or "",
        "paragraphs": article.get("paragraphs") or [],
    }
    (src_dir / "content.json").write_text(json.dumps(content, ensure_ascii=False), "utf-8")

    settings = article.get("settings") or {}
    print("  сборка HTML/CSS + Lottie-фон…")
    subprocess.run(
        ["node", str(PAPER / "compose.mjs"),
         "--slug", slug,
         "--template", str(article.get("template") or "2"),
         "--scale", str(settings.get("scale", 1.0)),
         "--x", str(settings.get("x", 0)),
         "--y", str(settings.get("y", 0)),
         "--animate", "true" if settings.get("animate", True) else "false",
         *_compose_style_args(project, article, state)],
        check=True, cwd=str(PAPER),
    )

    prores_path = render_dir / f"_render-{slug}.mov"
    print("  рендер кадров (hyperframes)…")
    subprocess.run(
        ["npx", "--yes", "hyperframes", "render", str(render_dir),
         "--format", "mov", "--fps", "25", "-o", str(prores_path)],
        check=True, cwd=str(PAPER),
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    final_name = f"gazeta_article_{_slugify(article.get('headline') or slug)}_{int(time.time() * 1000)}.mov"
    final_path = out_dir / final_name
    print("  транскод в QuickTime Animation (alpha)…")
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(prores_path), "-c:v", "qtrle", "-pix_fmt", "argb", str(final_path)],
        check=True,
    )
    prores_path.unlink(missing_ok=True)
    article["renderedPath"] = str(final_path.relative_to(_project_dir(project)))
    article["status"] = "rendered"
    article["error"] = None


def cmd_render(project: str, article_id: str) -> int:
    state = _load_state(project)
    articles = state.setdefault("articles", [])
    article = next((a for a in articles if a.get("id") == article_id), None)
    if not article:
        print(f"✗ статья не найдена: {article_id}")
        return 1
    out_dir = _project_dir(project) / "placeholders_screenshots"
    print(f"\n=== Шаг 1/1: {article.get('name') or article_id} ===")
    try:
        _render_one(project, state, article, out_dir)
    except subprocess.CalledProcessError as exc:
        print(f"✗ ошибка рендера: {exc}")
        article["status"] = "error"
        article["error"] = "ошибка рендера"
        _save_state(project, state)
        return 1
    _save_state(project, state)
    print(f"✓ готово -> {article['renderedPath']}")
    return 0


def cmd_precompose(project: str, article_id: str) -> int:
    """Пересобирает только "бумагу" (animation.json) для одной статьи — нужно при
    смене шаблона нодой "Шаблон", иначе в превью меняется текст, а подложка
    остаётся от старого шаблона. Быстро: без hyperframes/ffmpeg."""
    state = _load_state(project)
    article = next((a for a in state.get("articles", []) if a.get("id") == article_id), None)
    if not article:
        print(f"✗ статья не найдена: {article_id}")
        return 1
    _precompose(project, state, article)
    print(f"✓ подложка пересобрана (шаблон {article.get('template')})")
    return 0


def cmd_render_all(project: str) -> int:
    state = _load_state(project)
    articles = state.setdefault("articles", [])
    if not articles:
        print("Нет статей для рендера")
        return 0
    out_dir = _project_dir(project) / "placeholders_screenshots"
    n = len(articles)
    ok = fail = 0
    for i, article in enumerate(articles, start=1):
        print(f"\n=== Шаг {i}/{n}: {article.get('name') or article.get('id')} ===")
        try:
            _render_one(project, state, article, out_dir)
            ok += 1
        except subprocess.CalledProcessError as exc:
            print(f"✗ ошибка рендера: {exc}")
            article["status"] = "error"
            article["error"] = "ошибка рендера"
            fail += 1
        _save_state(project, state)
    print(f"\n=== Готово: {ok} ок, {fail} ошибок ===")
    return 0 if fail == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True, choices=["extract", "render", "render_all", "precompose"])
    parser.add_argument("--project", required=True)
    parser.add_argument("--id", default="")
    args = parser.parse_args()

    if args.mode == "extract":
        return cmd_extract(args.project)
    if args.mode == "render":
        if not args.id:
            print("--id required for --mode render")
            return 1
        return cmd_render(args.project, args.id)
    if args.mode == "precompose":
        if not args.id:
            print("--id required for --mode precompose")
            return 1
        return cmd_precompose(args.project, args.id)
    return cmd_render_all(args.project)


if __name__ == "__main__":
    sys.exit(main())
