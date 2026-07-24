#!/usr/bin/env python3
"""
Вставка фото в белые рамки шаблона плёнки (assets/New Design/Texturelabs_Film_139XL.jpg).

Часть общего пайплайна: запускается сразу после кропа 16:9 (2.1_smart_cropping.py),
берёт JPG из images_cropped и собирает копии шаблона плёнки, где каждая белая
рамка заменена на фото (cover-кроп по центру под пропорции рамки, с запасом под
рамку, чтобы скрыть кайму).

Группировка — по блоку сценария, а не по порядку в папке: имя файла
B<номер_строки>_<индекс>.jpg уже кодирует блок (строку таблицы сценария), это
и есть порядок сюжета. Фото из разных блоков никогда не смешиваются в одной
плёнке — иначе в одном кадре могут оказаться тематически не связанные фото.

На плёнку берётся 3 уникальных фото блока (A, B, C), в рамки они ставятся по
схеме 1-2-3-2-1: A, B, C, затем повтор B и A — но повторы (4-й и 5-й кадр)
делаются чёрно-белым негативом (ч/б + инверсия цвета), чтобы визуально
отличаться от оригиналов. Если в блоке фото меньше 3 — недостающие берутся
циклическим повтором того, что есть в блоке.

Если в блоке больше 3 фото — из него получится несколько плёнок подряд
(B<блок>_p1.jpg, B<блок>_p2.jpg, ...), все внутри одного блока, чужие фото
не подмешиваются.

На каждое фото дополнительно накладывается зернистая текстура
(Texturelabs_Grunge_265XL.jpg), сжатая под размер конкретного фото, через
режим наложения hard light с непрозрачностью 18%.

Скрипт идемпотентен: уже собранные плёнки (по имени файла) не пересоздаются,
повторный запуск на пополнившейся папке images_cropped дособерёт только новые.
"""

import argparse
import glob
import itertools
import os
import re
from collections import defaultdict

import numpy as np
from PIL import Image, ImageOps

from path_utils import get_base_dir as _get_base_dir, get_data_dir as _get_data_dir
import manifest

_BASE_DIR = _get_base_dir(__file__)
_DATA_DIR = _get_data_dir(__file__)
_TEMPLATE_PATH = _BASE_DIR / "assets" / "New Design" / "Texturelabs_Film_139XL.jpg"
_GRUNGE_TEXTURE_PATH = _BASE_DIR / "assets" / "New Design" / "Texturelabs_Grunge_265XL.jpg"
GRUNGE_OPACITY = 0.18

PHOTOS_PER_PAGE = 3  # уникальных фото на одну плёнку (A, B, C)

# Координаты 5 белых рамок в шаблоне (x0, y0, x1, y1), измерены по исходному
# файлу 14400x2914 (найдены поиском сплошных белых прямоугольников).
FRAME_BOXES = [
    (488, 404, 3065, 2110),
    (3192, 443, 5755, 2148),
    (5875, 482, 8425, 2186),
    (8543, 520, 11095, 2224),
    (11212, 558, 13778, 2262),
]

# Схема раскладки по 5 рамкам: индексы уникальных фото (A=0, B=1, C=2) + флаг
# негатива. 1-2-3-2-1: A, B, C, затем негатив B, негатив A.
FRAME_PATTERN = [(0, False), (1, False), (2, False), (1, True), (0, True)]

# Запас в пикселях, на который фото перекрывает рамку с каждой стороны,
# чтобы скрыть под чёрной рамкой шаблона тонкую белую кайму по краям кадра.
BLEED_PX = 40

_FILENAME_RE = re.compile(r"^B(\d+)_(\d+)$")


def parse_block_and_index(path: str):
    name = os.path.splitext(os.path.basename(path))[0]
    m = _FILENAME_RE.match(name)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def group_by_block(photos: list[str]) -> list[tuple[int, list[str]]]:
    """Группирует фото по номеру блока (строки сценария), сортирует блоки и
    фото внутри блока численно. Файлы, не подходящие под шаблон B<row>_<idx>,
    пропускаются (не могут быть привязаны к блоку сценария)."""
    blocks: dict[int, list[tuple[int, str]]] = defaultdict(list)
    skipped = 0
    for path in photos:
        parsed = parse_block_and_index(path)
        if not parsed:
            skipped += 1
            continue
        block_id, idx = parsed
        blocks[block_id].append((idx, path))
    if skipped:
        print(f"⚠ Пропущено файлов без блока (не подходят под B<row>_<idx>): {skipped}")
    ordered = []
    for block_id in sorted(blocks):
        paths = [p for _, p in sorted(blocks[block_id])]
        ordered.append((block_id, paths))
    return ordered


