"""Build the dense audio track: extract each edl.json segment from the source
audio (accurate seek), apply afade in/out at the configured fade duration, then
concat (-c copy, no re-encode) since every segment is re-encoded to the same
PCM format up front.

Usage:
    uv run helpers/build_audio.py <source_audio> --edl work/edl.json [--out out/audio_dense.wav]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

SAMPLE_FMT = "pcm_s24le"
SAMPLE_RATE = "48000"


def extract_segment(source: Path, entry: dict, out_path: Path) -> None:
    dur = entry["old_end"] - entry["old_start"]
    fade_out_start = max(0.0, dur - entry["fade_out"])
    af = f"afade=t=in:st=0:d={entry['fade_in']},afade=t=out:st={fade_out_start}:d={entry['fade_out']}"
    cmd = [
        "ffmpeg", "-y",
        # -ss BEFORE -i resets each extracted clip's timestamps to start at 0.
        # Placed after -i (output/accurate seeking), afade's st= values are
        # matched against the SOURCE file's absolute timestamps, not the
        # clip-local ones -- since every fade window sits far in the past
        # relative to those absolute timestamps, afade treats the whole clip
        # as already-decayed-to-silence. (Source is WAV/PCM, so pre-input
        # seeking here is still sample-accurate, no keyframe snapping.)
        "-ss", str(entry["old_start"]),
        "-i", str(source),
        "-t", str(dur),
        "-af", af,
        "-ar", SAMPLE_RATE, "-ac", "2",
        "-c:a", SAMPLE_FMT,
        str(out_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("--edl", default="work/edl.json")
    ap.add_argument("--segments-dir", default="work/audio_segments")
    ap.add_argument("--out", default="out/audio_dense.wav")
    args = ap.parse_args()

    source = Path(args.source)
    edl = json.loads(Path(args.edl).read_text(encoding="utf-8"))

    seg_dir = Path(args.segments_dir)
    seg_dir.mkdir(parents=True, exist_ok=True)

    seg_paths = []
    for i, entry in enumerate(edl):
        p = seg_dir / f"seg_{i:04d}_line{entry['line_no']}.wav"
        extract_segment(source, entry, p)
        seg_paths.append(p)
        print(f"  [{i+1}/{len(edl)}] extracted line {entry['line_no']} ({entry['old_end']-entry['old_start']:.3f}s)")

    list_path = seg_dir / "concat_list.txt"
    with list_path.open("w", encoding="utf-8") as f:
        for p in seg_paths:
            f.write(f"file '{p.resolve()}'\n")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_path), "-c", "copy", str(out_path)]
    subprocess.run(cmd, check=True)
    print(f"Wrote dense audio track ({len(seg_paths)} segments) -> {out_path}")


if __name__ == "__main__":
    main()
