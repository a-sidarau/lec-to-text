from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(slots=True)
class Segment:
    start: float
    end: float
    text: str


@dataclass(slots=True)
class TranscriptResult:
    text: str
    segments: list[Segment]
    language: str
    duration: float
    backend: str
    model: str


class Transcriber(Protocol):
    def transcribe(
        self, audio_path: str | Path, *, language: str | None = None
    ) -> TranscriptResult: ...