#!/usr/bin/env python3
"""Черновой таймлайн проекта в формате FCP7 XML (xmeml v4) — его импортируют
и Premiere Pro (File → Import), и DaVinci Resolve (File → Import → Timeline).

Раскладка, 1920x1080, 25 fps (как у текстового оверлея):
  A1 — озвучка целиком с нуля;
  V1 — материал строки сценария (видео, плёнка, статья, картинки) на её
       отрезке озвучки; несколько материалов делят отрезок поровну;
  V2 — плашка источника над своим YouTube-видео;
  V3 — карточки текстового оверлея (по клипу на строку).

Отрезок строки берётся из таймингов оверлея (placeholders_xml/_work/
timing.json): от начала строки до начала следующей — так же, как держит
карточку сам оверлей. Если таймингов нет (озвучку ещё не сопоставили),
строки идут подряд по SECONDS_PER_ITEM секунд на материал — всё равно
быстрее, чем раскладывать руками.

Ручной запуск: python3 timeline_export.py <папка проекта>
"""

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote
from xml.sax.saxutils import escape

from path_utils import project_subdir
from project_review import collect

FPS = 25
WIDTH, HEIGHT = 1920, 1080
SECONDS_PER_ITEM = 4.0
STILL_DURATION_FRAMES = FPS * 60 * 60  # «бесконечная» длина исходника для картинок

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}
VIDEO_EXT = {".mp4", ".m4v", ".mov", ".mkv", ".webm"}
AUDIO_EXT = (".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg")


def probe_seconds(path: Path):
    """Длина медиафайла через ffprobe; None, если узнать не удалось."""
    if not shutil.which("ffprobe"):
        return None
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=30,
        ).stdout.strip()
        return float(out) if out and out != "N/A" else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def frames(seconds: float) -> int:
    return round(seconds * FPS)


class Timeline:
    def __init__(self):
        self.tracks = {"V1": [], "V2": [], "V3": [], "A1": []}
        self._file_ids = {}
        self._clip_n = 0
        self._durations = {}

    def source_frames(self, path: Path) -> int:
        if path.suffix.lower() in IMAGE_EXT:
            return STILL_DURATION_FRAMES
        if path not in self._durations:
            seconds = probe_seconds(path)
            self._durations[path] = frames(seconds) if seconds else None
        return self._durations[path] or STILL_DURATION_FRAMES

    def add(self, track: str, path: Path, start: int, end: int, source_in: int = 0) -> None:
        if end <= start:
            return
        available = self.source_frames(path) - source_in
        end = min(end, start + max(available, 0))
        if end <= start:
            return
        self.tracks[track].append((path, start, end, source_in))

    def _file_xml(self, path: Path, kind: str) -> str:
        if path in self._file_ids:
            return f'<file id="{self._file_ids[path]}"/>'
        file_id = f"file-{len(self._file_ids) + 1}"
        self._file_ids[path] = file_id
        url = "file://localhost" + quote(str(path.resolve()))
        media = (
            "<audio><samplecharacteristics><depth>16</depth><samplerate>48000</samplerate>"
            "</samplecharacteristics><channelcount>2</channelcount></audio>"
            if kind == "audio" else
            f"<video><samplecharacteristics><width>{WIDTH}</width><height>{HEIGHT}</height>"
            f"</samplecharacteristics></video>"
        )
        return (
            f'<file id="{file_id}"><name>{escape(path.name)}</name><pathurl>{escape(url)}</pathurl>'
            f"<rate><timebase>{FPS}</timebase><ntsc>FALSE</ntsc></rate>"
            f"<duration>{self.source_frames(path)}</duration><media>{media}</media></file>"
        )

    def _clip_xml(self, path: Path, start: int, end: int, source_in: int, kind: str) -> str:
        self._clip_n += 1
        source_track = (
            "<sourcetrack><mediatype>audio</mediatype><trackindex>1</trackindex></sourcetrack>"
            if kind == "audio" else ""
        )
        return (
            f'<clipitem id="clip-{self._clip_n}"><name>{escape(path.name)}</name><enabled>TRUE</enabled>'
            f"<duration>{self.source_frames(path)}</duration>"
            f"<rate><timebase>{FPS}</timebase><ntsc>FALSE</ntsc></rate>"
            f"<start>{start}</start><end>{end}</end>"
            f"<in>{source_in}</in><out>{source_in + end - start}</out>"
            f"{self._file_xml(path, kind)}{source_track}</clipitem>"
        )

    def to_xml(self, name: str) -> str:
        total = max((end for clips in self.tracks.values() for _, _, end, _ in clips), default=0)
        rate = f"<rate><timebase>{FPS}</timebase><ntsc>FALSE</ntsc></rate>"
        video_tracks = "".join(
            "<track>" + "".join(self._clip_xml(p, s, e, i, "video") for p, s, e, i in sorted(self.tracks[t], key=lambda c: c[1])) + "</track>"
            for t in ("V1", "V2", "V3")
        )
        audio_tracks = "<track>" + "".join(
            self._clip_xml(p, s, e, i, "audio") for p, s, e, i in self.tracks["A1"]
        ) + "</track>"
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n<xmeml version="4">'
            f'<sequence id="sequence-1"><name>{escape(name)}</name><duration>{total}</duration>{rate}'
            f"<media><video><format><samplecharacteristics>{rate}<width>{WIDTH}</width><height>{HEIGHT}</height>"
            f"<pixelaspectratio>square</pixelaspectratio><fielddominance>none</fielddominance>"
            f"</samplecharacteristics></format>{video_tracks}</video>"
            f"<audio>{audio_tracks}</audio></media></sequence></xmeml>\n"
        )


