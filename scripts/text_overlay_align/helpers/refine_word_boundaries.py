"""Final precision pass: re-align every resolved row's chosen span against a
GENEROUS local window of words (not just the one segment it was matched
against), so the boundary can be trimmed exactly even when a CSV row's text
is longer than the single segment it was found in.

Why this is needed: match_csv.py aligns each row against one segment's word
list. When that row's text is LONGER than the segment (i.e. the segment only
covers PART of the row -- the rest belongs to a neighboring row), rapidfuzz's
partial_ratio_alignment can't trim a string against something shorter than
itself, so it falls back to the segment's whole (untrimmed) span. That span
can include words that actually belong to the PREVIOUS or NEXT CSV row. This
pass re-aligns against segment +/- a time margin pulled from the GLOBAL word
list, which is almost always long enough for the target to fit inside and
get trimmed to its real word boundaries.

Usage:
    uv run helpers/refine_word_boundaries.py --segments work/segments.json \
        --matches work/matches.json [--margin 6.0] [--out work/matches.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rapidfuzz import fuzz

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from helpers.model import Segment
from helpers.match_csv import build_word_index


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--segments", default="work/segments.json")
    ap.add_argument("--matches", default="work/matches.json")
    ap.add_argument("--margin", type=float, default=6.0, help="seconds of extra context pulled in on each side")
    ap.add_argument("--out", default=None, help="defaults to overwriting --matches")
    args = ap.parse_args()

    segments = [Segment.from_dict(d) for d in json.loads(Path(args.segments).read_text(encoding="utf-8"))]
    global_words = []
    for s in segments:
        if s.kind != "speech":
            continue
        for w in s.words:
            global_words.append({"text": w.text.strip(), "start": w.start, "end": w.end})
    global_words.sort(key=lambda w: w["start"])

    if not global_words:
        print("No word-level data in segments.json -- nothing to refine.")
        return

    matches = json.loads(Path(args.matches).read_text(encoding="utf-8"))

    n_refined = 0
    n_unchanged = 0
    n_skipped = 0
    for row in matches:
        if row["unmatched"]:
            continue
        cand = row["candidates"][row["chosen_index"]]
        target = row["text"]

        # A candidate whose matched text is ALREADY close in length to the
        # target was a clean, complete, correctly-bounded match to begin
        # with (no cross-row contamination to trim) -- widening the search
        # window for it is pure risk, not benefit. This matters most for
        # short, exact-repeat lines ("Сжечь его." x3 seconds apart): a wide
        # window spans multiple identical repeats, and alignment can't tell
        # them apart, so it can silently jump the boundary to the WRONG
        # repeat. Only refine candidates that show signs of truncation/
        # contamination (a real length mismatch against the target).
        if abs(len(cand["text"]) - len(target)) <= 3:
            n_unchanged += 1
            continue

        lo, hi = cand["start"] - args.margin, cand["end"] + args.margin
        window = [w for w in global_words if w["end"] > lo and w["start"] < hi]
        if not window:
            n_skipped += 1
            continue

        joined, offsets = build_word_index(window)
        if len(target) > len(joined):
            n_skipped += 1
            continue

        align = fuzz.partial_ratio_alignment(target.lower(), joined.lower())
        if align.dest_end <= align.dest_start:
            n_skipped += 1
            continue

        w_start_idx = next(i for i, (s, e) in enumerate(offsets) if e > align.dest_start)
        w_end_idx = next(i for i in range(len(offsets) - 1, -1, -1) if offsets[i][0] < align.dest_end)
        new_start = window[w_start_idx]["start"]
        new_end = window[w_end_idx]["end"]

        if abs(new_start - cand["start"]) > 1e-6 or abs(new_end - cand["end"]) > 1e-6:
            cand["start"], cand["end"] = new_start, new_end
            cand["text"] = joined[offsets[w_start_idx][0] : offsets[w_end_idx][1]].strip()
            cand["score"] = align.score
            n_refined += 1
        else:
            n_unchanged += 1

    out_path = Path(args.out or args.matches)
    out_path.write_text(json.dumps(matches, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Refined {n_refined} rows, {n_unchanged} already exact, {n_skipped} skipped (no window/target too long) -> {out_path}")


if __name__ == "__main__":
    main()
