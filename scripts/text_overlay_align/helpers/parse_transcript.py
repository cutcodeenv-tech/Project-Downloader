"""Parse a timed transcript (SRT / Whisper-style JSON / plain timestamped text)
into a flat list of Segment objects (helpers.model.Segment) and dump them to
work/segments.json.

Usage:
    uv run helpers/parse_transcript.py <transcript_file> [--format srt|json|lines] [--out work/segments.json]

If --format is omitted it's guessed from the file extension / content.

Pause/breath detection:
  - JSON: an entry is treated as non-speech if its "text"/"word" (stripped, lowered)
    matches one of PAUSE_MARKERS / BREATH_MARKERS, or if it carries an explicit
    "type"/"event" field equal to "pause"/"breath"/"silence".
  - SRT / plain text: same marker matching against the cue text. SRT/plain text
    have no word-level timing, so gaps between consecutive cues are NOT assumed to
    be silence automatically -- run silence.py (ffmpeg silencedetect) separately if
    the transcript doesn't mark pauses/breaths explicitly.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from helpers.model import Segment, Word

PAUSE_MARKERS = {"[pause]", "(pause)", "[silence]", "(silence)", "...", "[...]", "[пауза]", "(пауза)"}
BREATH_MARKERS = {"[breath]", "(breath)", "[вдох]", "(вдох)", "[inhale]", "(inhale)"}

SRT_TIME_RE = re.compile(
    r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})"
)
LINE_TIME_RE = re.compile(
    r"\[?(\d{1,2}):(\d{2}):(\d{2})(?:[.,](\d{1,3}))?\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})(?:[.,](\d{1,3}))?\]?\s*(.*)"
)


def _hms_to_seconds(h: str, m: str, s: str, ms: str | None) -> float:
    ms = (ms or "0").ljust(3, "0")[:3]
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def _classify(text: str) -> str:
    t = text.strip().lower()
    if t in PAUSE_MARKERS:
        return "pause"
    if t in BREATH_MARKERS:
        return "breath"
    return "speech"


def guess_format(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".srt":
        return "srt"
    if suffix == ".json":
        return "json"
    text = path.read_text(encoding="utf-8", errors="ignore")[:2000]
    if SRT_TIME_RE.search(text):
        return "srt"
    if text.lstrip().startswith("{") or text.lstrip().startswith("["):
        return "json"
    return "lines"


def parse_srt(path: Path) -> list[Segment]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    blocks = re.split(r"\n\s*\n", text.strip())
    segments: list[Segment] = []
    for block in blocks:
        lines = [l for l in block.splitlines() if l.strip() != ""]
        if not lines:
            continue
        # optional leading numeric index
        if lines[0].strip().isdigit():
            lines = lines[1:]
        if not lines:
            continue
        m = SRT_TIME_RE.search(lines[0])
        if not m:
            continue
        start = _hms_to_seconds(*m.group(1, 2, 3, 4))
        end = _hms_to_seconds(*m.group(5, 6, 7, 8))
        cue_text = " ".join(lines[1:]).strip()
        kind = _classify(cue_text)
        segments.append(Segment(kind=kind, start=start, end=end, text="" if kind != "speech" else cue_text))
    return segments


def parse_lines(path: Path) -> list[Segment]:
    segments: list[Segment] = []
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        m = LINE_TIME_RE.match(raw)
        if not m:
            continue
        start = _hms_to_seconds(m.group(1), m.group(2), m.group(3), m.group(4))
        end = _hms_to_seconds(m.group(5), m.group(6), m.group(7), m.group(8))
        cue_text = m.group(9).strip()
        kind = _classify(cue_text)
        segments.append(Segment(kind=kind, start=start, end=end, text="" if kind != "speech" else cue_text))
    return segments


RANGE_TS_RE = re.compile(
    r"^(?:(\d{1,2}):)?(\d{1,2}):(\d{2})\s*-\s*(?:(\d{1,2}):)?(\d{1,2}):(\d{2})$"
)


def _range_ts_to_seconds(h: str | None, m: str, s: str) -> float:
    return (int(h) * 3600 if h else 0) + int(m) * 60 + int(s)


def parse_json(path: Path) -> list[Segment]:
    """Handles three common shapes:

    1. Whisper/whisperx style: {"segments": [{"start","end","text","words":[{"word"/"text","start","end"}, ...]}]}
    2. A flat list of events: [{"start","end","text"/"word","type"?}, ...]
    3. A flat list of sentence-level ranges with no word timing:
       [{"text": "...", "timestamp": "MM:SS-MM:SS"}, ...] (hours optional: "H:MM:SS-H:MM:SS")
    """
    data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    raw_segments = data.get("segments") if isinstance(data, dict) else data
    if raw_segments is None:
        raise ValueError("Unrecognized JSON transcript shape: no 'segments' key and not a list")

    segments: list[Segment] = []
    for seg in raw_segments:
        explicit_type = (seg.get("type") or seg.get("event") or "").strip().lower()
        text = (seg.get("text") or seg.get("word") or "").strip()

        if "timestamp" in seg and ("start" not in seg or "end" not in seg):
            m = RANGE_TS_RE.match(seg["timestamp"].strip())
            if not m:
                raise ValueError(f"Unrecognized timestamp range: {seg['timestamp']!r}")
            start = _range_ts_to_seconds(m.group(1), m.group(2), m.group(3))
            end = _range_ts_to_seconds(m.group(4), m.group(5), m.group(6))
        else:
            start = float(seg["start"])
            end = float(seg["end"])

        if explicit_type in {"pause", "silence"}:
            kind = "pause"
        elif explicit_type == "breath":
            kind = "breath"
        else:
            kind = _classify(text)

        words = []
        for w in seg.get("words", []) or []:
            wtext = (w.get("word") or w.get("text") or "").strip()
            if not wtext:
                continue
            words.append(Word(text=wtext, start=float(w["start"]), end=float(w["end"])))

        segments.append(Segment(kind=kind, start=start, end=end, text="" if kind != "speech" else text, words=words))
    return segments


def parse(path: Path, fmt: str | None) -> list[Segment]:
    fmt = fmt or guess_format(path)
    if fmt == "srt":
        return parse_srt(path)
    if fmt == "json":
        return parse_json(path)
    if fmt == "lines":
        return parse_lines(path)
    raise ValueError(f"Unknown format: {fmt}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("transcript")
    ap.add_argument("--format", choices=["srt", "json", "lines"], default=None)
    ap.add_argument("--out", default="work/segments.json")
    args = ap.parse_args()

    path = Path(args.transcript)
    segments = parse(path, args.format)
    segments.sort(key=lambda s: s.start)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps([s.to_dict() for s in segments], ensure_ascii=False, indent=2), encoding="utf-8")

    n_speech = sum(1 for s in segments if s.kind == "speech")
    n_pause = sum(1 for s in segments if s.kind == "pause")
    n_breath = sum(1 for s in segments if s.kind == "breath")
    print(f"Parsed {len(segments)} segments -> {out_path}")
    print(f"  speech={n_speech} pause={n_pause} breath={n_breath}")
    if n_pause == 0 and n_breath == 0:
        print("  No explicit pause/breath markers found in the transcript.")
        print("  Run helpers/silence.py against the audio to detect gaps via ffmpeg silencedetect.")


if __name__ == "__main__":
    main()