def _row_spans(timing: list) -> dict:
    """{номер строки: (начало, конец)} в секундах — от начала основного дубля
    строки до начала следующей строки, как держит карточку оверлей."""
    starts = {}
    for row in timing:
        if row.get("is_duplicate"):
            continue
        base = re.sub(r"_\d+$", "", str(row["line_no"]))
        if base.isdigit():
            starts[int(base)] = float(row["start"])
    ordered = sorted(starts.items(), key=lambda kv: kv[1])
    spans = {}
    for i, (row_num, start) in enumerate(ordered):
        end = ordered[i + 1][1] if i + 1 < len(ordered) else max(float(r["end"]) for r in timing)
        spans[row_num] = (start, end)
    return spans


def _overlay_spans(timing: list) -> dict:
    """Где лежит клип оверлея каждой строки — повторяет раскладку
    render_overlay.py: клип строки начинается с её самого раннего дубля и
    длится до начала следующей строки; первый клип начинается с нуля
    (пустой «лид»), последний — до конца озвучки + 1 с."""
    groups = {}
    for row in timing:
        base = re.sub(r"_\d+$", "", str(row["line_no"]))
        if base.isdigit():
            groups.setdefault(int(base), []).append(float(row["start"]))
    order = sorted(groups, key=lambda b: min(groups[b]))
    total = max(float(r["end"]) for r in sorted(timing, key=lambda r: r["start"])[-1:]) + 1.0
    spans = {}
    for i, base in enumerate(order):
        start = 0.0 if i == 0 else min(groups[base])
        end = min(groups[order[i + 1]]) if i + 1 < len(order) else total
        spans[base] = (start, end)
    return spans


def _row_materials(block: dict) -> list:
    """Материал строки для V1 по порядку ячеек + плёнка блока (видео
    предпочтительнее картинки; если плёнка есть, фото блока отдельно не идут)."""
    film_videos = [p for p in block["filmstrips"] if p.suffix.lower() in VIDEO_EXT]
    film_images = [p for p in block["filmstrips"] if p.suffix.lower() in IMAGE_EXT]
    films = film_videos or film_images
    paths = [
        item["files"][0] for item in block["items"]
        # Фото блока уже собраны в плёнку — отдельно их не ставим.
        if item["files"] and not (films and item["category"] == "image")
    ]
    paths += films
    return [p for p in paths if p.suffix.lower() in VIDEO_EXT | IMAGE_EXT]


def build_timeline(project_dir, project_name: str = ""):
    """Пишет <проект>/01_Project_Files/<имя>_timeline.xml. Возвращает
    (путь, сводка) — сводка для вывода в терминал."""
    project_dir = Path(project_dir)
    project_name = project_name or project_dir.name
    data = collect(project_dir, project_name)
    timeline = Timeline()

    overlay_dir = project_subdir(project_dir, "placeholders_xml")
    timing_path = overlay_dir / "_work" / "timing.json"
    timing = []
    if timing_path.is_file():
        try:
            timing = json.loads(timing_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            timing = []
    spans = _row_spans(timing) if timing else {}

    cursor = 0.0
    placed_rows = unplaced_rows = 0
    for block in data["blocks"]:
        materials = _row_materials(block)
        if spans:
            if block["row"] not in spans:
                if materials:
                    unplaced_rows += 1
                continue
            start, end = spans[block["row"]]
        else:
            if not materials:
                continue
            start, end = cursor, cursor + SECONDS_PER_ITEM * len(materials)
            cursor = end
        if not materials:
            continue
        placed_rows += 1
        step = (end - start) / len(materials)
        for i, path in enumerate(materials):
            clip_start, clip_end = frames(start + i * step), frames(start + (i + 1) * step)
            timeline.add("V1", path, clip_start, clip_end)
            item = next((it for it in block["items"] if it["files"] and it["files"][0] == path), None)
            if item and item["author"]:
                timeline.add("V2", item["author"][0], clip_start, clip_end)

    # Озвучка и карточки оверлея — только когда есть тайминги.
    audio = None
    if spans:
        voiceover_dir = project_subdir(project_dir, "voiceover")
        audio_files = sorted(p for p in voiceover_dir.glob("*") if p.suffix.lower() in AUDIO_EXT)
        if audio_files:
            audio = audio_files[-1]
            timeline.add("A1", audio, 0, timeline.source_frames(audio))
        clips = {}
        for clip in (overlay_dir / "overlay_clips").glob("*.mov"):
            if clip.stem.isdigit():
                clips[int(clip.stem)] = clip
        for row_num, (start, end) in _overlay_spans(timing).items():
            if row_num in clips:
                timeline.add("V3", clips[row_num], frames(start), frames(end))

    out_dir = project_dir / "01_Project_Files"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{project_name}_timeline.xml"
    out_path.write_text(timeline.to_xml(f"{project_name} — черновой монтаж"), encoding="utf-8")

    summary = {
        "rows": placed_rows,
        "unplaced_rows": unplaced_rows,
        "clips": len(timeline.tracks["V1"]),
        "plaques": len(timeline.tracks["V2"]),
        "overlay": len(timeline.tracks["V3"]),
        "audio": audio.name if audio else "",
        "by_timing": bool(spans),
    }
    return out_path, summary


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Использование: python3 timeline_export.py <папка проекта>")
        sys.exit(1)
    path, info = build_timeline(Path(sys.argv[1]).expanduser())
    print(f"✓ {path}\n  {info}")
