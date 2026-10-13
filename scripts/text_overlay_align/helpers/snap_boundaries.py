"""Snap each row's chosen [start, end] in matches.json to the nearest real
silence<->speech transition detected via ffmpeg silencedetect.

Whole-second transcript timestamps (the "MM:SS-MM:SS" JSON shape) are only
accurate to +/-0.5s by construction (every value is rounded to the nearest
second) -- that rounding is exactly the "small offsets" a viewer notices
between when a card changes and when the line is actually spoken. This finds
the real onset/offset nearest each labeled boundary (within --tolerance,
which must cover the rounding error) and moves the boundary there.

A shared_segment split's INTERNAL cut point (the artificial boundary between
two CSV rows that share one recorded take) is never snapped -- there is no
real audio transition there, only the true outer edges
(cand["original_start"] / cand["original_end"]) are. merged_fragments spans
are true reconstructed original boundaries on both sides, so both snap.

Usage:
    uv run helpers/snap_boundaries.py <audio_file> --matches work/matches.json \
        [--tolerance 0.6] [--noise -30dB] [--min-duration 0.15] [--out work/matches.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from helpers.silence import detect_silence


def nearest(gaps: list[tuple[float, float]], t: float, want: str, tolerance: float) -> float | None:
    """want='onset' looks for a gap END near t (silence->speech transition);
    want='offset' looks for a gap START near t (speech->silence transition)."""
    best = None
    best_dist = tolerance
    for gs, ge in gaps:
        candidate = ge if want == "onset" else gs
        d = abs(candidate - t)
        if d <= best_dist:
            best_dist = d
            best = candidate
    return best


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("--matches", default="work/matches.json")
    ap.add_argument("--tolerance", type=float, default=0.6)
    ap.add_argument("--noise", default="-30dB")
    ap.add_argument("--min-duration", type=float, default=0.15)
    ap.add_argument("--out", default=None, help="defaults to overwriting --matches")
    args = ap.parse_args()

    gaps = detect_silence(Path(args.audio), args.noise, args.min_duration)
    print(f"Detected {len(gaps)} silence gaps (noise={args.noise}, min_duration={args.min_duration}s)")

    data = json.loads(Path(args.matches).read_text(encoding="utf-8"))

    n_snapped_start = 0
    n_snapped_end = 0
    for row in data:
        if row["unmatched"]:
            continue
        cand = row["candidates"][row["chosen_index"]]

        can_snap_start = True
        can_snap_end = True
        if cand.get("shared_segment"):
            can_snap_start = abs(cand["start"] - cand.get("original_start", cand["start"])) < 1e-6
            can_snap_end = abs(cand["end"] - cand.get("original_end", cand["end"])) < 1e-6

        if can_snap_start:
            snapped = nearest(gaps, cand["start"], "onset", args.tolerance)
            if snapped is not None and abs(snapped - cand["start"]) > 1e-6:
                cand["start"] = snapped
                n_snapped_start += 1

        if can_snap_end:
            snapped = nearest(gaps, cand["end"], "offset", args.tolerance)
            if snapped is not None and abs(snapped - cand["end"]) > 1e-6:
                cand["end"] = snapped
                n_snapped_end += 1

    out_path = Path(args.out or args.matches)
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Snapped {n_snapped_start} start boundaries, {n_snapped_end} end boundaries -> {out_path}")


if __name__ == "__main__":
    main()