def build_pages(blocks: list[tuple[int, list[str]]]) -> list[tuple[int, int, list[str]]]:
    """Для каждого блока делит его фото на страницы по PHOTOS_PER_PAGE.
    Последняя неполная страница блока дополняется циклическим повтором фото
    того же блока — так плёнка никогда не берёт чужой блок."""
    pages = []
    for block_id, block_photos in blocks:
        chunks = [block_photos[i:i + PHOTOS_PER_PAGE] for i in range(0, len(block_photos), PHOTOS_PER_PAGE)]
        for page_idx, chunk in enumerate(chunks, start=1):
            if len(chunk) < PHOTOS_PER_PAGE:
                pool = itertools.cycle(block_photos)
                chunk = list(chunk)
                while len(chunk) < PHOTOS_PER_PAGE:
                    chunk.append(next(pool))
            pages.append((block_id, page_idx, chunk))
    return pages


def cover_crop(image: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """Масштабирует и обрезает по центру изображение под точные размеры рамки."""
    src_w, src_h = image.size
    target_ratio = target_w / target_h
    src_ratio = src_w / src_h

    if src_ratio > target_ratio:
        new_h = target_h
        new_w = round(new_h * src_ratio)
    else:
        new_w = target_w
        new_h = round(new_w / src_ratio)

    resized = image.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    return resized.crop((left, top, left + target_w, top + target_h))


def to_negative(image: Image.Image) -> Image.Image:
    """Ч/б негатив: обесцвечиваем и инвертируем, чтобы не было цветных пятен."""
    grayscale = image.convert("L").convert("RGB")
    return ImageOps.invert(grayscale)


def apply_grunge_texture(image: Image.Image, texture_path, opacity: float = GRUNGE_OPACITY) -> Image.Image:
    """Накладывает зернистую текстуру через hard light с заданной непрозрачностью.
    Текстура сжимается (без сохранения пропорций) точно под размер фото."""
    w, h = image.size
    with Image.open(texture_path) as texture:
        texture = texture.convert("RGB").resize((w, h), Image.LANCZOS)

    base = np.asarray(image, dtype=np.float32)
    blend = np.asarray(texture, dtype=np.float32)

    low = (2 * base * blend) / 255.0
    high = 255.0 - (2 * (255.0 - base) * (255.0 - blend)) / 255.0
    hardlight = np.where(blend <= 127.5, low, high)

    result = base * (1 - opacity) + hardlight * opacity
    return Image.fromarray(np.clip(result, 0, 255).astype(np.uint8))


def compose_page(template_path, page_photos, output_path, texture_path=None, all_negative=False):
    """page_photos — список из PHOTOS_PER_PAGE путей (A, B, C).

    all_negative=True — все 5 рамок ч/б-негативом (не только 4-й/5-й кадр по
    схеме 1-2-3-2-1). Используется для «соседних» плёнок (до/после) в
    photo_filmstrip_anim_table.py — сама подложка/рамка плёнки не трогается,
    инвертируются только фото внутри (см. to_negative)."""
    pattern = [(idx, True) for idx, _ in FRAME_PATTERN] if all_negative else FRAME_PATTERN
    template = Image.open(template_path).convert("RGB")
    for box, (photo_idx, negative) in zip(FRAME_BOXES, pattern):
        x0, y0, x1, y1 = box
        x0, y0, x1, y1 = x0 - BLEED_PX, y0 - BLEED_PX, x1 + BLEED_PX, y1 + BLEED_PX
        w, h = x1 - x0, y1 - y0
        with Image.open(page_photos[photo_idx]) as photo:
            photo = photo.convert("RGB")
            fitted = cover_crop(photo, w, h)
        if negative:
            fitted = to_negative(fitted)
        if texture_path:
            fitted = apply_grunge_texture(fitted, texture_path)
        template.paste(fitted, (x0, y0))
    template.save(output_path, quality=95)


def main() -> int:
    parser = argparse.ArgumentParser(description="Вставка фото в рамки плёнки, по блокам сценария (1-2-3-2-1)")
    parser.add_argument("--input", dest="input_dir", default=None,
                         help="Папка с кропнутыми JPG (по умолчанию data/<проект>/images_cropped[/<волна>])")
    parser.add_argument("--output", dest="output_dir", default=None,
                         help="Папка для результатов (по умолчанию data/<проект>/filmstrips[/<волна>])")
    parser.add_argument("--project", default=None, help="Название проекта (если не задан --input)")
    parser.add_argument("--template", default=str(_TEMPLATE_PATH), help="Путь к шаблону плёнки")
    parser.add_argument("--texture", default=str(_GRUNGE_TEXTURE_PATH), help="Путь к текстуре, накладываемой на фото")
    parser.add_argument("--no-texture", action="store_true", help="Не накладывать текстуру на фото")
    parser.add_argument("--pages", type=int, default=0,
                         help="Сколько новых плёнок собрать за этот запуск (0 = все недостающие)")
    args = parser.parse_args()

    if args.input_dir:
        input_dir = args.input_dir
        output_dir = args.output_dir or str(os.path.join(os.path.dirname(input_dir), "filmstrips"))
    else:
        project_name = args.project or os.getenv("PROJECT_NAME", "").strip()
        if not project_name:
            project_name = input("Введите название проекта: ").strip()
        upd_subdir = os.getenv("UPD_SUBDIR", "").strip()
        base_input = _DATA_DIR / project_name / "images_cropped"
        base_output = _DATA_DIR / project_name / "filmstrips"
        input_dir = str(base_input / upd_subdir) if upd_subdir else str(base_input)
        output_dir = args.output_dir or (str(base_output / upd_subdir) if upd_subdir else str(base_output))
        if upd_subdir:
            print(f"🌊 Волна правок: {upd_subdir}")

    if not os.path.isdir(input_dir):
        print(f"❌ Входная директория не найдена: {input_dir}")
        return 1
    if not os.path.isfile(args.template):
        print(f"❌ Шаблон плёнки не найден: {args.template}")
        return 1

    texture_path = None if args.no_texture else args.texture
    if texture_path and not os.path.isfile(texture_path):
        print(f"❌ Текстура не найдена: {texture_path}")
        return 1

    photos = sorted(glob.glob(os.path.join(input_dir, "*.jpg")) + glob.glob(os.path.join(input_dir, "*.jpeg")))
    if not photos:
        print(f"❌ JPG файлы не найдены в директории: {input_dir}")
        return 1

    os.makedirs(output_dir, exist_ok=True)

    blocks = group_by_block(photos)
    if not blocks:
        print("❌ Ни один файл не подходит под шаблон B<row>_<idx>.jpg — блок сценария не определить")
        return 1

    pages = build_pages(blocks)
    print(f"📥 Источник: {input_dir}")
    print(f"📁 Найдено фото: {len(photos)} -> {len(blocks)} блоков сценария -> {len(pages)} плёнок")

    # Устаревшие (фото в блоке заменили/добавили после сборки) пересобираем
    # заодно с недостающими — манифест хранит, какие именно фото вошли в плёнку.
    stale_removed = manifest.clear_stale(output_dir, "B*_p*.jpg")
    if stale_removed:
        print(f"♻️  Устарело (фото изменились) — пересоберу: {len(stale_removed)}")

    todo = [(block_id, page_idx, chunk) for block_id, page_idx, chunk in pages
            if not os.path.exists(os.path.join(output_dir, f"B{block_id}_p{page_idx}.jpg"))]
    done_count = len(pages) - len(todo)
    print(f"✓ Уже собрано плёнок: {done_count}")

    if not todo:
        print("✓ Все доступные плёнки уже собраны. Нечего делать.")
        return 0

    pages_to_run = todo if args.pages == 0 else todo[:args.pages]
    print(f"🎬 Собираю новых плёнок: {len(pages_to_run)}")

    for i, (block_id, page_idx, chunk) in enumerate(pages_to_run, start=1):
        output_path = os.path.join(output_dir, f"B{block_id}_p{page_idx}.jpg")
        compose_page(args.template, chunk, output_path, texture_path=texture_path)
        manifest.write_manifest(output_path, chunk)
        print(f"  [{i}/{len(pages_to_run)}] ✓ {os.path.basename(output_path)}  (блок {block_id})")
        for p in chunk:
            print(f"      - {os.path.basename(p)}")

    print(f"\n✅ Готово. Результаты в: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
