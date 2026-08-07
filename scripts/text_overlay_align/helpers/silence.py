"""Detect silence gaps in an audio file via ffmpeg's silencedetect filter and
merge them into an existing segments.json (from parse_transcript.py) as
kind="pause" Segments, splitting/trimming so they never overlap speech.

Usage:
    uv run helpers/silence.py <audio_file> --segments work/segments.json \
        [--noise -30dB] [--min-duration 0.2] [--out work/segments.json]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from helpers.model import Segment

SILENCE_START_RE = re.compile(r"silence_start:\s*([0-9.]+)")
SILENCE_END_RE = re.compile(r"silence_end:\s*([0-9.]+)")


def detect_silence(audio_path: Path, noise: str, min_duration: float) -> list[tuple[float, float]]:
    cmd = [
        "ffmpeg", "-i", str(audio_path),
        "-af", f"silencedetect=noise={noise}:d={min_duration}",
        "-f", "null", "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    log = proc.stderr

    gaps: list[tuple[float, float]] = []
    pending_start: float | None = None
    for line in log.splitlines():
        m_start = SILENCE_START_RE.search(line)
        if m_start:
            pending_start = float(m_start.group(1))
            continue
        m_end = SILENCE_END_RE.search(line)
        if m_end and pending_start is not None:
            gaps.append((pending_start, float(m_end.group(1))))
            pending_start = None
    return gaps


def merge_into_segments(segments: list[Segment], gaps: list[tuple[float, float]]) -> list[Segment]:
    """Add detected silence gaps as new pause Segments, trimmed so they never
    overlap any EXISTING segment of any kind (transcript timing always wins,
    including transcript-marked pauses/breaths -- this only fills in gaps the
    transcript left uncovered)."""
    existing = sorted(segments, key=lambda s: s.start)

    new_pauses: list[Segment] = []
    for gap_start, gap_end in gaps:
        cur_start = gap_start
        for s in existing:
            if s.end <= cur_start or s.start >= gap_end:
                continue
            if s.start > cur_start:
                new_pauses.append(Segment(kind="pause", start=cur_start, end=min(s.start, gap_end)))
            cur_start = max(cur_start, s.end)
            if cur_start >= gap_end:
                break
        if cur_start < gap_end:
            new_pauses.append(Segment(kind="pause", start=cur_start, end=gap_end))

    merged = existing + new_pauses
    merged.sort(key=lambda s: s.start)
    return merged


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("--segments", default="work/segments.json")
    ap.add_argument("--noise", default="-30dB")
    ap.add_argument("--min-duration", type=float, default=0.2)
    ap.add_argument("--out", default=None, help="defaults to overwriting --segments")
    args = ap.parse_args()

    seg_path = Path(args.segments)
    segments = [Segment.from_dict(d) for d in json.loads(seg_path.read_text(encoding="utf-8"))]

    gaps = detect_silence(Path(args.audio), args.noise, args.min_duration)
    print(f"Detected {len(gaps)} silence gaps (noise={args.noise}, min_duration={args.min_duration}s)")

    merged = merge_into_segments(segments, gaps)

    out_path = Path(args.out or args.segments)
    out_path.write_text(json.dumps([s.to_dict() for s in merged], ensure_ascii=False, indent=2), encoding="utf-8")
    n_pause = sum(1 for s in merged if s.kind == "pause")
    print(f"Wrote {len(merged)} segments ({n_pause} pause) -> {out_path}")


if __name__ == "__main__":
    main()
