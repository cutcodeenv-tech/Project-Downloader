#!/usr/bin/env python3
"""
1.2_xml_placeholders.py — генератор прозрачного видео-оверлея с номером ячейки сценария.

На вход:
  - CSV-сценарий, разбитый на фразы (одна строка = одна «ячейка»).
  - Расшифровка озвучки с таймкодами (.srt или .txt-таймкод формата
    "HH:MM:SS:FF - HH:MM:SS:FF  текст") — в папке voiceover/ проекта.

На выход (папка placeholders_xml/):
  - {row_number}.mov на каждую ячейку (ProRes / QuickTime с альфа-каналом).
  - manifest.csv — таблица соответствий файлов и таймкодов.

Запуск из веб-интерфейса (PROJECT_NAME задан автоматически).
Ручной запуск:
  python3 1.2_xml_placeholders.py --csv script.csv --transcript voice.srt --out-dir /path/out
  python3 1.2_xml_placeholders.py --csv script.csv --transcript voice.srt --dump-timeline

Зависимости: стандартная библиотека Python + ffmpeg в PATH.
"""

import argparse
import csv
import difflib
import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile


# ─── парсинг CSV ─────────────────────────────────────────────────────────────

def _resolve_col(spec, rows):
    if spec is None:
        return None
    s = spec.strip()
    if s.isdigit():
        return int(s)
    if len(s) == 1 and s.isalpha():
        return ord(s.upper()) - 65
    norm = [c.strip().lower() for c in rows[0]]
    if s.lower() in norm:
        return norm.index(s.lower())
    sys.exit(f"Колонка '{spec}' не найдена. Заголовок: {rows[0]}")


def _col_letter(idx):
    return chr(65 + idx) if idx is not None and 0 <= idx < 26 else str(idx)


