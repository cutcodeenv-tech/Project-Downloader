#!/usr/bin/env python3
"""
Экспериментальная версия photo_filmstrip_anim.py: на подложке сразу три
плёнки одного масштаба — предыдущий блок и следующий (оба целиком в
негативе фото, рамка нетронута, слегка повёрнуты в разные стороны) вокруг
центральной (текущий блок, герой, без поворота). Камера широким планом
показывает весь «стол», затем толкается в 1-й кадр центральной плёнки и
дальше работает как в photo_filmstrip_anim.py (пуш-ин/степпинг/пан/блюр/
аберрация/виньетка, фон — независимое видео).

prev/curr/next подхватываются автоматически: скрипт проходит все фото
проекта (images_cropped) той же логикой, что и photo_filmstrip.py (блоки
сценария -> страницы по 3 фото), и для нужной страницы берёт соседние по
порядку страницы как «до» и «после». «curr» — уже собранная плёнка из
пайплайна (data/<проект>/filmstrips), если её ещё нет — дособерёт сама.
«prev»/«next» рендерятся целиком в негатив (по фото, рамка нетронута) во
временные файлы и кэшируются на время запуска (одна и та же страница часто
нужна дважды — как «next» одному видео и «prev» соседнему).

Пока не встроено в общий пайплайн — отдельный шаг, дальше подключим по
образцу photo_filmstrip в core/main.py / web/app.py.
"""

import argparse
import glob
import os
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from photo_filmstrip_anim import (
    OUTPUT_W, OUTPUT_H, OUTPUT_ASPECT, CANVAS_SCALE, STRIP_WIDTH_FRACTION,
    INTRO_S, HOLD_S, PAN_S, FPS, FRAME_PADDING,
    SHAKE_POS_AMP, SHAKE_ZOOM_AMP, STOPMOTION_STEP,
    ease_in_out, build_timeline, apply_shake, stepped_time,
    build_radial_mask, apply_zoom_blur, apply_chromatic_aberration, BgVideoReader,
    _DEFAULT_BG_VIDEO, _BG_START_FRAME,
)
from photo_filmstrip import (
    FRAME_BOXES, group_by_block, build_pages, compose_page,
    _TEMPLATE_PATH, _GRUNGE_TEXTURE_PATH,
)
from path_utils import get_base_dir as _get_base_dir, get_data_dir as _get_data_dir

_BASE_DIR = _get_base_dir(__file__)
_DATA_DIR = _get_data_dir(__file__)

WIDE_ZOOM_FACTOR = 3.6  # шире, чем в одиночной версии — чтобы весь «стол» успевал показаться
VIGNETTE_STRENGTH = 0.10

# Смещение центров соседних плёнок относительно центральной, в долях ширины/
# высоты САМОЙ плёнки (все три одного масштаба, поэтому доли общие).
SIDE_OFFSET_Y_FRAC = 0.98
SIDE_OFFSET_X_FRAC = 0.22

PREV_ANGLE_DEG = -4
NEXT_ANGLE_DEG = 5


def build_middle_geometry(strip_path: str):
    """Геометрия и цели камеры — как в одиночной версии (build_strip_geometry),
    без поворота, это герой сцены."""
    strip = Image.open(strip_path).convert("RGB")
    canvas_w, canvas_h = OUTPUT_W * CANVAS_SCALE, OUTPUT_H * CANVAS_SCALE

    target_w = round(canvas_w * STRIP_WIDTH_FRACTION)
    scale = target_w / strip.width
    target_h = round(strip.height * scale)

    offset_x = (canvas_w - target_w) // 2
    offset_y = (canvas_h - target_h) // 2
    box_canvas = (offset_x, offset_y, offset_x + target_w, offset_y + target_h)

    def to_canvas(point):
        x, y = point
        return offset_x + x * scale, offset_y + y * scale

    frame_centers, frame_sizes = [], []
    for box in FRAME_BOXES:
        x0, y0, x1, y1 = box
        cx, cy = to_canvas(((x0 + x1) / 2, (y0 + y1) / 2))
        frame_centers.append((cx, cy))
        frame_sizes.append(((x1 - x0) * scale, (y1 - y0) * scale))

    layer = {"strip": strip, "scale": scale, "box_canvas": box_canvas}
    return layer, (canvas_w, canvas_h), frame_centers, frame_sizes


