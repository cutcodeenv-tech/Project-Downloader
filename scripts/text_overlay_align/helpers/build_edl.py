"""Build a dense (pause/breath/retake-free) EDL from work/matches.json.

Assembly order = CSV line_no order (the script's intended sequence), NOT raw
chronological order in the original recording -- line_no is the source of
truth for what the final video says.

For each row's chosen segment [start, end] (original-recording time):
  1. Extend by --pad (default 0.05s, clamped to [0.03, 0.10]) on both sides,
     but never past the boundary of another SPEECH segment (word-boundary-safe:
     padding may only eat into pause/breath/silence, never into a neighbor's
     word).
  2. Place segments back-to-back in the new (dense) timeline in line_no order.
  3. Record a fade_in/fade_out (default 0.025s, clamped to [0.02, 0.03]) for
     build_audio.py to apply at each cut.

Refuses to run if matches.json has unresolved ambiguous or unmatched rows
(use --force to proceed anyway, dropping unmatched rows and using the
tentative pick for ambiguous ones).

Usage:
    uv run helpers/build_edl.py --segments work/segments.json --matches work/matches.json \
        [--pad 0.05] [--fade 0.025] [--out work/edl.json] [--force]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from helpers.model import Segment


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--segments", default="work/segments.json")
    ap.add_argument("--matches", default="work/matches.json")
    ap.add_argument("--pad", type=float, default=0.05)
    ap.add_argument("--fade", type=float, default=0.025)
    ap.add_argument("--min-duration", type=float, default=0.4, help="floor duration for coarse-timestamp segments that round to ~0s")
    ap.add_argument("--out", default="work/edl.json")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    pad = clamp(args.pad, 0.03, 0.10)
    fade = clamp(args.fade, 0.02, 0.03)
    min_duration = args.min_duration

    segments = [Segment.from_dict(d) for d in json.loads(Path(args.segments).read_text(encoding="utf-8"))]
    matches = json.loads(Path(args.matches).read_text(encoding="utf-8"))

    unmatched = [m for m in matches if m["unmatched"]]
    ambiguous = [m for m in matches if m["ambiguous"]]
    if (unmatched or ambiguous) and not args.force:
        print(f"Refusing to build EDL: {len(unmatched)} unmatched, {len(ambiguous)} ambiguous rows in {args.matches}.")
        print("Resolve them (edit chosen_index / fix the CSV or transcript) or re-run with --force.")
        raise SystemExit(1)

    rows = [m for m in matches if not m["unmatched"]]
    rows.sort(key=lambda r: float(r["line_no"]) if r["line_no"].replace(".", "", 1).isdigit() else 0)

    all_speech = [s for s in segments if s.kind == "speech" and s.text.strip()]
    speech_ends = sorted(s.end for s in all_speech)
    speech_starts = sorted(s.start for s in all_speech)

    edl = []
    cursor = 0.0
    for row in rows:
        cand = row["candidates"][row["chosen_index"]]
        s, e = cand["start"], cand["end"]
        shared = cand.get("shared_segment", False)
        # A shared_segment's start/end is an internal split point (proportional
        # split of one continuous take across multiple CSV rows) unless it
        # coincides with the original segment's true boundary -- only pad the
        # true boundary side, never the artificial internal cut.
        pad_left = pad if (not shared or abs(s - cand.get("original_start", s)) < 1e-6) else 0.0
        pad_right = pad if (not shared or abs(e - cand.get("original_end", e)) < 1e-6) else 0.0

        # b < e / b > s (not <=/>=) so a zero-duration segment (s == e, which
        # coarse whole-second transcript timestamps produce) never treats its
        # own boundary as its neighbor's boundary.
        left_candidates = [b for b in speech_ends if b <= s and b < e]
        left_bound = max(left_candidates) if left_candidates else 0.0
        padded_start = max(s - pad_left, left_bound)

        right_candidates = [b for b in speech_starts if b >= e and b > s]
        right_bound = min(right_candidates) if right_candidates else e + pad_right
        padded_end = min(e + pad_right, right_bound)

        # Coarse (whole-second) transcript timestamps can round a short
        # utterance's start and end to the identical second, producing a
        # zero (or near-zero) duration that ffmpeg can't extract. Force a
        # floor, extending further into the available left/right bound
        # room (never past a neighboring speech segment) if the normal pad
        # alone isn't enough.
        if padded_end - padded_start < min_duration:
            deficit = min_duration - (padded_end - padded_start)
            grow_left = min(deficit / 2, padded_start - left_bound)
            grow_right = min(deficit - grow_left, right_bound - padded_end)
            grow_left = min(deficit - grow_right, padded_start - left_bound)
            padded_start -= max(0.0, grow_left)
            padded_end += max(0.0, grow_right)

        duration = padded_end - padded_start
        if duration < min_duration:
            print(f"  warning: line {row['line_no']} duration {duration:.3f}s still below floor {min_duration}s (neighbors too tight)")
        new_start = cursor
        new_end = cursor + duration
        cursor = new_end

        edl.append({
            "line_no": row["line_no"],
            "text": row["text"],
            "old_start": padded_start,
            "old_end": padded_end,
            "new_start": new_start,
            "new_end": new_end,
            "fade_in": fade,
            "fade_out": fade,
        })

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(edl, ensure_ascii=False, indent=2), encoding="utf-8")

    total_old = sum(e["old_end"] - e["old_start"] for e in edl)
    print(f"Built EDL: {len(edl)} segments, dense duration {cursor:.3f}s (from {total_old:.3f}s of source audio) -> {out_path}")


if __name__ == "__main__":
    main()
