#!/usr/bin/env python3
"""
Анимация плёнки с фото (результат photo_filmstrip.py) в кадре 16:9.

Фон — живое видео (assets_media/BG_DOC_NEW.mov), проигрывается с 140-го кадра
(пропускаем начало ролика). Плёнка вписана по центру поверх фона.

Камера: пуш-ин на 1-й кадр плёнки (с лёгким «дышащим» шейком, который плавно
нарастает, чтобы зум-ин не «ёрзал»), удержание, панорама на 2-й кадр,
удержание, панорама на 3-й, удержание. Движение камеры сделано «степпингом»
(stop-motion) — позиция обновляется не каждый кадр, а раз в STOPMOTION_STEP
кадров, отчего движение чуть дёрганое, не современно-плавное.

По краям кадра — виньетка, лёгкий зум-блюр (радиальное размытие к периферии)
и хроматическая аберрация (небольшое рассовмещение R/B каналов к краям).

Работает поверх уже собранной плёнки (см. photo_filmstrip.py) — раскладку
фото не трогает, только оживляет готовую картинку камерой и фоном.
Полностью детерминированный скрипт: параметры движения/эффектов — константы
или аргументы командной строки, без ручной доводки.
"""

import argparse
import math
import os
import subprocess
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from path_utils import get_base_dir as _get_base_dir, get_assets_media_dir as _get_assets_media_dir
from photo_filmstrip import FRAME_BOXES  # позиции 1/2/3 = FRAME_BOXES[0..2]

_BASE_DIR = _get_base_dir(__file__)
_DEFAULT_BG_VIDEO = _get_assets_media_dir(__file__) / "BG_DOC_NEW.mov"
_BG_START_FRAME = 140

OUTPUT_W, OUTPUT_H = 1920, 1080
OUTPUT_ASPECT = OUTPUT_W / OUTPUT_H

CANVAS_SCALE = 6  # во сколько раз внутренний холст (координатная система) крупнее финального кадра
STRIP_WIDTH_FRACTION = 0.9  # какую долю ширины холста занимает плёнка

INTRO_S = 1.2   # пуш-ин на первый кадр
HOLD_S = 2.0    # удержание на каждом кадре
PAN_S = 0.85    # переход между кадрами
FPS = 25

WIDE_ZOOM_FACTOR = 2.3  # во сколько раз стартовый (широкий) вид шире целевого зума
FRAME_PADDING = 1.12    # запас вокруг фото в целевом зуме (1.0 = впритык)

SHAKE_POS_AMP = 0.0035   # амплитуда дрожания центра, доля ширины окна кропа
SHAKE_ZOOM_AMP = 0.005   # амплитуда дрожания зума

STOPMOTION_STEP = 2  # раз в сколько кадров обновляется позиция камеры (эффект стоп-моушн)

VIGNETTE_STRENGTH = 0.10
ZOOM_BLUR_STRENGTH = 0.5   # доля примешивания радиального блюра на самом краю кадра
ZOOM_BLUR_STEPS = 4
ZOOM_BLUR_AMOUNT = 0.05    # на сколько "раздувает" картинку на последнем шаге блюра
CHROMA_ABERRATION_AMOUNT = 0.006  # относительное рассовмещение R/B каналов на краю


def ease_in_out(t: float) -> float:
    """Smootherstep (Perlin) — более плавный и «точный» разгон/торможение,
    чем классический smoothstep: меньше видимого дёргания на старте/финише."""
    t = max(0.0, min(1.0, t))
    return t * t * t * (t * (t * 6 - 15) + 10)


# ── Геометрия плёнки на холсте ────────────────────────────────────────────────

