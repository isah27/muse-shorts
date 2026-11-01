"""Claim critic: every claim line of the script is checked against the text of the source it cites.

Verdict ladder per line:  supported  ->  keep
                          partial / unsupported / contradicted / fabricated quote  ->  rewrite from the sources and re-check (bounded retries)
                          still failing after MAX_CLAIM_ROUNDS  ->  drop the line (never ship an unverified claim)
Checks run in parallel (the Baseten model reasons for several seconds per call). Every rejection / rewrite / drop is
emitted as an event so the retry is visible in the SSE agent stream.
"""
from __future__ import annotations
import json, re
from concurrent.futures import ThreadPoolExecutor
from typing import Callable
from . import prompts as P
from .evidence import Source, _norm

def quote_in_source(quote: str | None, source_text: str) -> bool:
    """Deterministic anti-fabrication check: the cited quote must really occur in the source (whitespace/punctuation-insensitive)."""
    if not quote or len(_norm(quote)) < 8:
        return False
    return _norm(quote) in _norm(source_text)

def _ask(llm, system, user, schema) -> tuple[dict, str]:
    fn = getattr(llm, "complete_json_ex", None)
    if fn:
        return fn(system, user, schema)
    return llm.complete_json(system, user, schema), ""

def _trim(s: str, n: int = 700) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[:n].rsplit(" ", 1)[0] + " …"

def normalise_scenes(raw_scenes: list[dict]) -> list[dict]:
    """Coerce model output: ensure each scene has well-formed lines and a derived narration."""
    out = []
    for s in raw_scenes:
        lines = []
        for ln in s.get("lines") or []:
            text = str(ln.get("text", "")).strip()
            if not text:
                continue
            kind = "claim" if ln.get("kind") == "claim" or (ln.get("source_id") and ln.get("kind") != "framing") else "framing"
            lines.append({"kind": kind, "text": text, "source_id": ln.get("source_id") if kind == "claim" else None,
                          "quote": ln.get("quote") if kind == "claim" else None, "status": "unchecked", "history": []})
        if lines:
            s = {**s, "lines": lines}
            out.append(s)
    return out

def set_narration(scene: dict) -> None:
    scene["narration"] = " ".join(t if t[-1:] in ".!?…" else t + "." for t in (l["text"].strip() for l in scene["lines"]) if t)

