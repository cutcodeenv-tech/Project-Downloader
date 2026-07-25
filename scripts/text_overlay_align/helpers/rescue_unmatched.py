"""Recover rows that match_csv.py left unmatched because their text spans
TWO (or more) adjacent segments and neither one alone reaches --threshold.

match_csv.py scores each segment independently; a row whose text is split
roughly half-and-half across a segment boundary gets a mediocre score from
each side and never clears the threshold on its own, even though the
combined text is a perfect match. This re-aligns each unmatched row against
a wide window of the GLOBAL word list (not one segment) around its best
below-threshold guess, which almost always covers the full row.

Usage:
    uv run helpers/rescue_unmatched.py --segments work/segments.json \
        --matches work/matches.json [--margin 10.0] [--out work/matches.json]
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
    ap.add_argument("--threshold", type=float, default=70.0)
    ap.add_argument("--margin", type=float, default=10.0)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    segments = [Segment.from_dict(d) for d in json.loads(Path(args.segments).read_text(encoding="utf-8"))]
    global_words = []
    for s in segments:
        if s.kind != "speech":
            continue
        for w in s.words:
            global_words.append({"text": w.text.strip(), "start": w.start, "end": w.end})
    global_words.sort(key=lambda w: w["start"])

    matches = json.loads(Path(args.matches).read_text(encoding="utf-8"))

    n_rescued = 0
    n_still_unmatched = 0
    for row in matches:
        if not row["unmatched"]:
            continue
        best = row.get("closest_below_threshold")
        if not best:
            n_still_unmatched += 1
            continue

        anchor_start, anchor_end = best["start"], best["end"]
        lo, hi = anchor_start - args.margin, anchor_end + args.margin
        window = [w for w in global_words if w["end"] > lo and w["start"] < hi]
        if not window:
            n_still_unmatched += 1
            continue

        joined, offsets = build_word_index(window)
        target = row["text"]
        if len(target) > len(joined):
            n_still_unmatched += 1
            continue

        align = fuzz.partial_ratio_alignment(target.lower(), joined.lower())
        if align.score < args.threshold or align.dest_end <= align.dest_start:
            n_still_unmatched += 1
            continue

        w_start_idx = next(i for i, (s, e) in enumerate(offsets) if e > align.dest_start)
        w_end_idx = next(i for i in range(len(offsets) - 1, -1, -1) if offsets[i][0] < align.dest_end)
        row["candidates"] = [{
            "start": window[w_start_idx]["start"],
            "end": window[w_end_idx]["end"],
            "score": align.score,
            "text": joined[offsets[w_start_idx][0] : offsets[w_end_idx][1]].strip(),
        }]
        row["chosen_index"] = 0
        row["ambiguous"] = False
        row["unmatched"] = False
        n_rescued += 1

    out_path = Path(args.out or args.matches)
    out_path.write_text(json.dumps(matches, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Rescued {n_rescued} rows (cross-segment matches), {n_still_unmatched} still unmatched -> {out_path}")


if __name__ == "__main__":
    main()