def build_strip_geometry(strip_path: str):
    """Считает, где на холсте (в его координатах) лежит плёнка и центры/размеры
    всех 5 рамок (индексы 0-2 — уникальные фото, 3-4 — их же готовые ч/б
    негативы из самой плёнки, см. photo_filmstrip.py). Сам файл плёнки не
    ресайзится тут — он остаётся исходного разрешения, чтобы брать из него
    чёткие кропы."""
    strip = Image.open(strip_path).convert("RGB")
    canvas_w, canvas_h = OUTPUT_W * CANVAS_SCALE, OUTPUT_H * CANVAS_SCALE

    target_w = round(canvas_w * STRIP_WIDTH_FRACTION)
    scale = target_w / strip.width
    target_h = round(strip.height * scale)

    offset_x = (canvas_w - target_w) // 2
    offset_y = (canvas_h - target_h) // 2
    strip_box_canvas = (offset_x, offset_y, offset_x + target_w, offset_y + target_h)

    def to_canvas(point):
        x, y = point
        return offset_x + x * scale, offset_y + y * scale

    frame_centers, frame_sizes = [], []
    for box in FRAME_BOXES:
        x0, y0, x1, y1 = box
        cx, cy = to_canvas(((x0 + x1) / 2, (y0 + y1) / 2))
        frame_centers.append((cx, cy))
        frame_sizes.append(((x1 - x0) * scale, (y1 - y0) * scale))

    return {
        "strip": strip,
        "scale": scale,
        "strip_box_canvas": strip_box_canvas,
        "canvas_size": (canvas_w, canvas_h),
        "frame_centers": frame_centers,
        "frame_sizes": frame_sizes,
    }


# ── Таймлайн камеры ───────────────────────────────────────────────────────────

def build_timeline():
    segments = []
    t = 0.0
    segments.append((t, t + INTRO_S, "intro", 0, 0)); t += INTRO_S
    segments.append((t, t + HOLD_S, "hold", 0, 0)); t += HOLD_S
    segments.append((t, t + PAN_S, "pan", 0, 1)); t += PAN_S
    segments.append((t, t + HOLD_S, "hold", 1, 1)); t += HOLD_S
    segments.append((t, t + PAN_S, "pan", 1, 2)); t += PAN_S
    segments.append((t, t + HOLD_S, "hold", 2, 2)); t += HOLD_S
    return segments, t


def camera_state(t: float, segments, frame_centers, frame_sizes):
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


def apply_shake(t: float, cx: float, cy: float, win_w: float, win_h: float):
    # На пуш-ине шейк плавно нарастает от нуля к моменту прихода на кадр —
    # иначе зум-ин «ёрзает», потому что окно кропа и так быстро меняется.
    gain = ease_in_out(t / INTRO_S) if t < INTRO_S else 1.0

    dx = win_w * SHAKE_POS_AMP * gain * (0.7 * math.sin(2 * math.pi * 0.55 * t + 0.3)
                                          + 0.3 * math.sin(2 * math.pi * 1.35 * t + 2.1))
    dy = win_h * SHAKE_POS_AMP * gain * (0.7 * math.sin(2 * math.pi * 0.47 * t + 1.1)
                                          + 0.3 * math.sin(2 * math.pi * 1.1 * t + 0.4))
    zoom_jitter = 1 + SHAKE_ZOOM_AMP * gain * math.sin(2 * math.pi * 0.35 * t + 0.7)
    return cx + dx, cy + dy, win_w * zoom_jitter, win_h * zoom_jitter


