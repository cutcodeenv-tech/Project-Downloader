#!/usr/bin/env python3
"""Кроп картинок проекта в 16:9 (1920x1080) на Pillow.

Берёт images/ (или --input), кладёт результат в images_cropped/ (или
--output) под тем же именем с расширением .jpg. Уже обработанные картинки
пропускаются — повторный запуск достраивает только новые.

Рамка 16:9 центрируется по горизонтали, а по вертикали чуть смещена вверх
(центр рамки на 40% высоты): на вертикальных фото люди и заголовки обычно
в верхней части кадра.
"""

import argparse
import os
from pathlib import Path

from PIL import Image, ImageOps

from error_log import log_download_error
from path_utils import get_data_dir, project_subdir
from progress_ui import StatusBoard, render_bar

TARGET_SIZE = (1920, 1080)
TARGET_RATIO = TARGET_SIZE[0] / TARGET_SIZE[1]
VERTICAL_ANCHOR = 0.4
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp"}


def crop_box(width: int, height: int) -> tuple[int, int, int, int]:
    """Рамка максимального размера с соотношением 16:9 внутри width x height."""
    if width / height > TARGET_RATIO:
        crop_w, crop_h = round(height * TARGET_RATIO), height
    else:
        crop_w, crop_h = width, round(width / TARGET_RATIO)
    left = (width - crop_w) // 2
    top = round(height * VERTICAL_ANCHOR - crop_h / 2)
    top = min(max(top, 0), height - crop_h)
    return left, top, left + crop_w, top + crop_h


def smart_crop_image(input_path, output_path) -> bool:
    """Кропает одну картинку в 16:9 и сохраняет JPEG 1920x1080."""
    try:
        with Image.open(input_path) as img:
            img = ImageOps.exif_transpose(img).convert("RGB")
            cropped = img.crop(crop_box(*img.size)).resize(TARGET_SIZE, Image.LANCZOS)
            cropped.save(output_path, "JPEG", quality=95)
        return True
    except Exception as e:
        print(f"  ❌ {Path(input_path).name}: {e}")
        return False


def process_images(pictures_dir: Path, output_dir: Path) -> tuple[int, int, int]:
    """Возвращает (обработано, пропущено, ошибок)."""
    output_dir.mkdir(parents=True, exist_ok=True)
    images = sorted(
        p for p in pictures_dir.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
    )
    if not images:
        print("❌ В папке нет изображений")
        return 0, 0, 0

    done = {p.stem for p in output_dir.glob("*.jpg")}
    todo = [p for p in images if p.stem not in done]
    skipped = len(images) - len(todo)
    print(f"📁 Изображений: {len(images)}, уже готово: {skipped}, к обработке: {len(todo)}")
    if not todo:
        return 0, skipped, 0

    project_name = os.getenv("PROJECT_NAME", "").strip()
    successful = errors = 0
    board = StatusBoard(2)
    for i, src in enumerate(todo, 1):
        overall = (i - 1) / len(todo)
        board.render([
            f"[{i}/{len(todo)}] {src.name}",
            f"Всего:  [{render_bar(overall)}] {overall * 100:5.1f}%  (готово: {successful}, ошибок: {errors})",
        ])
        if smart_crop_image(src, output_dir / f"{src.stem}.jpg"):
            successful += 1
        else:
            errors += 1
            board.log(f"  ❌ {src.name}")
            if project_name:
                log_download_error(project_name, "smart_cropping", src.stem, str(src), reason="ошибка кропа")
    board.render([
        "готово",
        f"Всего:  [{render_bar(1.0)}] 100.0%  (готово: {successful}, ошибок: {errors})",
    ])
    board.close()
    return successful, skipped, errors


def main():
    parser = argparse.ArgumentParser(description="Кроп картинок 16:9")
    parser.add_argument("--input", dest="input_dir", default=None,
                        help="Папка с исходными изображениями (вместо структуры проекта)")
    parser.add_argument("--output", dest="output_dir", default=None,
                        help="Папка для результата (по умолчанию <input>/../images_cropped)")
    args, _ = parser.parse_known_args()

    if args.input_dir:
        pictures_dir = Path(args.input_dir).expanduser()
        output_dir = Path(args.output_dir).expanduser() if args.output_dir else pictures_dir.parent / "images_cropped"
    else:
        project_name = os.getenv("PROJECT_NAME", "").strip()
        while not project_name:
            project_name = input("Введите название проекта: ").strip()
        project_dir = get_data_dir(__file__) / project_name
        upd_subdir = os.getenv("UPD_SUBDIR", "").strip()
        pictures_dir = project_subdir(project_dir, "images")
        output_dir = project_subdir(project_dir, "images_cropped")
        if upd_subdir:
            pictures_dir, output_dir = pictures_dir / upd_subdir, output_dir / upd_subdir
            print(f"🌊 Волна правок: {upd_subdir}")

    print(f"📥 {pictures_dir}\n📤 {output_dir}")
    if not pictures_dir.exists():
        print(f"❌ Папка не найдена: {pictures_dir}")
        return

    successful, skipped, errors = process_images(pictures_dir, output_dir)
    print(f"\n✅ Обработано: {successful}   ⏭️  Пропущено: {skipped}   ❌ Ошибок: {errors}")


if __name__ == "__main__":
    main()
