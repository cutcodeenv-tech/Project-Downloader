"""Render a transparent-alpha overlay video (QuickTime Animation/qtrle) from timing.json.

For each row in timing.json, renders one static transparent PNG "card" (line
number + script text + every non-empty extra field, e.g. ТЗ-видео/ТЗ-графика)
via PIL with auto-fit text (font size shrinks to fit each text block's
allotted area -- cells can hold long production-note paragraphs), encodes it
to a short QuickTime Animation clip held for that row's [start, end) duration.
One fragment file per CSV row is written to --clips-dir (named by line_no) --
they are NOT concatenated into a single overlay file, so each row can be
dropped onto the timeline independently.

Usage:
    uv run helpers/render_overlay.py --timing work/timing.json \
        [--width 1920] [--height 1080] [--fps 30] [--clips-dir out/overlay_clips]
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
]


def font_path() -> str:
    for candidate in FONT_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    raise FileNotFoundError("No usable system font found; install one of: " + ", ".join(FONT_CANDIDATES))


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    lines: list[str] = []
    for paragraph in text.splitlines() or [text]:
        words = paragraph.split()
        cur = ""
        for w in words:
            trial = f"{cur} {w}".strip()
            if draw.textlength(trial, font=font) <= max_width:
                cur = trial
            else:
                if cur:
                    lines.append(cur)
                cur = w
        lines.append(cur)
    return lines


def fit_text_block(
    draw: ImageDraw.ImageDraw, text: str, max_width: int, max_height: int, max_size: int, min_size: int = 12
) -> tuple[ImageFont.FreeTypeFont, list[str], float]:
    """Shrink font size until the wrapped text fits max_width x max_height.
    Falls back to min_size (possibly overflowing) if it never fits."""
    path = font_path()
    size = max_size
    font = ImageFont.truetype(path, size)
    lines = wrap_text(draw, text, font, max_width)
    while size > min_size:
        line_h = font.getbbox("Ag")[3] * 1.35
        if line_h * len(lines) <= max_height:
            return font, lines, line_h
        size -= 2
        font = ImageFont.truetype(path, size)
        lines = wrap_text(draw, text, font, max_width)
    line_h = font.getbbox("Ag")[3] * 1.35
    return font, lines, line_h


def draw_block(draw: ImageDraw.ImageDraw, x: int, y: int, text: str, max_width: int, max_height: int, max_size: int, min_size: int, color: tuple) -> int:
    """Draws an auto-fit text block, returns the height actually used."""
    if not text.strip():
        return 0
    font, lines, line_h = fit_text_block(draw, text, max_width, max_height, max_size, min_size)
    cy = y
    for line in lines:
        draw.text((x, cy), line, font=font, fill=color)
        cy += line_h
    return cy - y


def render_card(row: dict, width: int, height: int, out_path: Path) -> None:
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    margin = int(width * 0.06)
    content_w = width - 2 * margin

    label_font = ImageFont.truetype(font_path(), int(height * 0.03))

    # Fixed-size plate regardless of digit count ("1" vs "245" must render
    # the same badge size) -- text is centered inside it, the box never
    # resizes to fit the text.
    plate_w, plate_h = int(height * 0.085), int(height * 0.05)
    plate_x, plate_y = margin, int(height * 0.03)
    draw.rounded_rectangle(
        [plate_x, plate_y, plate_x + plate_w, plate_y + plate_h],
        radius=int(plate_h * 0.25), fill=(255, 255, 255, 40),
    )
    # A duplicate-take card's line_no carries a "_1"/"_2" suffix (for a
    # unique card filename) that must not show in the badge itself.
    label_text = re.sub(r"_\d+$", "", str(row["line_no"]))
    bbox = draw.textbbox((0, 0), label_text, font=label_font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx = plate_x + (plate_w - tw) / 2 - bbox[0]
    ty = plate_y + (plate_h - th) / 2 - bbox[1]
    draw.text((tx, ty), label_text, font=label_font, fill=(255, 255, 255, 220))

    if row.get("is_duplicate"):
        dup_x = plate_x + plate_w + int(width * 0.015)
        draw.rounded_rectangle(
            [dup_x, plate_y, dup_x + int(height * 0.11), plate_y + plate_h],
            radius=int(plate_h * 0.25), fill=(200, 60, 60, 130),
        )
        dup_text = "ДУБЛЬ"
        dbbox = draw.textbbox((0, 0), dup_text, font=label_font)
        dtw, dth = dbbox[2] - dbbox[0], dbbox[3] - dbbox[1]
        dtx = dup_x + (int(height * 0.11) - dtw) / 2 - dbbox[0]
        dty = plate_y + (plate_h - dth) / 2 - dbbox[1]
        draw.text((dtx, dty), dup_text, font=label_font, fill=(255, 255, 255, 235))

    fields = row.get("fields", {})
    non_empty_fields = [(k, v) for k, v in fields.items() if v.strip()]

    top = int(height * 0.10)
    bottom = int(height * 0.94)
    available = bottom - top

    # Main script text gets ~45% of the space (or all of it if there are no
    # extra fields), the rest is split evenly among non-empty extra fields.
    main_h = int(available * (0.45 if non_empty_fields else 1.0))
    y = top
    used = draw_block(draw, margin, y, row["text"], content_w, main_h, max_size=int(height * 0.055), min_size=16, color=(255, 255, 255, 255))
    y += max(used, 0) + int(height * 0.02)

    if non_empty_fields:
        remaining = bottom - y
        per_field = remaining // len(non_empty_fields)
        for key, val in non_empty_fields:
            label_h = int(height * 0.03)
            draw.text((margin, y), key, font=label_font, fill=(255, 210, 90, 220))
            y += label_h
            used = draw_block(draw, margin, y, val, content_w, per_field - label_h, max_size=int(height * 0.032), min_size=12, color=(230, 230, 230, 255))
            y += used + int(height * 0.015)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)


def render_clip(card_path: Path, n_frames: int, fps: int, out_path: Path) -> None:
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", str(card_path),
        "-frames:v", str(max(n_frames, 1)),
        "-r", str(fps),
        "-c:v", "qtrle", "-pix_fmt", "argb",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def render_blank(width: int, height: int, out_path: Path) -> None:
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timing", default="work/timing.json")
    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--height", type=int, default=1080)
    ap.add_argument("--fps", type=int, default=25)
    ap.add_argument("--cards-dir", default="work/cards")
    ap.add_argument("--clips-dir", default="out/overlay_clips")
    ap.add_argument("--duration", type=float, default=None, help="total overlay duration in seconds (e.g. the untouched source audio's duration); defaults to the last row's end + 1s")
    args = ap.parse_args()

    timing = json.loads(Path(args.timing).read_text(encoding="utf-8"))
    if not timing:
        raise SystemExit("timing.json is empty")
    timing.sort(key=lambda r: r["start"])

    cards_dir = Path(args.cards_dir)
    clips_dir = Path(args.clips_dir)
    cards_dir.mkdir(parents=True, exist_ok=True)
    clips_dir.mkdir(parents=True, exist_ok=True)

    total_duration = args.duration if args.duration is not None else timing[-1]["end"] + 1.0
    total_frames = round(total_duration * args.fps)

    blank_path = cards_dir / "_blank.png"
    render_blank(args.width, args.height, blank_path)

    # One output FILE per CSV row, named by that row's line_no, for fast
    # timeline navigation -- a duplicate-take entry ("16_1") is NOT its own
    # file, it's an earlier segment INSIDE line 16's file. A card still
    # holds on screen through any pause after it, until the next segment
    # (another duplicate, or the main take) starts -- that's just now
    # happening both within a row's file and across row files.
    # Frame counts are derived from CUMULATIVE time (round(t*fps) deltas),
    # never from each clip's own isolated duration, so independent per-clip
    # rounding can't accumulate into audio/video drift over hundreds of rows.
    groups: dict[str, list[dict]] = {}
    order: list[str] = []
    for row in timing:
        base = re.sub(r"_\d+$", "", row["line_no"])
        if base not in groups:
            groups[base] = []
            order.append(base)
        groups[base].append(row)
    for base in groups:
        groups[base].sort(key=lambda r: r["start"])
    order.sort(key=lambda base: groups[base][0]["start"])

    pad = max(3, len(str(len(order))))
    parts_dir = clips_dir / "_parts"
    parts_dir.mkdir(parents=True, exist_ok=True)

    final_paths = []
    cursor = 0
    for gi, base in enumerate(order):
        entries = groups[base]
        next_group_start = groups[order[gi + 1]][0]["start"] if gi + 1 < len(order) else total_duration

        sub_clips = []
        if gi == 0 and round(entries[0]["start"] * args.fps) > 0:
            lead_frames = round(entries[0]["start"] * args.fps)
            lead_clip = parts_dir / f"{base}_lead.mov"
            render_clip(blank_path, lead_frames, args.fps, lead_clip)
            sub_clips.append(lead_clip)
            cursor = lead_frames

        for ei, entry in enumerate(entries):
            start_frame = round(entry["start"] * args.fps)
            entry_next_start = entries[ei + 1]["start"] if ei + 1 < len(entries) else next_group_start
            end_frame = round(entry_next_start * args.fps)

            if start_frame < cursor:
                print(f"  warning: line {entry['line_no']} starts before the previous segment's hold ends (overlap) -- clamping")
                start_frame = cursor
            if end_frame <= start_frame:
                print(f"  warning: line {entry['line_no']} has zero/negative duration after clamping -- skipping")
                continue

            card_path = cards_dir / f"card_{entry['line_no']}.png"
            render_card(entry, args.width, args.height, card_path)

            n_frames = end_frame - start_frame
            sub_clip = parts_dir / f"{entry['line_no']}.mov"
            render_clip(card_path, n_frames, args.fps, sub_clip)
            sub_clips.append(sub_clip)
            cursor = end_frame

        if gi == len(order) - 1 and cursor < total_frames:
            tail_clip = parts_dir / f"{base}_tail.mov"
            render_clip(blank_path, total_frames - cursor, args.fps, tail_clip)
            sub_clips.append(tail_clip)

        if not sub_clips:
            # Every entry in this group got clamped to zero/negative duration
            # (its whole window was swallowed by an overlapping neighbor,
            # e.g. a stray "duplicate take" from another row landing on the
            # same span) -- there is nothing to render for this row, and an
            # empty concat list would make ffmpeg fail outright below.
            print(f"  warning: line {base} has no visible duration after clamping -- no clip written for it")
            continue

        group_list = parts_dir / f"{base}_list.txt"
        with group_list.open("w", encoding="utf-8") as f:
            for p in sub_clips:
                f.write(f"file '{p.resolve()}'\n")
        final_path = clips_dir / f"{int(base):0{pad}d}.mov"
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(group_list), "-c", "copy", str(final_path)],
            check=True, capture_output=True,
        )
        final_paths.append(final_path)
        print(f"  [{gi+1}/{len(order)}] rendered line {base} -> {final_path.name} ({len(sub_clips)} segment(s))")

    print(f"Wrote {len(final_paths)} overlay fragment(s) -> {clips_dir}")

    shutil.rmtree(parts_dir, ignore_errors=True)
    print(f"Cleaned up {parts_dir} (intermediate per-segment clips)")


if __name__ == "__main__":
    main()
