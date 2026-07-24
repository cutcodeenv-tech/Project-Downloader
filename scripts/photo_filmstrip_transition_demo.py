#!/usr/bin/env python3
"""
Демо ОДНОГО перехода между наборами фото (плёнка A -> плёнка B) — не встроено
в общий пайплайн, только для проверки идеи.

Раскадровка — «протяжка» плёнки A в её собственные негативы + вход в B:
  держим кадр 3 (цвет) -> камера продолжает тот же панорамный ход вправо и
  проезжает по уже готовым ч/б-негативам 4 и 5 плёнки A (это реальные пиксели
  плёнки, никакой синтетики) -> короткий рывок дальше за край + вспышка ->
  на пике плёнка B появляется уже в синтетическом негативе и тем же рывком
  выходит в цвет на кадре 1 -> держим кадр 1.

Общая логика (геометрия плёнки, фон, блюр/аберрация/виньетка) переиспользует
код из photo_filmstrip_anim.py.
"""

import argparse
import os
import subprocess
import sys

import numpy as np
from PIL import Image, ImageOps

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from photo_filmstrip_anim import (
    OUTPUT_W, OUTPUT_H, OUTPUT_ASPECT, FPS, FRAME_PADDING,
    build_strip_geometry, compose_frame, apply_zoom_blur, apply_chromatic_aberration,
    build_radial_mask, BgVideoReader, _DEFAULT_BG_VIDEO, _BG_START_FRAME,
)

HOLD_S = 0.7     # держим кадр до/после перехода
LEG1_S = 0.16    # пан: кадр3(цвет) -> негатив-4 (по реальной плёнке)
LEG2_S = 0.12    # пан: негатив-4 -> негатив-5
LEG3_S = 0.11    # рывок дальше за край + нарастание вспышки
ENTRY_S = 0.28   # приход в плёнку B: из вспышки/негатива в цвет на кадре 1

PEAK_ZOOM = 0.82        # доп. приближение на пиковых точках (рывок за край / вход в B)
PEAK_PUSH_FRAC = 0.35   # на сколько долей ширины окна проезжаем дальше края негатива-5

FLASH_STRENGTH = 0.85
FLASH_COLOR = (250, 248, 244)


def hold_state(geom, idx: int):
    cx, cy = geom["frame_centers"][idx]
    w, h = geom["frame_sizes"][idx]
    w *= FRAME_PADDING
    h *= FRAME_PADDING
    if w / h > OUTPUT_ASPECT:
        h = w / OUTPUT_ASPECT
    else:
        w = h * OUTPUT_ASPECT
    return cx, cy, w, h


def to_negative_array(frame: Image.Image) -> np.ndarray:
    neg = ImageOps.invert(frame.convert("L").convert("RGB"))
    return np.asarray(neg, dtype=np.float32)


def render_frame(geom, bg_frame, cx, cy, win_w, win_h, color_mix, flash_amt, edge_mask, vignette_factor):
    frame = compose_frame(geom, bg_frame, cx, cy, win_w, win_h)
    frame = apply_zoom_blur(frame, edge_mask)

    normal = np.asarray(frame, dtype=np.float32) if not isinstance(frame, np.ndarray) else frame
    if color_mix > 0:
        neg = to_negative_array(Image.fromarray(np.clip(normal, 0, 255).astype(np.uint8)))
        normal = normal * (1 - color_mix) + neg * color_mix

    if flash_amt > 0:
        flash = np.array(FLASH_COLOR, dtype=np.float32)
        normal = normal * (1 - flash_amt) + flash * flash_amt

    arr = apply_chromatic_aberration(np.clip(normal, 0, 255).astype(np.uint8), edge_mask)
    arr = arr * vignette_factor[:, :, None]
    return np.clip(arr, 0, 255).astype(np.uint8)


def lerp_state(s0, s1, e):
    return tuple(a + (b - a) * e for a, b in zip(s0, s1))