def build_side_layer(strip_path: str, angle_deg: float, scale: float, canvas_size, center_x, center_y):
    """Слой соседней (негативной по фото) плёнки, повёрнутой на angle_deg —
    того же масштаба (px канвы на px исходника), что и центральная.
    Поворот делается с настоящей прозрачностью (RGBA), а не заливкой цветом —
    иначе прямоугольный «хвост» повёрнутого кадра лезет поверх фона сплошным
    светлым пятном вместо честной диагональной обрезки."""
    strip = Image.open(strip_path).convert("RGBA")
    strip = strip.rotate(angle_deg, expand=True, resample=Image.BICUBIC, fillcolor=(0, 0, 0, 0))
    w = strip.width * scale
    h = strip.height * scale
    box_canvas = (center_x - w / 2, center_y - h / 2, center_x + w / 2, center_y + h / 2)
    return {"strip": strip, "scale": scale, "box_canvas": box_canvas}


def camera_state(t, segments, frame_centers, frame_sizes):
    t0, t1, kind, i0, i1 = segments[-1]
    local = 1.0
    for seg in segments:
        if t <= seg[1]:
            t0, t1, kind, i0, i1 = seg
            local = (t - t0) / max(t1 - t0, 1e-6)
            break

    target_w, target_h = frame_sizes[i1]
    target_w *= FRAME_PADDING
    target_h *= FRAME_PADDING
    if target_w / target_h > OUTPUT_ASPECT:
        target_h = target_w / OUTPUT_ASPECT
    else:
        target_w = target_h * OUTPUT_ASPECT

    if kind == "intro":
        e = ease_in_out(local)
        win_w = target_w * WIDE_ZOOM_FACTOR + (target_w - target_w * WIDE_ZOOM_FACTOR) * e
        win_h = win_w / OUTPUT_ASPECT
        cx, cy = frame_centers[0]
    elif kind == "hold":
        win_w, win_h = target_w, target_h
        cx, cy = frame_centers[i1]
    else:  # pan
        e = ease_in_out(local)
        cx0, cy0 = frame_centers[i0]
        cx1, cy1 = frame_centers[i1]
        cx = cx0 + (cx1 - cx0) * e
        cy = cy0 + (cy1 - cy0) * e
        win_w, win_h = target_w, target_h

    return cx, cy, win_w, win_h


def paste_layer(frame: Image.Image, layer, left, top, right, bottom, scale_out):
    bx0, by0, bx1, by1 = layer["box_canvas"]
    ix0, iy0 = max(left, bx0), max(top, by0)
    ix1, iy1 = min(right, bx1), min(bottom, by1)
    if ix1 <= ix0 or iy1 <= iy0:
        return
    scale = layer["scale"]
    strip = layer["strip"]
    src_box = ((ix0 - bx0) / scale, (iy0 - by0) / scale, (ix1 - bx0) / scale, (iy1 - by0) / scale)
    src_box = (max(0, src_box[0]), max(0, src_box[1]), min(strip.width, src_box[2]), min(strip.height, src_box[3]))
    out_w = round((ix1 - ix0) * scale_out)
    out_h = round((iy1 - iy0) * scale_out)
    if out_w <= 0 or out_h <= 0:
        return
    crop = strip.resize((out_w, out_h), Image.LANCZOS, box=src_box)
    pos = (round((ix0 - left) * scale_out), round((iy0 - top) * scale_out))
    if crop.mode == "RGBA":
        frame.paste(crop, pos, crop)  # альфа-маска — не тянем прозрачные уголки поворота
    else:
        frame.paste(crop, pos)


def compose_frame(layers, canvas_size, bg_frame, cx, cy, win_w, win_h):
    canvas_w, canvas_h = canvas_size
    win_w = min(win_w, canvas_w)
    win_h = min(win_h, canvas_h)
    left, top = cx - win_w / 2, cy - win_h / 2
    right, bottom = left + win_w, top + win_h
    scale_out = OUTPUT_W / win_w

    frame = bg_frame.copy()
    for layer in layers:  # порядок — задом наперёд (сначала дальние слои, герой последним)
        paste_layer(frame, layer, left, top, right, bottom, scale_out)
    return frame


