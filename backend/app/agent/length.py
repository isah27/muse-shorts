"""Length rule: a Short must run at least MIN_SECONDS (ideally 45-75 s, longer is fine when the sources hold enough verified facts).

We estimate the spoken length from the script before any media is made (Kokoro at speed 1.05 measures about 0.37 s per word
plus about 0.55 s of pause/padding per scene), so the claim critic's drops can be compensated with new *sourced* lines instead
of discovering a 38-second video after the render. Padding is never allowed: new lines must be verified claims like every other line.
"""
from __future__ import annotations
from .. import config as C

def words(scene: dict) -> int:
    return len(str(scene.get("narration") or " ".join(l["text"] for l in scene.get("lines", []))).split())

def estimate_seconds(scenes: list[dict]) -> float:
    return round(sum(words(s) * C.WORD_SEC + C.SCENE_SEC for s in scenes), 1)

def total_words(scenes: list[dict]) -> int:
    return sum(words(s) for s in scenes)

def seconds_short(scenes: list[dict]) -> float:
    """How many estimated seconds are missing to be safely above the minimum (0 when long enough)."""
    return max(0.0, round(C.MIN_SECONDS + C.LENGTH_MARGIN - estimate_seconds(scenes), 1))

def words_for(seconds: float, n_scenes: int = 1) -> int:
    return max(0, int(round((seconds - C.SCENE_SEC * n_scenes) / C.WORD_SEC)))

def trim_to_max(scenes: list[dict]) -> int:
    """Hard cap: if the script runs past MAX_SECONDS, cut whole scenes just before the closing scene. Returns how many were cut."""
    cut = 0
    while estimate_seconds(scenes) > C.MAX_SECONDS and len(scenes) > 3:
        del scenes[-2]; cut += 1
    return cut
