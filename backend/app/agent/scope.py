"""Scope guard: Muse Shorts only makes anatomy / physiology / neuroscience *explainers*.

Two layers:
  1. deterministic rules catch obvious medical-advice, self-harm and prompt-injection topics with zero model cost;
  2. an LLM classifier (Muse Spark / Spark Open) handles everything else and proposes search queries for evidence.
The topic string is untrusted user input: it is only ever passed as JSON data, never concatenated into instructions.
"""
from __future__ import annotations
import json, re
from dataclasses import dataclass, field
from . import prompts as P

# (category, regex, reason) — ordered, first hit wins
RULES: list[tuple[str, re.Pattern, str]] = [
    ("unsafe", re.compile(r"\b(suicid\w*|kill (myself|yourself|someone)|self[- ]harm|overdose on purpose|end (my|your) life)\b", re.I),
     "This touches on self-harm. Muse Shorts won't make content about it. If you're struggling, please talk to someone you trust or a local crisis line."),
    ("medical_advice", re.compile(r"\b(diagnos\w*|prescri\w+|dosage|dose of|how (much|many) (mg|milligrams?|pills?|tablets?)|\d+\s?mg\b|"
                                  r"how (do|can|does|to)( (i|you|we|one|people))? (cure|treat|heal|get rid of|fix|manage)|(cure|treat|treatment|remedy|remedies|therapy) (for|of) |"
                                  r"do i have|am i (sick|ill|dying|having)|should i (take|stop|see|worry|use|go)|is it safe to (take|use|mix|combine)|"
                                  r"symptoms? of my|my (symptoms?|headache|pain|diagnosis|medication|pills?)|can i (take|mix|stop|combine)|"
                                  r"(drug|medication|medicine|supplement)s? (interactions?|for)|side effects? of (taking|my))\b", re.I),
     "That's a medical-advice question (diagnosis, treatment, dosage or a personal health decision). Muse Shorts only explains how the body and brain work."),
    ("injection", re.compile(r"(ignore (all |the )?(previous|above|prior) (instructions|rules)|disregard (your|the) (instructions|rules)|system prompt|you are now)", re.I),
     "The topic contains instructions aimed at the AI instead of a science topic."),
]

@dataclass
class ScopeResult:
    allowed: bool
    category: str = "ok"                 # ok | medical_advice | off_topic | unsafe | injection
    reason: str = ""
    suggestion: str = ""
    topic_clean: str = ""
    search_queries: list[str] = field(default_factory=list)
    layer: str = "llm"                   # "rules" | "llm"
    reasoning: str = ""

def rule_check(topic: str) -> ScopeResult | None:
    for cat, rx, reason in RULES:
        if rx.search(topic):
            return ScopeResult(False, cat, reason, SUGGESTION.get(cat, ""), layer="rules")
    return None

SUGGESTION = {
    "medical_advice": "Try the mechanism instead, e.g. “How the brain processes pain signals” or “How the liver filters blood”.",
    "unsafe": "",
    "injection": "Try a plain topic like “How neurons fire” or “How the heart pumps blood”.",
}

def check(topic: str, llm) -> ScopeResult:
    topic = (topic or "").strip()
    hit = rule_check(topic)
    if hit:
        return hit
    ask = getattr(llm, "complete_json_ex", None)
    if ask:
        d, reasoning = ask(P.SCOPE, json.dumps({"topic": topic}), P.SCOPE_SCHEMA)
    else:
        d, reasoning = llm.complete_json(P.SCOPE, json.dumps({"topic": topic}), P.SCOPE_SCHEMA), ""
    cat = d.get("category", "ok" if d.get("allowed") else "off_topic")
    allowed = bool(d.get("allowed")) and cat == "ok"
    qs = [q.strip() for q in (d.get("search_queries") or []) if isinstance(q, str) and q.strip()][:3]
    return ScopeResult(allowed, cat, str(d.get("reason", "")), str(d.get("suggestion", "")),
                       str(d.get("topic_clean") or topic), qs or [topic], "llm", reasoning)
