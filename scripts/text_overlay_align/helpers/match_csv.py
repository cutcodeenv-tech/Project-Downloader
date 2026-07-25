"""Match each CSV row's text to a transcript segment (helpers.model.Segment,
kind="speech") using rapidfuzz.

CSV shape: header-driven. One column's header must contain "текст"/"text"
(case-insensitive) -- that's the line matched against the transcript. Every
other column is carried through verbatim as an extra field (keyed by its
original header), EXCEPT that any line consisting solely of a URL is
stripped out of every field's value (production-notes columns routinely mix
a one-line brief with several reference links on their own lines -- those
links must never end up on an overlay card).

There is no line-number column in the real data; line_no = 1-based row
position in the CSV (script order = final assembly order).

Granularity mismatch: a CSV script is often finer-grained than the recorded
takes (e.g. two consecutive CSV lines were read as one continuous sentence
and only get transcribed as a single segment). To handle this:
  - scoring uses max(partial_ratio, token_sort_ratio) so a CSV line that is
    a SUBSTRING of a longer merged segment still matches well.
  - after picking each row's segment, any run of consecutive rows that
    resolved to the exact same segment gets that segment's duration split
    among them proportionally by character length (no word-level timing
    exists to split more precisely) -- see split_shared_segments().

Retakes/duplicates: if a row matches multiple distinct segments above
--threshold, the LAST one by time is the tentative pick, but the row is
flagged "ambiguous" and every candidate is printed for human confirmation.

Usage:
    uv run helpers/match_csv.py <csv_file> --segments work/segments.json \
        [--threshold 70] [--out work/matches.json]

Output work/matches.json:
    [
      {"line_no": "1", "text": "...", "fields": {"ТЗ-видео (архив)": "...", ...},
       "candidates": [{"start":.., "end":.., "score":.., "text":".."}, ...],
       "chosen_index": 0, "ambiguous": true/false, "unmatched": false}
      ...
    ]
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

from rapidfuzz import fuzz

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from helpers.model import Segment
from progress_ui import render_bar, StatusBoard

URL_LINE_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)


def strip_link_lines(text: str) -> str:
    """Drop any line that contains a URL (reference links live on their own
    line in this data, never mixed with real descriptive text)."""
    kept = [ln for ln in text.splitlines() if not URL_LINE_RE.search(ln) and ln.strip()]
    return "\n".join(kept).strip()


def load_csv_rows(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        rows = [r for r in reader if any(cell.strip() for cell in r)]

    if not rows:
        return []

    header = rows[0]
    text_col = next((i for i, h in enumerate(header) if "текст" in h.lower() or "text" in h.lower()), 0)

    # line_no = the row's actual position in the spreadsheet (header counts
    # as row 1), not a 1-based count of data rows -- so it matches what the
    # user sees when they open the CSV in a spreadsheet app.
    out = []
    for i, r in enumerate(rows[1:], start=2):
        r = r + [""] * (len(header) - len(r))
        fields = {}
        for j, h in enumerate(header):
            if j == text_col:
                continue
            fields[h] = strip_link_lines(r[j].strip())
        out.append({"line_no": str(i), "text": r[text_col].strip(), "fields": fields})
    return out


def fmt_time(t: float) -> str:
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def score_match(target: str, candidate: str) -> float:
    return max(fuzz.partial_ratio(target, candidate), fuzz.token_sort_ratio(target, candidate))


def build_word_index(words: list[dict]) -> tuple[str, list[tuple[int, int]]]:
    """Join word texts with an explicit single space (word text is already
    stripped by the transcript parser, so whisper's embedded leading spaces
    can't be relied on) while tracking each word's exact char range in the
    joined string, for mapping alignment offsets back to word timestamps."""
    parts = []
    offsets = []
    pos = 0
    for w in words:
        text = w["text"]
        offsets.append((pos, pos + len(text)))
        parts.append(text)
        pos += len(text) + 1
    return " ".join(parts), offsets


def align_candidate(target: str, words: list[dict]) -> dict | None:
    """Find the exact word sub-range of `words` (one segment's word list)
    that best matches `target`, instead of trusting the WHOLE segment's
    boundaries. A segment routinely contains text belonging to two different
    CSV rows (e.g. the tail of one line and the start of the next) -- without
    this, both rows would wrongly get the segment's full span."""
    joined, offsets = build_word_index(words)
    if not joined.strip():
        return None
    align = fuzz.partial_ratio_alignment(target.lower(), joined.lower())
    if align.dest_end <= align.dest_start:
        return None

    if len(target) > len(joined):
        # rapidfuzz swaps roles when s1 (target) is longer than s2 (joined):
        # dest_start/dest_end then span the WHOLE joined text (it's the
        # shorter string here), because the segment only covers PART of the
        # target -- the rest belongs to a neighboring row. Use the whole
        # segment as-is; there is nothing left to trim.
        return {"start": words[0]["start"], "end": words[-1]["end"], "score": align.score, "text": joined, "words": words}

    w_start_idx = next(i for i, (s, e) in enumerate(offsets) if e > align.dest_start)
    w_end_idx = next(i for i in range(len(offsets) - 1, -1, -1) if offsets[i][0] < align.dest_end)
    matched_words = words[w_start_idx : w_end_idx + 1]
    return {
        "start": matched_words[0]["start"],
        "end": matched_words[-1]["end"],
        "score": align.score,
        "text": joined[offsets[w_start_idx][0] : offsets[w_end_idx][1]].strip(),
        "words": matched_words,
    }


def word_level_split(group_texts: list[str], words: list[dict]) -> list[tuple[float, float]]:
    """Split one segment's word list among several CSV rows (in order) by
    fuzzy-aligning each row's text against the REMAINING words, consuming
    left to right. Returns the exact [start, end) per row from real word
    timestamps -- not a character-count guess."""
    norm_words = [w["text"].strip().lower() for w in words]
    offsets = []
    pos = 0
    for w in norm_words:
        offsets.append((pos, pos + len(w)))
        pos += len(w) + 1
    joined = " ".join(norm_words)

    results = []
    search_from = 0
    for text in group_texts:
        target = text.strip().lower()
        remainder = joined[search_from:]
        if not remainder.strip():
            results.append((words[-1]["end"], words[-1]["end"]))
            continue
        align = fuzz.partial_ratio_alignment(target, remainder)
        dest_start = search_from + align.dest_start
        dest_end = search_from + align.dest_end
        w_start_idx = next(idx for idx, (s, e) in enumerate(offsets) if e > dest_start)
        w_end_idx = next(idx for idx in range(len(offsets) - 1, -1, -1) if offsets[idx][0] < dest_end)
        results.append((words[w_start_idx]["start"], words[w_end_idx]["end"]))
        search_from = dest_end
    return results


def split_shared_segments(results: list[dict]) -> int:
    """When a run of consecutive rows resolved to the identical [start, end)
    segment (a CSV script split one recorded sentence into multiple lines),
    divide that segment among them. If the segment carries word-level
    timestamps, cut at the real word boundary (word_level_split); otherwise
    fall back to a proportional-by-character-length guess. Mutates each
    row's chosen candidate in place. Returns the number of rows affected."""
    n = len(results)
    affected = 0
    i = 0
    while i < n:
        r = results[i]
        if r["unmatched"]:
            i += 1
            continue
        cand = r["candidates"][r["chosen_index"]]
        group = [i]
        j = i + 1
        while j < n and not results[j]["unmatched"]:
            cand2 = results[j]["candidates"][results[j]["chosen_index"]]
            if abs(cand2["start"] - cand["start"]) < 1e-6 and abs(cand2["end"] - cand["end"]) < 1e-6:
                group.append(j)
                j += 1
            else:
                break

        if len(group) > 1:
            seg_start, seg_end = cand["start"], cand["end"]

            if cand.get("words"):
                spans = word_level_split([results[k]["text"] for k in group], cand["words"])
                # Force the outer edges to the segment's true boundaries --
                # the first/last matched word's timestamp should already be
                # very close, but this guarantees no gap/overlap forms
                # against whatever sits just outside this shared segment.
                spans[0] = (seg_start, spans[0][1])
                spans[-1] = (spans[-1][0], seg_end)
            else:
                total_chars = sum(max(1, len(results[k]["text"])) for k in group)
                seg_dur = seg_end - seg_start
                cursor = seg_start
                spans = []
                for k in group:
                    frac = max(1, len(results[k]["text"])) / total_chars
                    dur = seg_dur * frac
                    spans.append((cursor, cursor + dur))
                    cursor += dur

            for k, (s, e) in zip(group, spans):
                c = results[k]["candidates"][results[k]["chosen_index"]]
                c["original_start"], c["original_end"] = seg_start, seg_end
                c["start"], c["end"] = s, e
                c["shared_segment"] = True
                affected += 1
            i = j
        else:
            i += 1
    return affected


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_file")
    ap.add_argument("--segments", default="work/segments.json")
    ap.add_argument("--threshold", type=float, default=70.0)
    ap.add_argument("--out", default="work/matches.json")
    ap.add_argument("--cluster-gap", type=float, default=60.0, help="candidates more than this many seconds apart are different narrative occurrences, not the same retake")
    args = ap.parse_args()

    rows = load_csv_rows(Path(args.csv_file))
    segments = [Segment.from_dict(d) for d in json.loads(Path(args.segments).read_text(encoding="utf-8"))]
    speech = [s for s in segments if s.kind == "speech" and s.text.strip()]

    results = []
    n_ambiguous = 0
    n_unmatched = 0
    expected_pos = 0.0  # tracks narrative position (CSV order) through the recording

    total_rows = len(rows)
    board = StatusBoard(2)
    for row_idx, row in enumerate(rows, 1):
        overall = (row_idx - 1) / max(total_rows, 1)
        preview = row["text"][:60] + ("…" if len(row["text"]) > 60 else "")
        board.render([
            f"Всего:   [{render_bar(overall)}] {overall * 100:5.1f}%  (сопоставлено {row_idx - 1}/{total_rows})",
            f"Строка:  #{row['line_no']} «{preview}»",
        ])
        target = row["text"]
        candidates = []
        best_below_threshold = None
        for s in speech:
            if s.words:
                # Align against the segment's exact word range instead of
                # trusting its whole [start, end] -- a segment often holds
                # text for two different CSV rows (one line's tail + the
                # next line's start), and word-level alignment is the only
                # way to tell them apart precisely.
                words_dicts = [{"text": w.text, "start": w.start, "end": w.end} for w in s.words]
                cand = align_candidate(target, words_dicts)
                if cand is None:
                    continue
                score = cand["score"]
            else:
                score = score_match(target, s.text)
                cand = {"start": s.start, "end": s.end, "score": score, "text": s.text}

            if score >= args.threshold:
                candidates.append(cand)
            elif best_below_threshold is None or score > best_below_threshold["score"]:
                best_below_threshold = {"start": cand["start"], "end": cand["end"], "score": score, "text": cand["text"]}

        candidates.sort(key=lambda c: c["start"])

        if not candidates:
            n_unmatched += 1
            results.append({
                **row, "candidates": [], "chosen_index": None, "ambiguous": False, "unmatched": True,
                "closest_below_threshold": best_below_threshold,
            })
            continue

        # The same line can legitimately recur far apart in the video (e.g. a
        # branding tagline used in the intro AND the outro) -- that's not a
        # retake, it's two distinct narrative occurrences. Cluster ALL
        # threshold-passing candidates by time proximity (--cluster-gap) so
        # each cluster is one occurrence, then pick whichever cluster is
        # nearest to where CSV order says we should be right now. (A finer
        # transcript fragments sentences at every comma, so a fragment's own
        # score against the FULL target varies a lot depending on how much of
        # the target it covers -- filtering candidates by score margin before
        # clustering, like an earlier version of this script did, wrongly
        # discards valid low-coverage fragments. Distance-based clustering
        # alone is enough: threshold already keeps out unrelated text.)
        clusters = [[0]]
        for idx in range(1, len(candidates)):
            if candidates[idx]["start"] - candidates[clusters[-1][-1]]["end"] <= args.cluster_gap:
                clusters[-1].append(idx)
            else:
                clusters.append([idx])

        def cluster_distance(cluster: list[int]) -> float:
            lo = min(candidates[i]["start"] for i in cluster)
            hi = max(candidates[i]["end"] for i in cluster)
            if expected_pos < lo:
                return lo - expected_pos
            if expected_pos > hi:
                return expected_pos - hi
            return 0.0

        best_cluster = min(clusters, key=cluster_distance)

        # Within that cluster, split it into "readings": a finer transcript
        # can chop ONE take into several fragments that only reconstruct the
        # row TOGETHER, AND/OR the row can have been read multiple times (a
        # retake), where each retake is itself chopped into fragments. Walk
        # the cluster in time order, accumulating fragments into the current
        # reading; once it has accumulated roughly a full row's worth of text
        # (>=70%) and the NEXT fragment would overshoot well past a full row
        # (>130%), that's the boundary between two separate readings, not
        # more of the same one.
        target_len = len(target)
        readings: list[list[int]] = []
        current: list[int] = []
        current_len = 0
        for idx in best_cluster:
            frag_len = len(candidates[idx]["text"])
            if current and current_len >= 0.7 * target_len and current_len + frag_len > 1.3 * target_len:
                readings.append(current)
                current = [idx]
                current_len = frag_len
            else:
                current.append(idx)
                current_len += frag_len
        if current:
            readings.append(current)

        ambiguous = len(clusters) > 1 or len(readings) > 1
        if ambiguous:
            n_ambiguous += 1

        # "Last reading = final take" only holds among readings that are
        # genuinely alternate takes of each other (comparable match quality).
        # A short/generic target (e.g. a 2-word fragment) can coincidentally
        # score decently against an unrelated segment that happens to fall
        # within --cluster-gap of the real match -- that spurious reading
        # must never win just for sitting later in time. Only readings
        # within 10 points of the cluster's best score are eligible; among
        # those, take the last by time.
        reading_scores = [max(candidates[i]["score"] for i in reading) for reading in readings]
        best_reading_score = max(reading_scores)
        eligible = [i for i, s in enumerate(reading_scores) if s >= best_reading_score - 10]
        chosen_reading = readings[eligible[-1]]
        if len(chosen_reading) == 1:
            chosen_index = chosen_reading[0]
        else:
            merged = {
                "start": candidates[chosen_reading[0]]["start"],
                "end": candidates[chosen_reading[-1]]["end"],
                "score": min(candidates[i]["score"] for i in chosen_reading),
                "text": " ".join(candidates[i]["text"] for i in chosen_reading),
                "merged_fragments": True,
            }
            candidates.append(merged)
            chosen_index = len(candidates) - 1

        expected_pos = candidates[chosen_index]["end"]

        # Earlier readings within the SAME cluster are genuine retakes of
        # this exact line (discarded in favor of the final one) -- keep
        # their spans so the overlay can still show a "Дубль" card at the
        # earlier take's real position, instead of silently erasing it.
        # Only OTHER eligible (comparable-score) readings are real retakes
        # worth flagging as "Дубль" -- an ineligible reading was excluded
        # because it's a spurious match, not a genuine repeat of this line,
        # and must not show up in the video as if it were one.
        duplicate_reading_indices = [i for i in eligible if readings[i] is not chosen_reading]
        duplicate_takes = [
            {"start": candidates[readings[i][0]]["start"], "end": candidates[readings[i][-1]]["end"]}
            for i in duplicate_reading_indices
        ]

        results.append({
            **row, "candidates": candidates, "chosen_index": chosen_index, "ambiguous": ambiguous,
            "unmatched": False, "duplicate_takes": duplicate_takes,
        })

    board.render([
        f"Всего:   [{render_bar(1.0)}] 100.0%  (сопоставлено {total_rows}/{total_rows})",
        "",
    ])
    board.close()

    n_split = split_shared_segments(results)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Matched {len(rows)} CSV rows -> {out_path}")
    print(f"  unmatched: {n_unmatched}, ambiguous (multiple takes): {n_ambiguous}, split (shared segment): {n_split}")

    if n_unmatched:
        print("\nUNMATCHED rows (no segment above threshold -- lower --threshold or check for typos):")
        for r in results:
            if r["unmatched"]:
                best = r.get("closest_below_threshold")
                print(f'  line {r["line_no"]}: "{r["text"]}"')
                if best:
                    print(f'    closest (below threshold, score {best["score"]:.0f}): {fmt_time(best["start"])}-{fmt_time(best["end"])} "{best["text"]}"')

    if n_ambiguous:
        print("\nAMBIGUOUS rows -- multiple takes found, confirm the chosen one (tentatively = last by time):")
        for r in results:
            if r["ambiguous"]:
                print(f'\n  line {r["line_no"]}: "{r["text"]}"')
                for i, c in enumerate(r["candidates"]):
                    mark = " <- tentative pick" if i == r["chosen_index"] else ""
                    print(f'    [{i}] {fmt_time(c["start"])}-{fmt_time(c["end"])} (score {c["score"]:.0f}): "{c["text"]}"{mark}')
        print("\nEdit \"chosen_index\" in work/matches.json for any row where the tentative pick is wrong, then proceed.")


if __name__ == "__main__":
    main()