def stepped_time(frame_idx: int) -> float:
    """Квантует время под STOPMOTION_STEP кадров — камера «держит» позу и
    прыгает к следующей, а не едет плавно каждый кадр."""
    stepped_idx = (frame_idx // STOPMOTION_STEP) * STOPMOTION_STEP
    return stepped_idx / FPS


# ── Фон-видео ──────────────────────────────────────────────────────────────

class BgVideoReader:
    """Отдаёт кадры фонового видео начиная с start_frame; если запрошено больше
    кадров, чем осталось в ролике, зацикливает проигрывание с того же старта.
    Фон живёт независимо от камеры — всегда во весь кадр, без зума/кропа."""

    def __init__(self, video_path: str, start_frame: int, size=(OUTPUT_W, OUTPUT_H)):
        self.video_path = video_path
        self.start_frame = start_frame
        self.w, self.h = size
        self.frame_bytes = self.w * self.h * 3
        self._proc = None
        self._open()

    def _open(self):
        if self._proc is not None:
            self._proc.stdout.close()
            self._proc.wait()
        cmd = [
            "ffmpeg", "-nostdin", "-i", self.video_path,
            "-vf", f"select='gte(n\\,{self.start_frame})',scale={self.w}:{self.h}",
            # ffmpeg 9 удалил -vsync; современный эквивалент -vsync 0
            "-fps_mode", "passthrough",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
        ]
        self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       bufsize=self.frame_bytes * 4)

    def next_frame(self) -> Image.Image:
        buf = self._proc.stdout.read(self.frame_bytes)
        if len(buf) < self.frame_bytes:
            self._open()
            buf = self._proc.stdout.read(self.frame_bytes)
            if len(buf) < self.frame_bytes:
                stderr = (self._proc.stderr.read() or b"").decode("utf-8", "replace").strip()
                tail = "\n".join(stderr.splitlines()[-4:])
                raise RuntimeError(
                    f"Не удалось прочитать кадр фона из {os.path.basename(self.video_path)}"
                    + (f"\nffmpeg: {tail}" if tail else "")
                )
        return Image.frombuffer("RGB", (self.w, self.h), buf, "raw", "RGB", 0, 1).copy()

    def close(self):
        if self._proc is not None:
            self._proc.stdout.close()
            self._proc.terminate()


# ── Пост-эффекты ──────────────────────────────────────────────────────────────

def build_radial_mask(w: int, h: int, power: float) -> np.ndarray:
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    nx = (xx - w / 2) / (w / 2)
    ny = (yy - h / 2) / (h / 2)
    dist = np.sqrt(nx ** 2 + ny ** 2)
    dist = np.clip(dist, 0, 1.4) / 1.4
    return dist ** power


def apply_zoom_blur(img: Image.Image, edge_mask: np.ndarray) -> Image.Image:
    w, h = img.size
    acc = np.zeros((h, w, 3), dtype=np.float32)
    for i in range(ZOOM_BLUR_STEPS):
        s = 1.0 + ZOOM_BLUR_AMOUNT * (i + 1) / ZOOM_BLUR_STEPS
        nw, nh = round(w * s), round(h * s)
        scaled = img.resize((nw, nh), Image.BILINEAR)
        left, top = (nw - w) // 2, (nh - h) // 2
        acc += np.asarray(scaled.crop((left, top, left + w, top + h)), dtype=np.float32)
    blurred = acc / ZOOM_BLUR_STEPS

    original = np.asarray(img, dtype=np.float32)
    mix = (edge_mask * ZOOM_BLUR_STRENGTH)[:, :, None]
    return original * (1 - mix) + blurred * mix


def apply_chromatic_aberration(arr: np.ndarray, edge_mask: np.ndarray) -> np.ndarray:
    h, w = arr.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    nx = (xx - w / 2) / (w / 2)
    ny = (yy - h / 2) / (h / 2)
    amt = edge_mask * CHROMA_ABERRATION_AMOUNT

    def sample_channel(channel, k):
        src_x = np.clip(xx + nx * amt * (w / 2) * k, 0, w - 1)
        src_y = np.clip(yy + ny * amt * (h / 2) * k, 0, h - 1)
        return channel[src_y.astype(np.int32), src_x.astype(np.int32)]

    r = sample_channel(arr[:, :, 0], 1.0)
    g = arr[:, :, 1]
    b = sample_channel(arr[:, :, 2], -1.0)
    return np.stack([r, g, b], axis=-1)


# ── Компоновка одного кадра ───────────────────────────────────────────────────

