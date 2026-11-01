"""SAM gate: an image passes only if SAM finds every structure the scene must show.

Per structure, a detection counts if its score >= GATE_MIN_SCORE and its box is a sane size. A structure that is found
twice with similar confidence in different places is "ambiguous" (we could label the wrong one), which also fails the try.
On failure the frame is regenerated (a new seed, with the missing structures called out in the prompt) up to GATE_MAX_REGEN
times. If a structure is still missing after that, the best attempt is kept and that label is dropped (omit-label rule):
the video never labels something SAM could not find. Every reject / regenerate / drop is emitted as an event (step
"frame_qa", status "retry") so the retries are visible in the agent stream, like the claim critic.
"""
from __future__ import annotations
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from PIL import Image
from .. import config as C
from ..providers.base import Segment

def _iou(a, b) -> float:
    x1, y1, x2, y2 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0

@dataclass
class Check:
    found: dict[str, Segment] = field(default_factory=dict)   # structure -> best sane detection
    missing: list[str] = field(default_factory=list)          # nothing usable found
    ambiguous: list[str] = field(default_factory=list)        # two similar-confidence instances
    detail: dict[str, str] = field(default_factory=dict)      # structure -> short reason
    @property
    def passed(self) -> bool:
        return not self.missing and not self.ambiguous
    @property
    def bad(self) -> list[str]:
        return self.missing + self.ambiguous

def check_image(seg, path: str, structures: list[str], min_score=None, min_area=None, max_area=None) -> Check:
    min_score = C.GATE_MIN_SCORE if min_score is None else min_score
    min_area = C.GATE_MIN_AREA if min_area is None else min_area
    max_area = C.GATE_MAX_AREA if max_area is None else max_area
    W, H = Image.open(path).size
    res = Check()
    for phrase in structures:
        raw = seg.segment(path, phrase)
        good, why = [], ""
        for s in raw:
            area = max(0, s.box[2] - s.box[0]) * max(0, s.box[3] - s.box[1]) / (W * H)
            if s.score < min_score:
                why = why or f"low confidence {s.score:.2f}"
            elif area < min_area:
                why = why or f"too small ({area:.1%} of frame)"
            elif area > max_area:
                why = why or f"too large ({area:.0%} of frame)"
            else:
                good.append(s)
        if not good:
            res.missing.append(phrase); res.detail[phrase] = why or "not found"
            continue
        area_of = lambda s: (s.box[2] - s.box[0]) * (s.box[3] - s.box[1])
        good.sort(key=lambda s: (-s.score, -area_of(s)))
        best = good[0]
        # The Meta SAM API returns no confidence (every score is 1.0), so "several instances" is normal there (three cells):
        # ambiguity only applies when the provider gives real scores; otherwise the largest instance is labelled.
        scored = len({round(s.score, 3) for s in good}) > 1 or best.score < 0.999
        rivals = [s for s in good[1:] if scored and s.score >= 0.8 * best.score and _iou(s.box, best.box) < 0.3]
        if rivals:
            res.ambiguous.append(phrase); res.detail[phrase] = f"{1 + len(rivals)} similar instances"
            res.found[phrase] = best   # kept in case it is the best attempt, but the label is only used if the try passes
        else:
            res.found[phrase] = best
    # Two different structures must not be the same region (SAM answering "cerebellum" with the whole brain): the smaller
    # box keeps its label, a tie goes to the structure listed first, and the other one fails the try.
    names = [p for p in structures if p in res.found and p not in res.ambiguous]
    for a in range(len(names)):
        for b in range(a + 1, len(names)):
            pa, pb = names[a], names[b]
            if pa in res.ambiguous or pb in res.ambiguous or pa == pb:
                continue
            if _iou(res.found[pa].box, res.found[pb].box) > C.GATE_MAX_OVERLAP:
                area = lambda n: (res.found[n].box[2] - res.found[n].box[0]) * (res.found[n].box[3] - res.found[n].box[1])
                loser = pa if area(pa) < area(pb) else pb
                winner = pb if loser == pa else pa
                if area(pa) == area(pb): loser, winner = pb, pa
                res.ambiguous.append(loser); res.detail[loser] = f"same region as {winner}"
    return res

@dataclass
class SceneGate:
    scene: int
    attempts: int
    passed: bool
    labels: list[Segment]
    dropped: list[str]
    first_try: bool

class ImageGate:
    def __init__(self, img_gen, seg, emit: Callable[..., None], url: Callable[[Path], str], max_regen: int | None = None, quality=None):
        self.gen, self.seg, self.emit, self.url = img_gen, seg, emit, url
        self.max_regen = C.GATE_MAX_REGEN if max_regen is None else max_regen
        self.quality = quality

    def run_scene(self, i: int, structures: list[str], make_prompt: Callable[[list[str], int], str], final: Path, attempts_dir: Path) -> SceneGate:
        attempts_dir.mkdir(parents=True, exist_ok=True)
        best: tuple[int, Check, Path] | None = None
        missing: list[str] = []
        total = self.max_regen + 1
        made = 0
        for n in range(total):
            p = attempts_dir / f"{i + 1:02}_try{n + 1}.png"
            self.gen.generate(make_prompt(missing, n), str(p), seed=n)
            made = n + 1
            if self.quality and not self.quality(str(p))["ok"]:
                self.emit("frame_qa", "retry", f"Frame {i + 1} try {n + 1} looked flat or badly exposed" + (" — regenerating" if n + 1 < total else ""),
                          kind="reject", scene=i, attempt=n + 1, reason="exposure", image=self.url(p))
                if best is None:
                    best = (99, Check(missing=list(structures)), p)
                continue
            chk = check_image(self.seg, str(p), structures)
            score = len(chk.bad)
            if best is None or score < best[0]:
                best = (score, chk, p)
            if chk.passed:
                break
            missing = chk.bad
            why = "; ".join(f"{s}: {chk.detail[s]}" for s in chk.bad)
            last = n + 1 == total
            self.emit("frame_qa", "retry",
                      f"Frame {i + 1} try {n + 1}: SAM could not confirm {', '.join(chk.bad)} ({why})" + ("" if last else " — regenerating"),
                      kind="reject", scene=i, attempt=n + 1, missing=chk.bad, reason=why, image=self.url(p))
            if not last:
                self.emit("frame_qa", "retry", f"Frame {i + 1}: regenerating with new seed (try {n + 2}/{total}), asking for {', '.join(chk.bad)}",
                          kind="regenerate", scene=i, attempt=n + 2)
        _, chk, p = best
        shutil.copy(p, final)
        labels = [chk.found[s] for s in structures if s in chk.found and s not in chk.bad]
        dropped = list(chk.bad)
        for s in dropped:
            self.emit("frame_qa", "retry", f"Frame {i + 1}: dropped the “{s}” label — SAM never confirmed it, so the video will not label it",
                      kind="drop_label", scene=i, label=s, reason=chk.detail.get(s, ""))
        return SceneGate(i, made, not dropped, labels, dropped, first_try=made == 1 and not dropped)
