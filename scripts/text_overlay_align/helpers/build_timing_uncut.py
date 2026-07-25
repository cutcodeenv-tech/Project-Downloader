"""Build timing.json directly from matches.json WITHOUT cutting anything --
each row's start/end is its chosen candidate's ORIGINAL position in the
source recording (no dense EDL, no padding, no fades, no timeline
compression). Use this when the audio track must stay untouched and the
overlay just needs to show each line's card at its real position in the
original recording, with nothing shown during pauses/gaps/unused retakes.

Usage:
    uv run helpers/build_timing_uncut.py --matches work/matches.json [--out work/timing.json]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--matches", default="work/matches.json")
    ap.add_argument("--out", default="work/timing.json")
    args = ap.parse_args()

    matches = json.loads(Path(args.matches).read_text(encoding="utf-8"))

    unmatched = [m for m in matches if m["unmatched"]]
    if unmatched:
        print(f"Skipping {len(unmatched)} unmatched rows (no card will be shown for them):")
        for r in unmatched:
            print(f'  line {r["line_no"]}: "{r["text"]}"')

    n_duplicates = 0
    timing = []
    for r in matches:
        if r["unmatched"]:
            continue
        cand = r["candidates"][r["chosen_index"]]
        timing.append({
            "line_no": r["line_no"],
            "text": r["text"],
            "fields": r.get("fields", {}),
            "start": cand["start"],
            "end": cand["end"],
        })

        # Discarded retakes of this SAME line: show a card at their real
        # position too, marked as a duplicate, instead of erasing them.
        for i, span in enumerate(r.get("duplicate_takes", []), start=1):
            timing.append({
                "line_no": f'{r["line_no"]}_{i}',
                "text": r["text"],
                "fields": r.get("fields", {}),
                "start": span["start"],
                "end": span["end"],
                "is_duplicate": True,
            })
            n_duplicates += 1

    timing.sort(key=lambda r: r["start"])

    # Independent per-row boundary snapping (snap_boundaries.py) can leave
    # adjacent rows overlapping by a few tenths of a second -- e.g. one side
    # of a shared pause snaps but the other doesn't, or they snap to two
    # different nearby gaps. A single narrator's lines can't really overlap,
    # so any overlap here is a snapping artifact: resolve it by meeting in
    # the middle. Iterate since resolving one pair can occasionally nudge a
    # neighbor into a new (smaller) overlap with the next one.
    n_resolved = 0
    for _ in range(3):
        changed = False
        for i in range(len(timing) - 1):
            if timing[i + 1]["start"] < timing[i]["end"]:
                mid = (timing[i]["end"] + timing[i + 1]["start"]) / 2
                timing[i]["end"] = mid
                timing[i + 1]["start"] = mid
                n_resolved += 1
                changed = True
        if not changed:
            break
    if n_resolved:
        print(f"Resolved {n_resolved} adjacent-row overlaps (snapping artifacts) by meeting in the middle")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(timing, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(timing)} rows ({n_duplicates} marked duplicate takes, original uncut timeline) -> {out_path}")


if __name__ == "__main__":
    main()
