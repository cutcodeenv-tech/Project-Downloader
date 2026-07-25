"""Shared data model for the text-overlay-align pipeline.

Everything downstream (matcher, EDL builder, timing, renderer, audio, EDL export)
speaks in these two types, so the format of the original transcript (SRT / JSON /
plain text) only matters to parse_transcript.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict


@dataclass
class Word:
    text: str
    start: float  # seconds, absolute in the ORIGINAL (uncut) recording
    end: float


@dataclass
class Segment:
    """One timeline event in the original recording."""

    kind: str  # "speech" | "pause" | "breath" | "noise"
    start: float
    end: float
    text: str = ""
    words: list[Word] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    @staticmethod
    def from_dict(d: dict) -> "Segment":
        words = [Word(**w) for w in d.get("words", [])]
        return Segment(kind=d["kind"], start=d["start"], end=d["end"], text=d.get("text", ""), words=words)