def main() -> int:
    parser = argparse.ArgumentParser(description="Демо перехода: протяжка A в негативы -> вспышка -> вход в B")
    parser.add_argument("--input-a", required=True, help="Плёнка A (уходим с последнего кадра)")
    parser.add_argument("--input-b", required=True, help="Плёнка B (приходим на первый кадр)")
    parser.add_argument("--output", required=True)
    parser.add_argument("--bg-video", default=str(_DEFAULT_BG_VIDEO))
    parser.add_argument("--bg-start-frame", type=int, default=_BG_START_FRAME)
    args = parser.parse_args()

    geom_a = build_strip_geometry(args.input_a)
    geom_b = build_strip_geometry(args.input_b)

    hold_a = hold_state(geom_a, 2)   # кадр 3 плёнки A, в цвете
    box3_a = hold_state(geom_a, 3)   # уже готовый ч/б негатив (реальные пиксели плёнки)
    box4_a = hold_state(geom_a, 4)   # уже готовый ч/б негатив (реальные пиксели плёнки)
    hold_b = hold_state(geom_b, 0)   # кадр 1 плёнки B, в цвете

    # Пиковая точка на выходе: чуть дальше края последнего негатива A + доп. зум.
    peak_a = (
        box4_a[0] + box4_a[2] * PEAK_PUSH_FRAC,
        box4_a[1],
        box4_a[2] * PEAK_ZOOM,
        box4_a[3] * PEAK_ZOOM,
    )
    # Зеркальная пиковая точка на входе в B: чуть раньше кадра 1 + тот же зум.
    peak_b = (
        hold_b[0] - hold_b[2] * PEAK_PUSH_FRAC,
        hold_b[1],
        hold_b[2] * PEAK_ZOOM,
        hold_b[3] * PEAK_ZOOM,
    )

    S = lambda state, color, flash: (*state, color, flash)

    segments = [
        # (длительность, geom, состояние-начало, состояние-конец)
        (HOLD_S, geom_a, S(hold_a, 0.0, 0.0), S(hold_a, 0.0, 0.0)),
        (LEG1_S, geom_a, S(hold_a, 0.0, 0.0), S(box3_a, 0.0, 0.0)),
        (LEG2_S, geom_a, S(box3_a, 0.0, 0.0), S(box4_a, 0.0, 0.0)),
        (LEG3_S, geom_a, S(box4_a, 0.0, 0.0), S(peak_a, 0.0, FLASH_STRENGTH)),
        (ENTRY_S, geom_b, S(peak_b, 1.0, FLASH_STRENGTH), S(hold_b, 0.0, 0.0)),
        (HOLD_S, geom_b, S(hold_b, 0.0, 0.0), S(hold_b, 0.0, 0.0)),
    ]

    vignette_factor = 1 - 0.10 * build_radial_mask(OUTPUT_W, OUTPUT_H, 2.6)
    edge_mask = build_radial_mask(OUTPUT_W, OUTPUT_H, 1.6)
    bg_reader = BgVideoReader(args.bg_video, args.bg_start_frame)

    seg_frames = [round(dur * FPS) for dur, *_ in segments]
    total_frames = sum(seg_frames)

    cmd = [
        "ffmpeg", "-y", "-nostdin",
        "-f", "rawvideo", "-pixel_format", "rgb24",
        "-video_size", f"{OUTPUT_W}x{OUTPUT_H}", "-framerate", str(FPS),
        "-i", "-",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "16", "-preset", "slow",
        str(args.output),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    try:
        frame_idx = 0
        for (dur, geom, s0, s1), n in zip(segments, seg_frames):
            for i in range(n):
                e = i / max(n - 1, 1) if n > 1 else 1.0
                cx, cy, w, h, color_mix, flash_amt = lerp_state(s0, s1, e)
                bg_frame = bg_reader.next_frame()
                arr = render_frame(geom, bg_frame, cx, cy, w, h, color_mix, flash_amt, edge_mask, vignette_factor)
                proc.stdin.write(arr.tobytes())
                if frame_idx % 10 == 0:
                    print(f"  кадр {frame_idx}/{total_frames}")
                frame_idx += 1
    finally:
        bg_reader.close()
        proc.stdin.close()
        proc.wait()

    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg завершился с ошибкой: {proc.returncode}")
    print(f"✅ Готово: {args.output} ({total_frames} кадров)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