def parse_csv(path, col_a=None, col_b=None):
    """CSV → [(rownum, textA, textB)], rownum 1-based = номер ячейки."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    if not rows:
        sys.exit(f"CSV пустой: {path}")
    ncols = max((len(r) for r in rows), default=0)

    def filled(c):
        return sum(1 for r in rows if c < len(r) and r[c].strip())

    a = _resolve_col(col_a, rows)
    b = _resolve_col(col_b, rows)
    if a is None:
        ranked = sorted((c for c in range(ncols) if filled(c)),
                        key=lambda c: (-filled(c), c))
        top = sorted(ranked[:2])
        a = top[0] if top else 0
        if b is None and len(top) > 1:
            b = top[1]

    header_kw = {"script", "текст", "фраза", "сценарий", "монтаж", "реплика", ""}

    def cellval(row, c):
        return row[c].strip() if c is not None and c < len(row) else ""

    cells = []
    for i, row in enumerate(rows):
        ta = cellval(row, a)
        if not ta or ta.startswith("#") or ta.startswith("//"):
            continue
        if i == 0 and ta.lower() in header_kw:
            continue
        tb = cellval(row, b)
        if i == 0 and tb.lower() in header_kw:
            tb = ""
        cells.append((i + 1, ta, tb))
    if not cells:
        sys.exit(f"Не удалось извлечь ячейки из CSV (колонка A={_col_letter(a)}). "
                 "Проверьте --col-a.")
    bnote = f", B={_col_letter(b)}" if b is not None else ""
    print(f"CSV: текст A={_col_letter(a)}{bnote}, ячеек {len(cells)} "
          f"(строки {cells[0][0]}–{cells[-1][0]})")
    return cells


# ─── парсинг расшифровки ─────────────────────────────────────────────────────

def _srt_tc_to_sec(tc):
    tc = tc.strip().replace(".", ",")
    h, m, rest = tc.split(":")
    s, ms = rest.split(",")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def parse_srt(text):
    segments = []
    blocks = re.split(r"\n\s*\n", text.strip())
    for block in blocks:
        lines = [l for l in block.splitlines() if l.strip()]
        if not lines:
            continue
        tc_line = None
        tc_i = 0
        for i, l in enumerate(lines):
            if "-->" in l:
                tc_line = l
                tc_i = i
                break
        if tc_line is None:
            continue
        start_s, end_s = tc_line.split("-->")
        start = _srt_tc_to_sec(start_s)
        end = _srt_tc_to_sec(end_s)
        body = " ".join(lines[tc_i + 1:]).strip()
        if body:
            segments.append((start, end, body))
    return segments


_TXT_LINE = re.compile(
    r"^\s*(\d{1,2}):(\d{2}):(\d{2}):(\d{2})\s*-\s*"
    r"(\d{1,2}):(\d{2}):(\d{2}):(\d{2})\s+(.*\S)\s*$"
)


def parse_txt_timecode(text, fps_tc):
    segments = []
    for line in text.splitlines():
        m = _TXT_LINE.match(line)
        if not m:
            continue
        g = m.groups()
        start = int(g[0]) * 3600 + int(g[1]) * 60 + int(g[2]) + int(g[3]) / fps_tc
        end = int(g[4]) * 3600 + int(g[5]) * 60 + int(g[6]) + int(g[7]) / fps_tc
        segments.append((start, end, g[8].strip()))
    return segments


_TC_LOOSE = re.compile(r"^\s*(?:(\d{1,2}):)?(\d{1,2}):(\d{2})[.,](\d{1,3})\s*$")


def _loose_tc_to_sec(m):
    h = int(m.group(1)) if m.group(1) else 0
    return h * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + int(m.group(4)) / 1000.0


def parse_loose_timecode(text):
    entries = []
    start = None
    buf = []
    for line in text.splitlines():
        m = _TC_LOOSE.match(line)
        if m:
            if start is not None and buf:
                entries.append((start, " ".join(buf).strip()))
            start = _loose_tc_to_sec(m)
            buf = []
        elif line.strip():
            buf.append(line.strip())
    if start is not None and buf:
        entries.append((start, " ".join(buf).strip()))

    segments = []
    for i, (st, body) in enumerate(entries):
        if i + 1 < len(entries):
            end = entries[i + 1][0]
        else:
            end = st + max(2.0, len(body.split()) * 0.4)
        segments.append((st, end, body))
    return segments


def parse_transcript(path, fps_tc):
    with open(path, encoding="utf-8-sig") as f:
        text = f.read()
    candidates = [
        parse_srt(text) if "-->" in text else [],
        parse_txt_timecode(text, fps_tc),
        parse_loose_timecode(text),
    ]
    segments = max(candidates, key=len)
    if not segments:
        sys.exit(f"Не удалось распарсить расшифровку: {path}")
    segments.sort(key=lambda s: s[0])
    return segments


# ─── нормализация и токенизация ──────────────────────────────────────────────

_WORD = re.compile(r"[a-zа-я0-9]+")


def tokenize(text):
    text = text.lower().replace("ё", "е")
    return _WORD.findall(text)


# ─── выравнивание ────────────────────────────────────────────────────────────

def build_transcript_tokens(segments):
    out = []
    for start, end, body in segments:
        toks = tokenize(body)
        if not toks:
            continue
        span = max(end - start, 0.0)
        n = len(toks)
        for i, tok in enumerate(toks):
            t = start + (span * (i + 0.5) / n if n else 0)
            out.append((tok, t))
    return out


def build_script_tokens(cells):
    out = []
    for idx, text_a, _ in cells:
        for tok in tokenize(text_a):
            out.append((tok, idx))
    return out


def align(transcript_tokens, script_tokens):
    a = [t for t, _ in transcript_tokens]
    b = [t for t, _ in script_tokens]
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    assigned = [None] * len(a)
    for ai, bi, size in sm.get_matching_blocks():
        for k in range(size):
            assigned[ai + k] = script_tokens[bi + k][1]

    last = None
    for i in range(len(assigned)):
        if assigned[i] is None:
            assigned[i] = last
        else:
            last = assigned[i]
    nxt = None
    for i in range(len(assigned) - 1, -1, -1):
        if assigned[i] is None:
            assigned[i] = nxt
        else:
            nxt = assigned[i]

    return [(transcript_tokens[i][1], assigned[i]) for i in range(len(a))]


def build_timeline(timed_assignments, total_end):
    pts = [(t, c) for t, c in timed_assignments if c is not None]
    if not pts:
        return []
    raw = []
    for t, c in pts:
        if raw and raw[-1][1] == c:
            continue
        raw.append((t, c))

    segs = []
    for i, (t, c) in enumerate(raw):
        start = 0.0 if i == 0 else t
        end = total_end if i == len(raw) - 1 else None
        segs.append([start, end, c])
    for i in range(len(segs) - 1):
        segs[i][1] = segs[i + 1][0]
    segs = [s for s in segs if s[1] > s[0]]
    return [(s[0], s[1], s[2]) for s in segs]


# ─── рендер ──────────────────────────────────────────────────────────────────

import struct
import zlib

_DIGITS = {
    "0": ["01110", "10001", "10011", "10101", "11001", "10001", "01110"],
    "1": ["00100", "01100", "00100", "00100", "00100", "00100", "01110"],
    "2": ["01110", "10001", "00001", "00010", "00100", "01000", "11111"],
    "3": ["11111", "00010", "00100", "00010", "00001", "10001", "01110"],
    "4": ["00010", "00110", "01010", "10010", "11111", "00010", "00010"],
    "5": ["11111", "10000", "11110", "00001", "00001", "10001", "01110"],
    "6": ["00110", "01000", "10000", "11110", "10001", "10001", "01110"],
    "7": ["11111", "00001", "00010", "00100", "01000", "01000", "01000"],
    "8": ["01110", "10001", "10001", "01110", "10001", "10001", "01110"],
    "9": ["01110", "10001", "10001", "01111", "00001", "00010", "01100"],
}


def _write_png(path, w, h, rgba):
    def chunk(typ, data):
        return (struct.pack(">I", len(data)) + typ + data +
                struct.pack(">I", zlib.crc32(typ + data) & 0xffffffff))

    raw = bytearray()
    stride = w * 4
    for y in range(h):
        raw.append(0)
        raw += rgba[y * stride:(y + 1) * stride]
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)))
        f.write(chunk(b"IDAT", zlib.compress(bytes(raw), 9)))
        f.write(chunk(b"IEND", b""))


def corner_xy_num(corner, width, height, box, margin):
    if corner == "tr":
        return width - box - margin, margin
    if corner == "tl":
        return margin, margin
    if corner == "br":
        return width - box - margin, height - box - margin
    if corner == "bl":
        return margin, height - box - margin
    sys.exit(f"Неизвестный угол: {corner}")


def render_frame(path, number, width, height, box, ox, oy):
    buf = bytearray(width * height * 4)
    for py in range(oy, oy + box):
        base = (py * width + ox) * 4
        for k in range(box):
            i = base + k * 4
            buf[i] = buf[i + 1] = buf[i + 2] = buf[i + 3] = 255
    s = str(number)
    by_height = int(box * 0.55) // 7
    by_width = int(box * 0.8) // (6 * len(s) - 1)
    scale = max(1, min(by_height, by_width))
    dw, dh, gap = 5 * scale, 7 * scale, scale
    total_w = len(s) * dw + (len(s) - 1) * gap
    x0 = ox + (box - total_w) // 2
    y0 = oy + (box - dh) // 2
    for ci, ch in enumerate(s):
        glyph = _DIGITS.get(ch)
        if not glyph:
            continue
        gx = x0 + ci * (dw + gap)
        for ry in range(7):
            row = glyph[ry]
            for rx in range(5):
                if row[rx] != "1":
                    continue
                for yy in range(scale):
                    py = y0 + ry * scale + yy
                    for xx in range(scale):
                        px = gx + rx * scale + xx
                        idx = (py * width + px) * 4
                        buf[idx] = buf[idx + 1] = buf[idx + 2] = 0
                        buf[idx + 3] = 255
    _write_png(path, width, height, bytes(buf))


def frame_counts(timeline, total_end, fps):
    counts = []
    prev_frame = 0
    n = len(timeline)
    for i, (_, end, _) in enumerate(timeline):
        end_frame = round(total_end * fps) if i == n - 1 else round(end * fps)
        counts.append(max(end_frame - prev_frame, 1))
        prev_frame = end_frame
    return counts


def _encode_clip(png, nframes, fps, out_path):
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-loop", "1", "-framerate", str(fps), "-i", png,
        "-frames:v", str(nframes),
        "-c:v", "qtrle", "-pix_fmt", "argb",
        out_path,
    ], check=True)


def _im_bin():
    return shutil.which("magick") or shutil.which("convert")


def _cyrillic_font():
    for c in ("/System/Library/Fonts/Supplemental/Arial.ttf",
              "/Library/Fonts/Arial.ttf",
              "/System/Library/Fonts/HelveticaNeue.ttc"):
        if os.path.exists(c):
            return c
    return None


_GRAVITY = {"tr": "NorthEast", "tl": "NorthWest",
            "br": "SouthEast", "bl": "SouthWest"}


def compute_num_pointsize(args, max_len):
    magick = _im_bin()
    font = _cyrillic_font()
    fontargs = ["-font", font] if font else []
    pad = max(8, args.box // 10)
    inner = args.box - 2 * pad
    ref = 100
    out = subprocess.run(
        [magick, "-background", "white", "-fill", "black", *fontargs,
         "-pointsize", str(ref), f"label:{'0' * max_len}",
         "-format", "%wx%h", "info:"],
        capture_output=True, text=True, check=True).stdout.strip().lower()
    w, h = (int(x) for x in out.split("x"))
    scale = min(inner / w, inner / h) * 0.92
    return max(8, int(ref * scale))


def _text_block(text, fontargs, area_w, area_h):
    return ["(", "-background", "white", "-fill", "black", *fontargs,
            "-gravity", "center", "-size", f"{area_w}x{area_h}",
            f"caption:{text}", "-trim", "+repage",
            "-bordercolor", "white", "-border", "26",
            "-bordercolor", "none", "-border", "0x14", ")"]


def render_frame_im(path, cell, args):
    magick = _im_bin()
    font = _cyrillic_font()
    fontargs = ["-font", font] if font else []
    grav = _GRAVITY[args.corner]
    box = args.box

    cmd = [magick, "-size", f"{args.width}x{args.height}", "xc:none"]
    if args._num_ps:
        number = ["(", "-size", f"{box}x{box}", "xc:white", *fontargs,
                  "-fill", "black", "-gravity", "center",
                  "-pointsize", str(args._num_ps), "-annotate", "+0+0", str(cell),
                  ")"]
    else:
        pad = max(8, box // 10)
        inner = box - 2 * pad
        number = ["(", "-background", "white", "-fill", "black", *fontargs,
                  "-gravity", "center", "-size", f"{inner}x{inner}",
                  f"label:{cell}", "-bordercolor", "white", "-border", str(pad), ")"]
    cmd += number + ["-gravity", grav,
                     "-geometry", f"+{args.margin}+{args.margin}", "-composite"]
    if args._with_text:
        tw = int(args.width * 0.82)
        ta = args._cell_text.get(cell)
        tb = args._cell_text_b.get(cell)
        blocks = []
        if ta:
            blocks.append(_text_block(ta, fontargs, tw, int(args.height * 0.40)))
        if tb:
            blocks.append(_text_block(tb, fontargs, tw, int(args.height * 0.28)))
        if blocks:
            stack = ["("]
            for b in blocks:
                stack += b
            stack += ["-background", "none", "-gravity", "center", "-append", ")"]
            cmd += stack + ["-gravity", "center", "-geometry", "+0+0", "-composite"]
    cmd += [path]
    subprocess.run(cmd, check=True)


def build_frame_png(png, cell, args):
    if _im_bin():
        render_frame_im(png, cell, args)
    else:
        render_frame(png, cell, args.width, args.height, args.box,
                     *corner_xy_num(args.corner, args.width, args.height,
                                    args.box, args.margin))


def render(timeline, total_end, args):
    fps = args.fps
    counts = frame_counts(timeline, total_end, fps)
    tmpdir = tempfile.mkdtemp(prefix="celloverlay_")
    try:
        clip_list = []
        n = len(timeline)
        for i, (_, _, cell) in enumerate(timeline):
            png = os.path.join(tmpdir, f"f{i}.png")
            build_frame_png(png, cell, args)
            clip = os.path.join(tmpdir, f"c{i}.mov")
            _encode_clip(png, counts[i], fps, clip)
            clip_list.append(clip)
            print(f"  сегмент {i + 1}/{n}: ячейка {cell}, {counts[i]} кадров")

        list_path = os.path.join(tmpdir, "clips.txt")
        with open(list_path, "w", encoding="utf-8") as f:
            for c in clip_list:
                f.write(f"file '{c}'\n")
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", list_path,
            "-c", "copy", args.out,
        ], check=True)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    print(f"\nГотово: {args.out}")


def render_split(timeline, total_end, args):
    """Каждый блок — отдельный .mov с именем {row_number}.mov + манифест."""
    fps = args.fps
    counts = frame_counts(timeline, total_end, fps)
    out_dir = args.out_dir
    os.makedirs(out_dir, exist_ok=True)
    n = len(timeline)
    manifest = [("file", "cell_row", "start", "end", "duration", "frames")]
    skipped = 0
    rendered = 0
    for i, (start, end, cell) in enumerate(timeline):
        # Имя файла — просто номер строки, как в старом скрипте (1.jpg → 1.mov).
        name = f"{cell}.mov"
        clip = os.path.join(out_dir, name)

        # Пропускаем уже готовый клип (повторный запуск).
        if os.path.isfile(clip):
            dur = counts[i] / fps
            manifest.append((name, str(cell), fmt_tc(start), fmt_tc(end),
                             f"{dur:.3f}", str(counts[i])))
            skipped += 1
            continue

        png = os.path.join(out_dir, f".tmp_{i}.png")
        build_frame_png(png, cell, args)
        _encode_clip(png, counts[i], fps, clip)
        os.remove(png)
        dur = counts[i] / fps
        manifest.append((name, str(cell), fmt_tc(start), fmt_tc(end),
                         f"{dur:.3f}", str(counts[i])))
        rendered += 1
        print(f"  [{i + 1}/{n}] строка {cell} | "
              f"{fmt_tc(start)}–{fmt_tc(end)} | {dur:.2f}с → {name}")

    man_path = os.path.join(out_dir, "manifest.csv")
    with open(man_path, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(manifest)
    if skipped:
        print(f"  Пропущено (уже есть): {skipped}")
    print(f"\nГотово: {rendered} новых блоков в {out_dir}\nМанифест: {man_path}")


# ─── вспомогательное ─────────────────────────────────────────────────────────

def fmt_tc(sec):
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def dump_timeline(timeline):
    print(f"{'ячейка':>7} | {'начало':>12} | {'конец':>12}")
    print("-" * 40)
    for start, end, cell in timeline:
        print(f"{cell:>7} | {fmt_tc(start):>12} | {fmt_tc(end):>12}")
    print(f"\nВсего сегментов: {len(timeline)}")


def _srt_tc(sec):
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    ms = int(round((sec - int(sec)) * 1000))
    if ms == 1000:
        s += 1
        ms = 0
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(timeline, path, cell_text=None, cell_text_b=None):
    with open(path, "w", encoding="utf-8") as f:
        for i, (start, end, cell) in enumerate(timeline, 1):
            body = str(cell)
            if cell_text:
                ta = cell_text.get(cell)
                if ta:
                    body = f"{cell}: {ta}"
                tb = cell_text_b.get(cell) if cell_text_b else None
                if tb:
                    body += f"\n{tb}"
            f.write(f"{i}\n{_srt_tc(start)} --> {_srt_tc(end)}\n{body}\n\n")
    print(f"\nГотово: {path} ({len(timeline)} записей)")


def parse_size(s):
    m = re.match(r"^\s*(\d+)\s*[xX]\s*(\d+)\s*$", s)
    if not m:
        sys.exit(f"Некорректный --size: {s} (ожидается напр. 1920x1080)")
    return int(m.group(1)), int(m.group(2))


def ask_path(prompt):
    while True:
        raw = input(prompt).strip()
        if (raw.startswith("'") and raw.endswith("'")) or \
           (raw.startswith('"') and raw.endswith('"')):
            raw = raw[1:-1]
        path = raw.replace("\\ ", " ").strip()
        if not path:
            print("  Пусто. Введите путь к файлу.")
            continue
        path = os.path.expanduser(path)
        if not os.path.isfile(path):
            print(f"  Файл не найден: {path}")
            continue
        return path


def ask_mode():
    print("Шаг 3. Что сделать?")
    print("  1 — видео-оверлей .mov, один файл")
    print("  2 — видео-оверлей .mov, отдельный клип на каждый блок")
    print("  3 — субтитры .srt с номерами блоков (без рендера видео)")
    mapping = {"1": "mov", "2": "split", "3": "srt"}
    while True:
        choice = input("  Выбор [1/2/3]: ").strip()
        if choice in mapping:
            return mapping[choice]
        print("  Введите 1, 2 или 3.")


def ask_yes_no(prompt, default=False):
    d = "Y/n" if default else "y/N"
    while True:
        ans = input(f"{prompt} [{d}]: ").strip().lower()
        if not ans:
            return default
        if ans in ("y", "yes", "д", "да"):
            return True
        if ans in ("n", "no", "н", "нет"):
            return False


def _find_transcript(voiceover_dir):
    """Авто-поиск расшифровки в папке voiceover/: сначала .srt, потом .txt."""
    for ext in ("*.srt", "*.txt"):
        matches = sorted(glob.glob(os.path.join(voiceover_dir, ext)))
        if matches:
            return matches[-1]
    return None


def _process(args, mode):
    """Общий финальный этап: выравнивание + рендер."""
    if not shutil.which("ffmpeg") and mode in ("mov", "split") and not args.dump_timeline:
        sys.exit("ffmpeg не найден в PATH.")

    cells = parse_csv(args.csv, args.col_a, args.col_b)
    segments = parse_transcript(args.transcript, args.fps_tc)
    total_end = max(e for _, e, _ in segments)

    tr_tokens = build_transcript_tokens(segments)
    sc_tokens = build_script_tokens(cells)
    if not tr_tokens:
        sys.exit("В расшифровке нет слов после нормализации.")
    if not sc_tokens:
        sys.exit("В сценарии нет слов после нормализации.")

    args._cell_text = {r: a for r, a, _ in cells}
    args._cell_text_b = {r: b for r, a, b in cells}

    timed = align(tr_tokens, sc_tokens)
    timeline = build_timeline(timed, total_end)
    if not timeline:
        sys.exit("Не удалось построить таймлайн (выравнивание пустое).")

    print(f"Ячеек: {len(cells)} | сегментов расшифровки: {len(segments)} | "
          f"длительность: {fmt_tc(total_end)}")
    matched = sorted({c for _, _, c in timeline})
    print(f"Сопоставлено ячеек: {len(matched)} из {len(cells)}")

    if args.dump_timeline:
        dump_timeline(timeline)
        return

    args._num_ps = None
    if mode in ("mov", "split") and _im_bin():
        max_len = max(len(str(c)) for _, _, c in timeline)
        args._num_ps = compute_num_pointsize(args, max_len)

    if mode == "srt":
        srt_path = args.srt or (
            re.sub(r"\.(mov|mp4|mxf)$", "", args.out, flags=re.I) + ".srt")
        write_srt(timeline, srt_path,
                  cell_text=args._cell_text if args._with_text else None,
                  cell_text_b=args._cell_text_b if args._with_text else None)
    elif mode == "split":
        render_split(timeline, total_end, args)
    else:
        render(timeline, total_end, args)


def main():
    # ── Режим пайплайна: PROJECT_NAME задан из веб-интерфейса ────────────────
    env_project = os.getenv("PROJECT_NAME", "").strip()
    if env_project:
        from path_utils import get_data_dir
        data_dir = get_data_dir(__file__)
        project_dir = os.path.join(str(data_dir), env_project)
        db_dir = os.path.join(project_dir, "database")
        voiceover_dir = os.path.join(project_dir, "voiceover")

        # CSV: последний input_gdoc*.csv
        csv_candidates = sorted(glob.glob(os.path.join(db_dir, "input_gdoc*.csv")))
        if not csv_candidates:
            sys.exit(
                f"❌ CSV не найден в {db_dir}\n"
                "   Сначала запустите «Парсинг Google таблицы»."
            )
        csv_path = csv_candidates[-1]

        # Расшифровка: TRANSCRIPT_FILE или авто-поиск в voiceover/
        transcript_path = os.getenv("TRANSCRIPT_FILE", "").strip()
        if not transcript_path or not os.path.isfile(transcript_path):
            transcript_path = _find_transcript(voiceover_dir)
        if not transcript_path or not os.path.isfile(transcript_path):
            sys.exit(
                f"❌ Расшифровка озвучки не найдена в {voiceover_dir}\n"
                "   Положите .srt или .txt с таймкодами в папку voiceover/ проекта\n"
                "   или задайте переменную среды TRANSCRIPT_FILE=<путь>."
            )

        out_dir = os.path.join(project_dir, "placeholders_xml")

        print("=== XML ПЛЕЙСХОЛДЕРЫ (оверлей с номерами ячеек) ===")
        print(f"  Проект:      {env_project}")
        print(f"  CSV:         {os.path.basename(csv_path)}")
        print(f"  Расшифровка: {os.path.basename(transcript_path)}")
        print(f"  Выход:       {out_dir}")

        import types
        args = types.SimpleNamespace(
            csv=csv_path,
            transcript=transcript_path,
            out=os.path.join(out_dir, "overlay.mov"),
            out_dir=out_dir,
            srt=None,
            with_text=False,
            _with_text=False,
            col_a=None,
            col_b=None,
            width=1920, height=1080,
            fps=25.0,
            fps_tc=25.0,
            corner="bl",
            box=80,
            margin=40,
            dump_timeline=False,
            _num_ps=None,
        )
        _process(args, mode="split")
        return

    # ── Интерактивный / CLI режим ─────────────────────────────────────────────
    ap = argparse.ArgumentParser(description="Генератор оверлея с номером ячейки.")
    ap.add_argument("--csv", help="CSV-сценарий (если не задан — спросит в терминале)")
    ap.add_argument("--transcript", help="Расшифровка .srt или .txt (если не задана — спросит)")
    ap.add_argument("--format", choices=["mov", "split", "srt"], default=None,
                    help="mov — один .mov; split — .mov на каждый блок; "
                         "srt — субтитры с номерами. Если не задан — спросит.")
    ap.add_argument("--out", default="overlay.mov", help="Выходной .mov (один файл)")
    ap.add_argument("--out-dir", default=None,
                    help="Папка для посегментного рендера: каждый блок — отдельный "
                         ".mov со своим хроном + manifest.csv")
    ap.add_argument("--srt", default=None, help="Путь выходного .srt (для format=srt)")
    ap.add_argument("--with-text", dest="with_text", action="store_true", default=None,
                    help="Добавлять текст ячейки. Если не задано — спросит.")
    ap.add_argument("--no-text", dest="with_text", action="store_false",
                    help="Не добавлять текст ячейки (только номер).")
    ap.add_argument("--col-a", "--text-col", dest="col_a", default=None)
    ap.add_argument("--col-b", dest="col_b", default=None)
    ap.add_argument("--size", default="1920x1080")
    ap.add_argument("--fps", type=float, default=25.0)
    ap.add_argument("--fps-tc", type=float, default=25.0)
    ap.add_argument("--corner", default="bl", choices=["tr", "tl", "br", "bl"])
    ap.add_argument("--box", type=int, default=80)
    ap.add_argument("--margin", type=int, default=40)
    ap.add_argument("--dump-timeline", action="store_true")
    args = ap.parse_args()
    args.width, args.height = parse_size(args.size)

    if not args.csv:
        print("Шаг 1. Путь к CSV-сценарию (можно перетащить файл в терминал):")
        args.csv = ask_path("  CSV: ")
    if not args.transcript:
        print("Шаг 2. Путь к расшифровке (.srt или .txt — перетащите файл):")
        args.transcript = ask_path("  Расшифровка: ")

    mode = args.format
    if mode is None:
        if args.out_dir:
            mode = "split"
        elif args.srt:
            mode = "srt"
        elif sys.stdin.isatty() and not args.dump_timeline:
            mode = ask_mode()
        else:
            mode = "mov"

    with_text = args.with_text
    if with_text is None and not args.dump_timeline:
        if sys.stdin.isatty():
            with_text = ask_yes_no("Шаг 4. Добавлять текст ячейки?", default=False)
        else:
            with_text = False
    args._with_text = bool(with_text)

    if args._with_text and mode in ("mov", "split") and not _im_bin():
        print("⚠️  ImageMagick не найден — текст отключён, будет только номер.")
        args._with_text = False

    if mode == "split" and not args.out_dir:
        args.out_dir = "overlay_blocks"

    _process(args, mode)


if __name__ == "__main__":
    main()