def compose_frame(geom, bg_frame: Image.Image, cx, cy, win_w, win_h):
    canvas_w, canvas_h = geom["canvas_size"]
    win_w = min(win_w, canvas_w)
    win_h = min(win_h, canvas_h)
    # Окно кропа камеры честно центрировано на (cx, cy) — двигает и зумит
    # только плёнку. Фон в это движение не вовлечён вообще: он не часть
    # холста, который «снимает» камера, а отдельный статичный слой на весь
    # кадр (см. ниже) — просто живёт своей жизнью на фоне.
    left = cx - win_w / 2
    top = cy - win_h / 2
    right, bottom = left + win_w, top + win_h
    scale_out = OUTPUT_W / win_w

    # Фон: независим от камеры, всегда во весь кадр, без кропа и зума.
    frame = bg_frame.copy()

    # Плёнка: пересечение окна кропа с прямоугольником плёнки на холсте,
    # кроп берём из исходного (не уменьшенного) файла плёнки — чётче на зуме.
    sx0, sy0, sx1, sy1 = geom["strip_box_canvas"]
    ix0, iy0 = max(left, sx0), max(top, sy0)
    ix1, iy1 = min(right, sx1), min(bottom, sy1)
    if ix1 > ix0 and iy1 > iy0:
        scale = geom["scale"]
        strip = geom["strip"]
        src_box = ((ix0 - sx0) / scale, (iy0 - sy0) / scale,
                   (ix1 - sx0) / scale, (iy1 - sy0) / scale)
        src_box = (max(0, src_box[0]), max(0, src_box[1]),
                   min(strip.width, src_box[2]), min(strip.height, src_box[3]))
        out_w = round((ix1 - ix0) * scale_out)
        out_h = round((iy1 - iy0) * scale_out)
        if out_w > 0 and out_h > 0:
            strip_crop = strip.resize((out_w, out_h), Image.LANCZOS, box=src_box)
            paste_x = round((ix0 - left) * scale_out)
            paste_y = round((iy0 - top) * scale_out)
            frame.paste(strip_crop, (paste_x, paste_y))

    return frame


def render(strip_path: str, output_path: str, bg_video: str, bg_start_frame: int):
    geom = build_strip_geometry(strip_path)
    segments, total_s = build_timeline()
    total_frames = round(total_s * FPS)

    # build_radial_mask: 0 в центре -> 1 к краям. Для виньетки превращаем в
    # коэффициент затемнения (1 в центре -> 1-VIGNETTE_STRENGTH к краям).
    vignette_factor = 1 - VIGNETTE_STRENGTH * build_radial_mask(OUTPUT_W, OUTPUT_H, 2.6)
    edge_mask = build_radial_mask(OUTPUT_W, OUTPUT_H, 1.6)  # мягче к центру — для блюра/аберрации

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
            t_pose = stepped_time(frame_idx)  # степпинг под стоп-моушн
            cx, cy, win_w, win_h = camera_state(t_pose, segments, geom["frame_centers"], geom["frame_sizes"])
            cx, cy, win_w, win_h = apply_shake(t_pose, cx, cy, win_w, win_h)

            bg_frame = bg_reader.next_frame()
            frame = compose_frame(geom, bg_frame, cx, cy, win_w, win_h)
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Анимация плёнки с фото в кадре 16:9")
    parser.add_argument("--input", required=True, help="Путь к собранной плёнке (B<block>_p<n>.jpg)")
    parser.add_argument("--output", default=None, help="Путь к выходному .mp4 (по умолчанию рядом со входом)")
    parser.add_argument("--bg-video", default=str(_DEFAULT_BG_VIDEO), help="Фоновое видео")
    parser.add_argument("--bg-start-frame", type=int, default=_BG_START_FRAME, help="С какого кадра фона начинать")
    args = parser.parse_args()

    if not os.path.isfile(args.input):
        print(f"❌ Файл не найден: {args.input}")
        return 1
    if not os.path.isfile(args.bg_video):
        print(f"❌ Фоновое видео не найдено: {args.bg_video}")
        return 1

    output_path = args.output or os.path.splitext(args.input)[0] + ".mp4"
    render(args.input, output_path, args.bg_video, args.bg_start_frame)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