def render_table_video(curr_path, prev_path, next_path, output_path, bg_video, bg_start_frame):
    """prev_path/next_path могут быть None (первая/последняя страница пайплайна —
    соседа с этой стороны просто нет, слой не добавляется)."""
    middle_layer, canvas_size, frame_centers, frame_sizes = build_middle_geometry(curr_path)
    scale = middle_layer["scale"]
    mx0, my0, mx1, my1 = middle_layer["box_canvas"]
    mw, mh = mx1 - mx0, my1 - my0
    mcx, mcy = (mx0 + mx1) / 2, (my0 + my1) / 2

    layers = []
    if next_path:
        layers.append(build_side_layer(next_path, NEXT_ANGLE_DEG, scale, canvas_size,
                                        mcx + mw * SIDE_OFFSET_X_FRAC, mcy + mh * SIDE_OFFSET_Y_FRAC))
    if prev_path:
        layers.append(build_side_layer(prev_path, PREV_ANGLE_DEG, scale, canvas_size,
                                        mcx - mw * SIDE_OFFSET_X_FRAC, mcy - mh * SIDE_OFFSET_Y_FRAC))
    layers.append(middle_layer)  # герой поверх всех

    segments, total_s = build_timeline()
    total_frames = round(total_s * FPS)

    vignette_factor = 1 - VIGNETTE_STRENGTH * build_radial_mask(OUTPUT_W, OUTPUT_H, 2.6)
    edge_mask = build_radial_mask(OUTPUT_W, OUTPUT_H, 1.6)
    bg_reader = BgVideoReader(bg_video, bg_start_frame)

    cmd = [
        "ffmpeg", "-y", "-nostdin",
        "-f", "rawvideo", "-pixel_format", "rgb24",
        "-video_size", f"{OUTPUT_W}x{OUTPUT_H}", "-framerate", str(FPS),
        "-i", "-",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "16", "-preset", "slow",
        str(output_path),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    try:
        for frame_idx in range(total_frames):
            t_pose = stepped_time(frame_idx)
            cx, cy, win_w, win_h = camera_state(t_pose, segments, frame_centers, frame_sizes)
            cx, cy, win_w, win_h = apply_shake(t_pose, cx, cy, win_w, win_h)

            bg_frame = bg_reader.next_frame()
            frame = compose_frame(layers, canvas_size, bg_frame, cx, cy, win_w, win_h)
            frame = apply_zoom_blur(frame, edge_mask)

            arr = apply_chromatic_aberration(frame, edge_mask)
            arr = arr * vignette_factor[:, :, None]
            arr = np.clip(arr, 0, 255).astype(np.uint8)

            proc.stdin.write(arr.tobytes())
            if frame_idx % 25 == 0:
                print(f"  кадр {frame_idx}/{total_frames}")
    finally:
        bg_reader.close()
        proc.stdin.close()
        proc.wait()

    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg завершился с ошибкой: {proc.returncode}")
    print(f"✅ Готово: {output_path} ({total_frames} кадров, {total_s:.2f}с)")


class NegativeCache:
    """Рендерит all_negative-вариант страницы во временный файл и переиспользует
    его — одна и та же страница обычно нужна дважды: как «next» одному видео
    и как «prev» соседнему."""

    def __init__(self, template_path, texture_path, tmp_dir):
        self.template_path = template_path
        self.texture_path = texture_path
        self.tmp_dir = tmp_dir
        self._cache = {}

    def get(self, block_id, page_idx, photos):
        key = (block_id, page_idx)
        if key not in self._cache:
            out_path = os.path.join(self.tmp_dir, f"B{block_id}_p{page_idx}_allneg.jpg")
            compose_page(self.template_path, photos, out_path, self.texture_path, all_negative=True)
            self._cache[key] = out_path
        return self._cache[key]


def resolve_pages(project_name: str):
    """Тот же обход, что и в photo_filmstrip.py: images_cropped -> блоки ->
    страницы по 3 фото, в порядке сценария. Возвращает [(block_id, page_idx,
    photos), ...] и путь к filmstrips/, где лежат (или дособираются) готовые
    плёнки-герои."""
    upd_subdir = os.getenv("UPD_SUBDIR", "").strip()
    base_input = _DATA_DIR / project_name / "images_cropped"
    base_output = _DATA_DIR / project_name / "filmstrips"
    input_dir = base_input / upd_subdir if upd_subdir else base_input
    filmstrips_dir = base_output / upd_subdir if upd_subdir else base_output

    photos = sorted(glob.glob(os.path.join(str(input_dir), "*.jpg")) + glob.glob(os.path.join(str(input_dir), "*.jpeg")))
    if not photos:
        raise RuntimeError(f"JPG файлы не найдены в директории: {input_dir}")
    blocks = group_by_block(photos)
    if not blocks:
        raise RuntimeError(f"Ни один файл не подходит под шаблон B<row>_<idx>.jpg в {input_dir}")
    pages = build_pages(blocks)
    return pages, filmstrips_dir


def ensure_curr_rendered(filmstrips_dir, block_id, page_idx, photos, template_path, texture_path):
    path = os.path.join(str(filmstrips_dir), f"B{block_id}_p{page_idx}.jpg")
    if not os.path.exists(path):
        os.makedirs(str(filmstrips_dir), exist_ok=True)
        compose_page(template_path, photos, path, texture_path)
        print(f"  (плёнка B{block_id}_p{page_idx} ещё не была собрана — дособрал)")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Анимация «стола» с тремя плёнками — prev/curr/next автоматически")
    parser.add_argument("--project", default=None, help="Название проекта (по умолчанию $PROJECT_NAME)")
    parser.add_argument("--block", type=int, default=None, help="Собрать только для этого блока (нужен --page)")
    parser.add_argument("--page", type=int, default=None, help="Номер страницы внутри блока (с --block)")
    parser.add_argument("--output-dir", default=None, help="Куда класть видео (по умолчанию data/<проект>/filmstrip_videos)")
    parser.add_argument("--template", default=str(_TEMPLATE_PATH))
    parser.add_argument("--texture", default=str(_GRUNGE_TEXTURE_PATH))
    parser.add_argument("--bg-video", default=str(_DEFAULT_BG_VIDEO))
    parser.add_argument("--bg-start-frame", type=int, default=_BG_START_FRAME)
    args = parser.parse_args()

    project_name = args.project or os.getenv("PROJECT_NAME", "").strip()
    if not project_name:
        project_name = input("Введите название проекта: ").strip()

    pages, filmstrips_dir = resolve_pages(project_name)
    output_dir = args.output_dir or str(_DATA_DIR / project_name / "filmstrip_videos")
    os.makedirs(output_dir, exist_ok=True)

    if (args.block is None) != (args.page is None):
        print("❌ --block и --page нужно указывать вместе")
        return 1

    if args.block is not None:
        indices = [i for i, (b, p, _) in enumerate(pages) if b == args.block and p == args.page]
        if not indices:
            print(f"❌ Страница B{args.block}_p{args.page} не найдена среди собранных страниц")
            return 1
    else:
        indices = list(range(len(pages)))

    print(f"📁 Всего страниц в проекте: {len(pages)}. К рендеру: {len(indices)}")

    with tempfile.TemporaryDirectory(prefix="filmstrip_allneg_") as tmp_dir:
        neg_cache = NegativeCache(args.template, args.texture, tmp_dir)

        for n, i in enumerate(indices, start=1):
            block_id, page_idx, photos = pages[i]
            output_path = os.path.join(output_dir, f"B{block_id}_p{page_idx}.mp4")
            print(f"\n=== [{n}/{len(indices)}] B{block_id}_p{page_idx} ===")

            curr_path = ensure_curr_rendered(filmstrips_dir, block_id, page_idx, photos, args.template, args.texture)

            prev_path = None
            if i > 0:
                pb, pp, pphotos = pages[i - 1]
                prev_path = neg_cache.get(pb, pp, pphotos)

            next_path = None
            if i < len(pages) - 1:
                nb, np_, nphotos = pages[i + 1]
                next_path = neg_cache.get(nb, np_, nphotos)

            render_table_video(curr_path, prev_path, next_path, output_path, args.bg_video, args.bg_start_frame)

    print(f"\n✅ Готово. Видео в: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
