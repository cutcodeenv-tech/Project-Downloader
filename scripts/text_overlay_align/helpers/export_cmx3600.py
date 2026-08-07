"""Generate a CMX3600 EDL (audio-only, AA track) from work/edl.json for import
into DaVinci Resolve: File -> Import -> Timeline, then relink media to the
original (uncut) source audio file using the reel name / "FROM CLIP NAME" comment.

Usage:
    uv run helpers/export_cmx3600.py <source_audio> --edl work/edl.json \
        [--fps 25] [--title "dense edit"] [--out out/dense.edl]
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def seconds_to_tc(t: float, fps: int) -> str:
    total_frames = round(t * fps)
    frames = total_frames % fps
    total_seconds = total_frames // fps
    s = total_seconds % 60
    m = (total_seconds // 60) % 60
    h = (total_seconds // 3600)
    return f"{h:02d}:{m:02d}:{s:02d}:{frames:02d}"


def reel_name(source: Path) -> str:
    name = re.sub(r"[^A-Za-z0-9]", "", source.stem).upper()
    return (name or "SOURCE")[:20]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("--edl", default="work/edl.json")
    ap.add_argument("--fps", type=int, default=25)
    ap.add_argument("--title", default="text-overlay-align dense edit")
    ap.add_argument("--out", default="out/dense.edl")
    args = ap.parse_args()

    source = Path(args.source)
    edl = json.loads(Path(args.edl).read_text(encoding="utf-8"))
    reel = reel_name(source)

    lines = [f"TITLE: {args.title}", "FCM: NON-DROP FRAME", ""]

    for i, entry in enumerate(edl, start=1):
        src_in = seconds_to_tc(entry["old_start"], args.fps)
        src_out = seconds_to_tc(entry["old_end"], args.fps)
        rec_in = seconds_to_tc(entry["new_start"], args.fps)
        rec_out = seconds_to_tc(entry["new_end"], args.fps)
        lines.append(f"{i:03d}  {reel:<8} AA    C        {src_in} {src_out} {rec_in} {rec_out}")
        lines.append(f"* FROM CLIP NAME: {source.name}")
        lines.append(f"* LINE {entry['line_no']}: {entry['text']}")
        lines.append("")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote CMX3600 EDL ({len(edl)} events, reel={reel}, fps={args.fps}) -> {out_path}")
    print("Import in Resolve: File -> Import -> Timeline, then relink media to the original source audio.")


if __name__ == "__main__":
    main()
