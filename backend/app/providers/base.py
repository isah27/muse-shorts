"""Provider interfaces. Every Meta capability the agent uses sits behind one of these."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Protocol

@dataclass
class Segment:
    label: str
    box: tuple[int, int, int, int]          # x1, y1, x2, y2 in image pixels
    mask: "object | None" = None            # optional PIL 'L' image, same size as source
    score: float = 1.0

@dataclass
class Transcript:
    text: str
    words: list[dict] = field(default_factory=list)   # [{word,start,end}] when available

class LLM(Protocol):
    name: str
    def complete_json(self, system: str, user: str, schema_hint: str = "") -> dict: ...

class ImageGen(Protocol):
    name: str
    def generate(self, prompt: str, out_path: str, seed: int = 0, aspect: str = "1080x1920") -> str: ...

class Segmenter(Protocol):
    name: str
    def segment(self, image_path: str, phrase: str) -> list[Segment]: ...

class ASR(Protocol):
    name: str
    def transcribe(self, wav_path: str, keywords: list[str] | None = None) -> Transcript: ...