def _content_words(t: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", t.lower()) if len(w) > 3}

def dedupe(scenes: list[dict], threshold: float = 0.6) -> int:
    """Drop later claim lines that repeat an earlier line (rewrites from the same source sentence often collide)."""
    seen: list[set[str]] = []
    seen_q: list[set[str]] = []   # two lines resting on (nearly) the same source sentence say the same thing
    n = 0
    for s in scenes:
        keep = []
        for l in s["lines"]:
            w = _content_words(l["text"])
            q = _content_words(l.get("quote") or "")
            if l["kind"] == "claim" and ((w and any(len(w & o) / len(w | o) >= threshold for o in seen))
                                         or (q and any(len(q & o) / len(q | o) >= 0.8 for o in seen_q))):
                n += 1; continue
            if l["kind"] == "claim":
                seen.append(w)
                if q: seen_q.append(q)
            keep.append(l)
        s["lines"] = keep
    scenes[:] = [s for s in scenes if s["lines"]]
    return n

CTA = "Follow for more body science."

def ensure_cta(scenes: list[dict]) -> None:
    """The last spoken line should be a follow CTA. If the gate dropped it, add a fixed, fact-free framing line."""
    if scenes and not any(l["kind"] == "framing" and "follow" in l["text"].lower() for l in scenes[-1]["lines"]):
        scenes[-1]["lines"].append({"kind": "framing", "text": CTA, "source_id": None, "quote": None, "status": "supported",
                                    "history": [{"round": 0, "verdict": "supported", "reason": "fixed CTA, states no fact"}], "quote_verified": True})

class ClaimGate:
    def __init__(self, critic, writer, sources: list[Source], emit: Callable[..., None], max_rounds: int = 2, workers: int = 4):
        self.critic, self.writer, self.emit = critic, writer, emit
        self.sources = {s.id: s for s in sources}
        self.max_rounds, self.workers = max_rounds, workers

    def add_sources(self, more: list[Source]) -> None:
        for x in more:
            self.sources[x.id] = x

    # ---- single-line check (runs in a worker thread; must not emit)
    def check_line(self, line: dict) -> dict:
        if line["kind"] == "framing":
            d, reasoning = _ask(self.critic, P.CHECK_FRAMING, json.dumps({"line": line["text"]}), P.CHECK_FRAMING_SCHEMA)
            v = d.get("verdict", "unsupported")
            return {"verdict": "supported" if v == "supported" else "unsupported", "reason": d.get("reason", ""), "reasoning": reasoning, "fix": ""}
        src = self.sources.get(line.get("source_id"))
        if not src:
            return {"verdict": "unsupported", "reason": f"cites unknown source {line.get('source_id')!r}", "reasoning": "", "fix": ""}
        d, reasoning = _ask(self.critic, P.CHECK_CLAIM, json.dumps(
            {"line": line["text"], "cited_quote": line.get("quote"), "source": {"id": src.id, "title": src.title, "text": src.text}}), P.CHECK_CLAIM_SCHEMA)
        v = d.get("verdict", "unsupported")
        v = v if v in ("supported", "partial", "unsupported", "contradicted") else "unsupported"
        res = {"verdict": v, "reason": d.get("reason", ""), "fix": d.get("fix", ""), "reasoning": reasoning,
               "supporting_quote": d.get("supporting_quote")}
        if v == "supported":
            sq = d.get("supporting_quote")
            if quote_in_source(sq, src.text):
                res["quote_verified"] = True
            elif quote_in_source(line.get("quote"), src.text):
                res["supporting_quote"], res["quote_verified"] = line["quote"], True
            else:  # critic said supported but nothing verbatim backs it -> do not trust
                res.update(verdict="unsupported", reason="no verbatim passage in the source backs this line", quote_verified=False)
        return res

    def rewrite_line(self, line: dict, verdict: dict) -> dict:
        d, reasoning = _ask(self.writer, P.REWRITE_CLAIM, json.dumps({
            "line": line["text"], "verdict": verdict["verdict"], "reason": verdict.get("reason", ""), "fix": verdict.get("fix", ""),
            "sources": [{"id": s.id, "title": s.title, "text": s.text} for s in self.sources.values()]}), P.REWRITE_CLAIM_SCHEMA)
        d["reasoning"] = reasoning
        return d

    # ---- the gate
    def run(self, scenes: list[dict]) -> dict:
        # lines that already passed in an earlier run (length top-up rounds) are not re-checked
        lines = [(si, li, l) for si, s in enumerate(scenes) for li, l in enumerate(s["lines"]) if l.get("status") not in ("supported", "rewritten")]
        stats = {"claims": sum(1 for _, _, l in lines if l["kind"] == "claim"), "framing": sum(1 for _, _, l in lines if l["kind"] == "framing"),
                 "supported_first_try": 0, "rewritten": 0, "dropped": 0, "corrections": [], "checks": 0, "rounds": []}
        pending = list(lines)
        for rnd in range(1, self.max_rounds + 2):
            self.emit("claims", "running", f"Round {rnd}: checking {len(pending)} lines against their sources…", round=rnd)
            with ThreadPoolExecutor(self.workers) as ex:
                verdicts = list(ex.map(lambda t: self.check_line(t[2]), pending))
            stats["checks"] += len(pending)
            failing = []
            for (si, li, l), v in zip(pending, verdicts):
                l["history"].append({"round": rnd, "verdict": v["verdict"], "reason": v.get("reason", "")})
                if v["verdict"] == "supported":
                    l["status"] = "supported" if rnd == 1 else "rewritten"
                    l["supporting_quote"] = v.get("supporting_quote") or l.get("quote")
                    l["quote_verified"] = bool(v.get("quote_verified", l["kind"] == "framing"))
                    if rnd == 1:
                        stats["supported_first_try"] += 1
                    self.emit("claims", "progress", f"✓ Scene {si + 1}: “{_trim(l['text'], 90)}” — {l.get('source_id') or 'framing'}",
                              kind="pass", scene=si, line=l["text"], source_id=l.get("source_id"), reasoning=_trim(v.get("reasoning", "")))
                else:
                    failing.append(((si, li, l), v))
                    self.emit("claims", "retry",
                              f"Claim rejected (scene {si + 1}, {v['verdict']}): “{_trim(l['text'], 120)}” — {v.get('reason', '')}",
                              kind="reject", round=rnd, scene=si, line=l["text"], verdict=v["verdict"], reason=v.get("reason", ""),
                              source_id=l.get("source_id"), reasoning=_trim(v.get("reasoning", "")))
            stats["rounds"].append({"round": rnd, "checked": len(pending),
                                    "rejected": [f"scene {si + 1} {v['verdict']}: {_trim(l['text'], 90)}" for (si, li, l), v in failing]})
            if not failing:
                break
            if rnd > self.max_rounds:
                for (si, li, l), v in failing:
                    l["status"] = "dropped"
                    stats["dropped"] += 1
                    stats["corrections"].append({"scene": si, "action": "dropped", "before": l["text"], "reason": v.get("reason", ""), "verdict": v["verdict"]})
                    self.emit("claims", "retry", f"Dropped unverifiable line (scene {si + 1}): “{_trim(l['text'], 120)}”",
                              kind="drop", scene=si, line=l["text"], reason=v.get("reason", ""))
                break
            # rewrite failing lines (parallel) from the sources — a 'framing' line that smuggled in a fact is re-sourced as a claim — then re-check only those
            with ThreadPoolExecutor(self.workers) as ex:
                fixes = list(ex.map(lambda fv: self.rewrite_line(fv[0][2], fv[1]), failing))
            pending = []
            for ((si, li, l), v), fx in zip(failing, fixes):
                if fx.get("drop") or not str(fx.get("text", "")).strip():
                    l["status"] = "dropped"; stats["dropped"] += 1
                    stats["corrections"].append({"scene": si, "action": "dropped", "before": l["text"], "reason": v.get("reason", ""), "verdict": v["verdict"]})
                    self.emit("claims", "retry", f"Source can't support this point — dropped (scene {si + 1}): “{_trim(l['text'], 120)}”",
                              kind="drop", scene=si, line=l["text"], reason=v.get("reason", ""), reasoning=_trim(fx.get("reasoning", "")))
                    continue
                before = l["text"]
                l.update(text=str(fx["text"]).strip(), source_id=fx.get("source_id") or l.get("source_id"), quote=fx.get("quote"), kind="claim", status="rewriting")
                l["history"].append({"round": rnd, "rewrite_from": before})
                stats["rewritten"] += 1
                stats["corrections"].append({"scene": si, "action": "rewritten", "before": before, "after": l["text"], "source_id": l["source_id"],
                                             "reason": v.get("reason", ""), "verdict": v["verdict"]})
                self.emit("claims", "retry", f"Rewrote from {l['source_id']}: “{_trim(l['text'], 140)}”", kind="rewrite", scene=si,
                          before=before, after=l["text"], source_id=l["source_id"], reasoning=_trim(fx.get("reasoning", "")))
                pending.append((si, li, l))
            if not pending:
                break
        # apply drops, rebuild narration
        for s in scenes:
            s["lines"] = [l for l in s["lines"] if l["status"] != "dropped"]
        kept = [s for s in scenes if s["lines"]]
        scenes[:] = kept
        stats["deduped"] = dedupe(scenes)
        ensure_cta(scenes)
        for s in scenes:
            set_narration(s)
        stats["claims_final"] = sum(1 for s in scenes for l in s["lines"] if l["kind"] == "claim")
        stats["all_verified"] = all(l["status"] in ("supported", "rewritten") for s in scenes for l in s["lines"])
        return stats
