"""Model-driven orchestrator: the model picks the next tool, the tools enforce the rules.

Lessons applied (Agents 101 / legal-agent-workshop):
  1. The model chooses; the code carries out exactly ONE tool per turn.
  2. Tools refuse bad calls ({"error": ...}) and the refusal goes back to the model.
  3. Checklist + state on disk (outputs/<run>/state.json) every turn: resume, and language remakes reuse verified facts.
  4. finish_short is the only normal exit; hard turn limit with a last-turn nudge.
  5. Verification hooks live inside tools (claim critic, SAM gate, length rule). Retries are capped at 3, then escalate.
"""
from __future__ import annotations
import json, threading, time, traceback
from pathlib import Path
from .. import config as C
from ..providers.openai_compat import extract_json
from . import length as L_
from . import verify as V
from ..media import render as RND
from ..media.wazobia import MissingLineError
from .claims import ClaimGate
from .evidence import Source, get_evidence
from .scope import ScopeResult
from .pipeline import Job, steps_for

MAX_RETRIES = 3          # same tool failing / refused this many times in a row -> escalate
CHECKLIST_DEFAULT = [
    {"id": "scope", "text": "Topic is an explainer in scope (no medical advice)"},
    {"id": "sources", "text": "Enough Wikipedia/PubMed evidence gathered"},
    {"id": "claims", "text": "Every claim is supported by a verbatim source quote"},
    {"id": "length", "text": f"Script is {C.MIN_SECONDS:.0f}-{C.IDEAL_MAX_SECONDS:.0f}s (cap {C.MAX_SECONDS:.0f}s), never padded"},
    {"id": "labels", "text": "Every label on screen is confirmed by SAM"},
    {"id": "video", "text": "1080x1920 video rendered"},
    {"id": "final", "text": "Final check: claims, labels, duration, captions = voice, nothing swapped since it passed"},
]

# Per-stage tool allowlist: only these tools are exposed (and accepted) in each stage. scope_check/set_checklist are always allowed.
ALWAYS = ["scope_check", "set_checklist"]
STAGE_TOOLS = {
    "scope": [],
    "evidence": ["gather_evidence"],
    "plan": ["plan_scenes", "gather_evidence"],
    "script": ["write_script", "plan_scenes", "gather_evidence"],
    "claims": ["check_claims", "write_script", "plan_scenes", "gather_evidence"],
    "media": ["generate_frames", "check_labels", "translate_script", "render_video", "check_claims", "gather_evidence"],
    "finish": ["generate_frames", "check_labels", "translate_script", "render_video", "check_claims", "finish_short"],
}

TOOLS = {
    "set_checklist": "Set or update the checklist this Short is judged against. args: {items:[{id,text}]} (optional; a default exists).",
    "scope_check": "Check the topic is an anatomy/neuroscience explainer and not medical advice. args: {}",
    "gather_evidence": "Fetch Wikipedia + PubMed sources. Call again to fetch MORE sources if evidence is thin. args: {}",
    "plan_scenes": "Plan the angle and scenes from the sources. args: {}",
    "write_script": "Write the sourced script (every claim cites a source id + verbatim quote). args: {}",
    "check_claims": "Run the claim critic on every line (rewrite/drop unsupported lines) and enforce the length rule. args: {}",
    "translate_script": "Only when language is yo/pcm/ha/ig: translate the VERIFIED script, back-translate it and have the claim critic confirm every line kept its meaning (re-translate up to 2x, then flag). args: {}",
    "generate_frames": "Generate one frame per scene with Muse Image; each frame is gated by SAM (regenerate up to 2x). args: {}",
    "check_labels": "Draw only the labels SAM confirmed and verify none is unconfirmed. args: {}",
    "render_video": "Voiceover, captions and 9:16 render. args: {}",
    "finish_short": "Finish the run. args: {summary: str}",
}

PLAYBOOK = f"""You are the orchestrator of Muse Shorts, an agent that makes sourced, fact-checked educational vertical Shorts.
You do NOT write content yourself. Each turn you choose exactly ONE tool to call next, and you see its result.

Tools:
""" + "\n".join(f"- {k}: {v}" for k, v in TOOLS.items()) + f"""

Procedure (adapt when results tell you to):
1. scope_check first. If the topic is rejected, call finish_short immediately.
2. set_checklist is optional (a default checklist exists).
3. gather_evidence; if it reports thin evidence, you may call it again once.
4. plan_scenes -> write_script -> check_claims. If check_claims reports the script is short of {C.MIN_SECONDS:.0f}s, you may call gather_evidence then check_claims again; never pad.
5. If language is "yo", "pcm", "ha" or "ig": translate_script after check_claims passes (any time before render_video).
6. generate_frames -> check_labels -> render_video -> finish_short. Skip any step listed in "already_done" (e.g. a language remake
   already has verified claims, frames and labels: it only needs translate_script -> render_video -> finish_short).
Rules: tools refuse calls whose preconditions are not met; read the refusal and fix exactly that. Do not repeat a refused call unchanged.
Every result tells you the current "stage" and the "allowed_tools" for it: only call one of those; any other call is refused and logged.
Checks run in layers: deterministic checks first (plan claims map to sources; script schema, a source on every claim, length bounds), then the
claim judge, then the domain policy (health/finance/legal need 100% verified claims; other topics >=90% with unverified claims cut).
A failed check returns "feedback": fix exactly that and retry (plan_scenes again, or write_script then check_claims).
finish_short runs a mandatory final check (claims, labels, duration, captions vs voice, sha256 fingerprints) and refuses if anything fails.

Reply with ONLY a JSON object: {{"tool": "<name>", "args": {{}}, "reason": "<one short sentence>"}}"""


def _short(obs: dict, n: int = 400) -> str:
    s = json.dumps(obs, ensure_ascii=False, default=str)
    return s if len(s) <= n else s[:n] + "…"


class AgentJob(Job):
    """Job driven by the orchestrator loop. Falls back to the fixed pipeline (autopilot) on orchestrator failure."""

    def __init__(self, job_id: str, opts: dict, emit, llm=None):
        super().__init__(job_id, opts, emit)
        self.llm = llm
        self.max_turns = int(opts.get("max_turns") or C.AGENT_MAX_TURNS)
        self.step_mode = bool(opts.get("step_mode"))
        self._step_event = threading.Event()
        self.checklist = [dict(x, status="open") for x in CHECKLIST_DEFAULT]
        self.turns: list[dict] = []
        self.flags: list[str] = []
        self.status = "running"
        self.video_path: Path | None = None
        self.messages: list[dict] = []
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0}
        self.lang = opts.get("language", "en") or "en"
        self.domain: dict | None = None
        self.plan_ok = False
        self.plan_feedback: list[str] | None = None
        self.script_feedback: list[str] | None = None
        self.script_rewrite = False
        self.check_trace: dict[str, list[dict]] = {}
        self.demo_faults = bool(opts.get("demo_faults"))
        self.probe = RND.probe_duration
        if opts.get("resume"):
            self._load(C.OUTPUT_DIR / opts["resume"], reuse_dir=True)
        elif opts.get("remake_from"):
            self._load(C.OUTPUT_DIR / opts["remake_from"], reuse_dir=False)
        if self.lang != "en" and not any(c["id"] == "translation" for c in self.checklist):
            self.checklist.insert(len(self.checklist) - 1, {"id": "translation", "text": "Every translated line back-translates to the verified English meaning", "status": "open"})

    # ---------------- persistence ----------------
    @property
    def state_path(self) -> Path:
        return self.dir / "state.json"

    def snapshot(self) -> dict:
        sc = getattr(self, "sc", None)
        return {"id": self.id, "topic": self.topic, "opts": {k: v for k, v in self.opts.items() if k not in ("resume", "remake_from")},
                "status": self.status, "language": self.opts.get("language", "en"), "updated": time.time(),
                "checklist": self.checklist, "flags": self.flags, "turns": self.turns, "usage": self.usage,
                "scope": sc.__dict__ if sc is not None else None,
                "evidence": [x.public() for x in (getattr(self, "sources", None) or [])],
                "used_queries": getattr(self, "used_queries", None) or [],
                "plan": getattr(self, "plan", None), "script": getattr(self, "script", None),
                "scenes": getattr(self, "scenes", None), "proof": getattr(self, "proof", None),
                "frames": [{"scene": i, "image": s.get("image"), "gate": s.get("gate"), "labeled": s.get("labeled")}
                           for i, s in enumerate(getattr(self, "scenes", None) or [])],
                "video": str(self.video_path.relative_to(C.OUTPUT_DIR)) if self.video_path else None,
                "messages": self.messages, "domain": self.domain, "plan_ok": self.plan_ok, "script_rewrite": self.script_rewrite,
                "check_trace": self.check_trace}

    def save(self):
        self.state_path.write_text(json.dumps(self.snapshot(), indent=1, default=str))

    def _load(self, d: Path, reuse_dir: bool):
        st = json.loads((d / "state.json").read_text())
        if st.get("scope"):
            self.sc = ScopeResult(**st["scope"])
        self.sources = [Source(**x) for x in st.get("evidence") or []] or None
        self.used_queries = st.get("used_queries") or []
        self.plan, self.script, self.scenes, self.proof = st.get("plan"), st.get("script"), st.get("scenes"), st.get("proof")
        self.checklist = st.get("checklist") or self.checklist
        if not any(c["id"] == "final" for c in self.checklist):
            self.checklist.append(dict(CHECKLIST_DEFAULT[-1], status="open"))
        self.domain = st.get("domain")
        self.plan_ok = bool(st.get("plan_ok", bool(self.plan)))
        self.script_rewrite = bool(st.get("script_rewrite"))
        if reuse_dir:   # resume in place: keep everything, including the conversation
            import shutil
            shutil.rmtree(self.dir, ignore_errors=True)
            self.dir, self.rel = d, d.relative_to(C.OUTPUT_DIR).as_posix()
            self.turns, self.messages, self.flags = st.get("turns") or [], st.get("messages") or [], st.get("flags") or []
            self.check_trace = st.get("check_trace") or {}
            self.usage = st.get("usage") or self.usage
            if st.get("video") and (C.OUTPUT_DIR / st["video"]).exists():
                self.video_path = C.OUTPUT_DIR / st["video"]
        else:           # language remake: reuse verified facts (scope, evidence, script, claim verdicts) AND the SAM-gated frames;
            import shutil   # only translate, voice and render are redone
            for s in self.scenes or []:   # a remake of a remake starts again from the verified English
                if s.get("narration_en"):
                    s["narration"] = s.pop("narration_en")
                s.pop("language", None)
                for l in s.get("lines", []):
                    if l.get("text_en"):
                        l["text"] = l.pop("text_en")
                    l.pop("tr", None)
                for k in ("audio_seconds", "start"):
                    s.pop(k, None)
            if self.proof:
                self.proof.pop("translation", None); self.proof.pop("agent", None); self.proof.pop("final_check", None)
                self.proof.pop("verification", None); self.proof.pop("fingerprints", None)
            have = all((d / sub / f"{i + 1:02}.png").exists() for sub in ("frames", "labeled") for i in range(len(self.scenes or [])))
            if self.scenes and have and all(s.get("gate") and s.get("labeled") for s in self.scenes):
                for sub in ("frames", "labeled"):
                    shutil.copytree(d / sub, self.dir / sub, dirs_exist_ok=True)
                for i, s in enumerate(self.scenes):
                    s["image"] = self.url(self.dir / "frames" / f"{i + 1:02}.png")
                    s["labeled"] = self.url(self.dir / "labeled" / f"{i + 1:02}.png")
                reused = "the verified script and its SAM-gated frames"
                self._fp("frames", self._frame_files())   # re-fingerprint the copied, already-approved frames
            else:
                for s in self.scenes or []:
                    for k in ("image", "labeled", "labels", "gate", "gate_found", "quality"):
                        s.pop(k, None)
                for c in self.checklist:
                    if c["id"] == "labels":
                        c["status"] = "open"
                reused = "the verified script (frames will be redrawn)"
            self.flags.append(f"remake of {d.name}: reused {len(self.sources or [])} sources and {reused}")
            for c in self.checklist:
                if c["id"] in ("video", "translation", "final"):
                    c["status"] = "open"
        self.remake = not reuse_dir

    def tick(self, cid: str, status: str = "proven", note: str = ""):
        for c in self.checklist:
            if c["id"] == cid:
                c["status"], c["note"] = status, note

    # ---------------- tools (preconditions live here, not in the prompt) ----------------
    def _claims_ok(self) -> bool:
        p = getattr(self, "proof", None) or {}
        return bool(p) and bool(p.get("all_verified")) and bool(getattr(self, "scenes", None)) \
            and (p.get("policy") or {}).get("ok", True) and not self.script_rewrite

    # ---------------- verification helpers ----------------
    def stage(self) -> str:
        has = lambda k: getattr(self, k, None)
        if not (has("sc") and self.sc.allowed):
            return "scope"
        if not has("sources"):
            return "evidence"
        if not (has("plan") and self.plan_ok) and not has("scenes"):
            return "plan"
        if not has("scenes") or self.script_rewrite:
            return "script"
        if not self._claims_ok():
            return "claims"
        if self.video_path and self.video_path.exists():
            return "finish"
        return "media"

    def allowed_tools(self) -> list[str]:
        st = self.stage()
        tools = ALWAYS + [t for t in STAGE_TOOLS[st] if not (t == "translate_script" and self.lang == "en")]
        return [t for t in TOOLS if t in tools]

    def _trace(self, check: str, ok: bool, feedback=None, **info) -> dict:
        """Record one attempt of a check: fail -> feedback -> retry -> pass is visible in the UI and in the proof."""
        tr = self.check_trace.setdefault(check, [])
        rec = {"attempt": len(tr) + 1, "turn": len(self.turns) + 1, "result": "pass" if ok else "fail",
               "feedback": [str(x)[:240] for x in (feedback or [])][:8], **info}
        tr.append(rec)
        msg = f"{check}: attempt {rec['attempt']} " + ("passed" if ok else "failed — " + "; ".join(rec["feedback"][:2]))
        self.emit("agent", "verify", msg[:400], check=check, attempt=rec["attempt"], result=rec["result"], feedback=rec["feedback"],
                  turn=rec["turn"], trace=self.check_trace)
        if getattr(self, "proof", None) is not None:
            self.proof["verification"] = self.check_trace
        return rec

    def _frame_files(self) -> list[str]:
        n = len(getattr(self, "scenes", None) or [])
        return [f"{sub}/{i + 1:02}.png" for sub in ("frames", "labeled") for i in range(n)]

    def _fp(self, kind: str, rels: list[str]):
        if getattr(self, "proof", None) is None:
            return
        self.proof.setdefault("fingerprints", {})[kind] = V.fingerprint(self.dir, rels)

    def final_check(self) -> dict:
        """Mandatory gate inside finish_short. Re-verifies everything from disk; any failure refuses the finish."""
        p, fails, checks = getattr(self, "proof", None) or {}, [], {}
        checks["claims"] = self._claims_ok() and bool(p.get("all_verified"))
        if not checks["claims"]:
            fails.append("claims: not every claim is verified (or the domain policy failed); run check_claims")
        scenes = getattr(self, "scenes", None) or []
        bad = [l["label"] for s in scenes for l in s.get("labels", []) if l["label"] in ((s.get("gate") or {}).get("dropped") or [])]
        checks["labels"] = bool(scenes) and all(s.get("labeled") for s in scenes) and not bad
        if not checks["labels"]:
            fails.append(f"labels: not every frame label is SAM-approved{(': ' + str(bad)) if bad else ''}")
        dur = float(self.probe(str(self.video_path))) if self.video_path and self.video_path.exists() else 0.0
        short_ok = bool((p.get("length") or {}).get("short"))   # evidence ran out: shorter allowed, never padded (existing rule)
        checks["duration"] = (dur >= C.MIN_SECONDS or (short_ok and dur > 0)) and dur <= C.MAX_SECONDS \
            and (dur <= C.IDEAL_MAX_SECONDS or bool(p.get("all_verified")))
        if not checks["duration"]:
            fails.append(f"duration: {dur:.1f}s is outside {C.MIN_SECONDS:.0f}-{C.IDEAL_MAX_SECONDS:.0f}s (cap {C.MAX_SECONDS:.0f}s)")
        voice = self.dir / "voiceover.wav"
        audio = float(self.probe(str(voice))) if voice.exists() else 0.0
        cm = V.captions_match(self.dir / "captions.srt", " ".join(s.get("narration", "") for s in scenes), audio)
        checks["captions"] = cm["ok"]
        if not cm["ok"]:
            fails.append(f"captions: {cm['detail']}")
        fps = p.get("fingerprints") or {}
        missing = [k for k in ("frames", "media") if not fps.get(k)]
        swapped = [r for k in ("frames", "media") for r in V.changed(self.dir, fps.get(k) or {})]
        checks["fingerprints"] = not missing and not swapped
        if missing:
            fails.append(f"fingerprints: no sha256 recorded for {missing} (the check that records them never passed)")
        if swapped:
            fails.append(f"fingerprints: changed since they passed their check: {swapped[:6]}")
        res = {"ok": not fails, "checks": checks, "failures": fails, "duration": round(dur, 2), "captions": cm}
        p["final_check"] = res
        self._trace("final_check", res["ok"], fails)
        self.tick("final", "proven" if res["ok"] else "open", f"{dur:.0f}s" if res["ok"] else fails[0][:80])
        return res

    def tool(self, name: str, args: dict) -> dict:
        has = lambda k: getattr(self, k, None)
        if name not in TOOLS:
            return {"error": f"Unknown tool '{name}'. Choose one of: {', '.join(self.allowed_tools())}"}
        allowed = self.allowed_tools()
        if name not in allowed and not (self.status == "rejected" and name == "finish_short"):
            st = self.stage()
            msg = f"Refused: {name} is not allowed in stage '{st}'. Allowed now: {', '.join(allowed)}."
            self.emit("agent", "blocked", msg, tool=name, stage=st, allowed=allowed, turn=len(self.turns) + 1)
            return {"error": msg, "stage": st, "allowed_tools": allowed}
        if name == "set_checklist":
            items = args.get("items") or []
            if not isinstance(items, list) or not all(isinstance(i, dict) and i.get("text") for i in items):
                return {"error": "items must be a list of {id, text}"}
            known = {c["id"] for c in self.checklist}
            for i, it in enumerate(items):
                cid = str(it.get("id") or f"item{i + 1}")
                if cid not in known:
                    self.checklist.append({"id": cid, "text": str(it["text"])[:160], "status": "open"})
            return {"ok": True, "checklist": [{"id": c["id"], "status": c["status"]} for c in self.checklist]}
        if name == "scope_check":
            if has("sc") and self.sc.allowed:
                return {"ok": True, "note": "already in scope", "search_queries": self.sc.search_queries}
            self.step_scope()
            if self.status == "rejected":   # the scope guard already told the user; the run ends here
                return {"status": "rejected", "allowed": False, "reason": self.sc.reason, "suggestion": self.sc.suggestion}
            self.tick("scope")
            self.domain = V.classify_domain(self.topic, self.critic)
            self.emit("agent", "domain", f"Domain: {self.domain['domain']} ({'strict: 100% of claims verified' if self.domain['strict'] else f'lenient: >= {self.domain["threshold"]:.0%} verified, the rest cut'}) · {self.domain['layer']}: {self.domain['reason']}",
                      domain=self.domain)
            return {"ok": True, "allowed": True, "search_queries": self.sc.search_queries, "domain": self.domain}
        if name == "finish_short":
            if self.status == "rejected":
                return {"status": "rejected"}
            if not (self.video_path and self.video_path.exists()):
                return {"error": "Refused: no video exists yet. Run render_video first."}
            fc = self.final_check()
            if not fc["ok"]:
                return {"error": "Refused: final check failed: " + "; ".join(fc["failures"]), "feedback": fc["failures"]}
            return {"status": "done", "summary": str(args.get("summary", ""))[:300], "final_check": fc["checks"]}
        if not (has("sc") and self.sc.allowed):
            return {"error": "Refused: run scope_check first; nothing is made before the topic is confirmed in scope."}
        if name == "gather_evidence":
            if has("sources"):
                more = self._more_sources(self.ev or get_evidence(), self.sources, self.sc, self.critic, self.used_queries)
                if more:
                    self.sources.extend(more)
                    if has("gate"):
                        self.gate.add_sources(more)
                    self.emit("evidence", "done", f"Fetched {len(more)} more source(s)", sources=[x.public() for x in self.sources])
                return {"ok": True, "added": len(more), "sources": len(self.sources), "chars": sum(len(x.text) for x in self.sources)}
            self.step_evidence()
            self.tick("sources")
            chars = sum(len(x.text) for x in self.sources)
            return {"ok": True, "sources": [f"{x.id} {x.title[:60]}" for x in self.sources], "chars": chars,
                    "thin": chars < C.MIN_SOURCE_CHARS}
        if not has("sources"):
            return {"error": "Refused: no evidence yet. Call gather_evidence first; every line must cite a source."}
        if name == "plan_scenes":
            self.step_plan()
            if self.demo_faults and not self.check_trace.get("plan_check") and self.plan.get("claims"):
                self.plan["claims"][0]["source_id"] = "S99"   # demo fault injection: a planned claim with no gathered source
            pc = V.plan_check(self.plan, self.sources)
            self.plan_ok = pc["ok"]
            self.plan_feedback = None if pc["ok"] else pc["failures"]
            self._trace("plan_check", pc["ok"], pc["failures"], checked=pc["checked"])
            if not pc["ok"]:
                return {"error": "Plan check failed: planned claims must map to gathered evidence. Call plan_scenes again.",
                        "feedback": pc["failures"]}
            return {"ok": True, "title": self.plan.get("title"), "angle": self.plan.get("angle"), "claims_mapped": pc["checked"]}
        if name == "write_script":
            if not (has("plan") and self.plan_ok):
                return {"error": "Refused: the plan check has not passed. Call plan_scenes first.", "feedback": self.plan_feedback}
            self.step_script(); self.proof = None; self.script_rewrite = False; self.script_feedback = None
            for c in ("claims", "length", "labels", "video"):
                self.tick(c, "open")
            return {"ok": True, "scenes": len(self.scenes), "claims": sum(1 for x in self.scenes for l in x["lines"] if l["kind"] == "claim"),
                    "estimated_seconds": round(L_.estimate_seconds(self.scenes), 1), "note": "unverified until check_claims passes"}
        if name == "check_claims":
            if not has("scenes"):
                return {"error": "Refused: write_script first."}
            if self.script_rewrite:
                return {"error": "Refused: the last check failed; write_script again first.", "feedback": self.script_feedback}
            if self.demo_faults and not self.check_trace.get("script_checks"):
                for l in (x for s in self.scenes for x in s["lines"] if x["kind"] == "claim"):
                    l["source_id"] = None; break   # demo fault injection: a claim line without a source
            sc_ = V.script_checks(self.scenes, self.sources)
            self._trace("script_checks", sc_["ok"], sc_["failures"], estimated_seconds=round(sc_["estimated_seconds"], 1))
            if not sc_["ok"]:   # deterministic layer failed: the model judge is not even called
                self.script_rewrite, self.script_feedback = True, sc_["failures"]
                return {"error": "Deterministic script checks failed (the claim judge did not run). Call write_script again.",
                        "feedback": sc_["failures"]}
            if has("proof") and self.proof.get("all_verified") and (self.proof.get("policy") or {}).get("ok", True) \
                    and (self.proof.get("translation") or not self.proof.get("length", {}).get("short")):
                return {"ok": True, "note": "claims already verified; nothing to re-check", "claims": self.proof.get("claims_final")}
            if has("proof"):   # re-check after more evidence: the critic re-runs on the current script
                self.gate = ClaimGate(self.critic, self.writer, self.sources, self.emit, max_rounds=C.MAX_CLAIM_ROUNDS)
            self.step_claims()
            p, ln = self.proof, self.proof.get("length", {})
            pol = V.claim_policy(p, self.domain or V.policy_for("general") | {"layer": "default", "reason": "unclassified"})
            p["policy"] = pol
            # the judge's own fail -> rewrite -> re-check rounds inside the gate are attempts too: show them in the trace
            for r in [r for r in (p.get("rounds") or []) if r.get("rejected")]:
                self._trace("claim_judge", False, [f"round {r['round']}: {len(r['rejected'])}/{r['checked']} lines rejected, rewriting from sources"]
                            + r["rejected"], round=r["round"])
            self._trace("claim_judge", pol["ok"], [] if pol["ok"] else
                        [f"{pol['verified']}/{pol['verified'] + pol['unverified']} claims verified ({pol['ratio']:.0%}); {pol['domain']} needs >= {pol['threshold']:.0%}"]
                        + [f"cut: {c[:120]}" for c in pol["cut"]], domain=pol["domain"], ratio=pol["ratio"])
            if not pol["ok"]:
                self.script_rewrite = True
                self.script_feedback = [f"only {pol['ratio']:.0%} of claims verified; {pol['domain']} needs {pol['threshold']:.0%}. "
                                        "Use only facts stated in the sources"] + [f"unsupported: {c[:120]}" for c in pol["cut"]]
                self.tick("claims", "open", f"{pol['ratio']:.0%} verified")
                return {"error": f"Claim policy failed for a {pol['domain']} topic: {pol['ratio']:.0%} verified, needs {pol['threshold']:.0%}. "
                                 "Call write_script again (or gather_evidence first).", "feedback": self.script_feedback}
            self.tick("claims", "proven" if p.get("all_verified") else "open", f"{p.get('claims_final')} claims")
            self.tick("length", "open" if ln.get("short") else "proven", f"~{ln.get('estimated_seconds', 0):.0f}s")
            if ln.get("short"):
                self.flags.append(f"script short: ~{ln.get('estimated_seconds', 0):.0f}s (evidence ran out; not padded)")
            return {"ok": True, "all_verified": p.get("all_verified"), "claims": p.get("claims_final"), "rewritten": p.get("rewritten"),
                    "policy": {k: pol[k] for k in ("domain", "ratio", "threshold", "cut")},
                    "dropped": p.get("dropped"), "estimated_seconds": round(ln.get("estimated_seconds", 0), 1), "short_of_minimum": bool(ln.get("short"))}
        if name == "translate_script":
            if self.lang == "en":
                return {"error": "Refused: language is English; nothing to translate. Continue with generate_frames / render_video."}
            if not self._claims_ok():
                return {"error": "Refused: only a verified script is translated. Run check_claims first."}
            if self.proof.get("translation"):
                return {"ok": True, "note": "already translated", **{k: self.proof["translation"][k] for k in ("lines", "verified_same", "flagged")}}
            self.step_translate()
            t = self.proof["translation"]
            self.tick("translation", "open" if t["flagged"] else "proven", f"{t['verified_same']}/{t['lines']} lines")
            if t["flagged"]:
                self.flags.append(f"translation: {len(t['flagged'])} line(s) still differ after 2 re-translations: {t['flagged']}")
            return {"ok": True, "language": t["language"], "lines": t["lines"], "verified_same": t["verified_same"],
                    "rewritten": t["rewritten"], "flagged": t["flagged"]}
        if name == "generate_frames":
            if not self._claims_ok():
                return {"error": "Refused: claims are not verified. Run check_claims first; no frame is drawn for an unverified script."}
            self.step_frames()
            v = self.proof["visuals"]
            return {"ok": True, "frames": v["frames"], "first_try": v["first_try"], "regenerated": v["regenerated"], "labels_dropped": v["labels_dropped"]}
        if name == "check_labels":
            if not (has("scenes") and all(s.get("gate") for s in self.scenes)):
                return {"error": "Refused: frames are not generated and SAM-gated yet. Run generate_frames first."}
            self.step_labels()
            bad = [l["label"] for s in self.scenes for l in s.get("labels", []) if l["label"] in (s["gate"].get("dropped") or [])]
            self._trace("labels", not bad, [f"unconfirmed label: {b}" for b in bad])
            if bad:
                return {"error": f"Unconfirmed labels found: {bad}"}
            self._fp("frames", self._frame_files())
            self.tick("labels", "proven", f"{sum(len(s['labels']) for s in self.scenes)} labels")
            return {"ok": True, "labels": sum(len(s["labels"]) for s in self.scenes), "dropped": sum(len(s["gate"].get("dropped") or []) for s in self.scenes)}
        if name == "render_video":
            if not self._claims_ok():
                return {"error": "Refused: render needs verified claims. Run check_claims first."}
            if not all(s.get("labeled") for s in self.scenes):
                return {"error": "Refused: labels not checked. Run check_labels (after generate_frames) first."}
            if self.lang != "en" and not self.proof.get("translation"):
                return {"error": f"Refused: language is '{self.lang}' but the script is still English. Run translate_script first."}
            self.step_render()
            self.video_path = self.dir / "video.mp4"
            d = self.final["duration"]
            voice = self.dir / "voiceover.wav"
            cm = V.captions_match(self.dir / "captions.srt", " ".join(s.get("narration", "") for s in self.scenes),
                                  float(self.probe(str(voice))) if voice.exists() else 0.0)
            self._trace("render", cm["ok"], [] if cm["ok"] else [f"captions: {cm['detail']}"], duration=round(d, 1))
            if not cm["ok"]:
                return {"error": f"Render check failed: {cm['detail']}. Call render_video again.", "feedback": [cm["detail"]]}
            self._fp("media", ["video.mp4", "voiceover.wav", "voiceover.mp3", "captions.srt"])
            self.tick("video", "proven", f"{d:.1f}s")
            if d < C.MIN_SECONDS:
                self.flags.append(f"video {d:.1f}s is under the {C.MIN_SECONDS:.0f}s minimum")
            return {"ok": True, "duration": round(d, 1), "meets_minimum": d >= C.MIN_SECONDS}
        return {"error": "unreachable"}

    # ---------------- the loop ----------------
    def decide(self, turn: int) -> dict:
        if self.llm is None:
            from ..providers.baseten import baseten_llm
            self.llm = baseten_llm(C.AGENT_REASONING)
        if not self.messages:
            self.messages = [{"role": "system", "content": PLAYBOOK},
                             {"role": "user", "content": json.dumps({"topic": self.topic, "language": self.opts.get("language", "en"),
                                                                     "checklist": self.checklist, "turn_limit": self.max_turns,
                                                                     "already_done": self._done_summary(),
                                                                     "stage": self.stage(), "allowed_tools": self.allowed_tools()})}]
        msgs = list(self.messages)
        if turn >= self.max_turns - 1:
            msgs.append({"role": "user", "content": "LAST TURNS: finish now. If a video exists call finish_short; otherwise call the next step that leads to a video."})
        err = None
        for _ in range(MAX_RETRIES):
            c = self.llm.chat_full(msgs)
            if c.usage:
                self.usage["prompt_tokens"] += int(c.usage.get("prompt_tokens") or 0)
                self.usage["completion_tokens"] += int(c.usage.get("completion_tokens") or 0)
            for text in (c.content, c.reasoning):
                try:
                    d = extract_json(text)
                    if isinstance(d.get("tool"), str):
                        self.messages.append({"role": "assistant", "content": json.dumps({k: d.get(k) for k in ("tool", "args", "reason")})})
                        return {"tool": d["tool"], "args": d.get("args") or {}, "reason": str(d.get("reason", ""))[:300]}
                except Exception as e:  # noqa: BLE001
                    err = e
            msgs = msgs + [{"role": "user", "content": 'Reply with ONLY {"tool": ..., "args": {}, "reason": ...}.'}]
        raise RuntimeError(f"orchestrator returned no usable tool choice ({err})")

    def _done_summary(self) -> list[str]:
        out = []
        if getattr(self, "sc", None) and self.sc.allowed: out.append("scope_check passed")
        if getattr(self, "sources", None): out.append(f"{len(self.sources)} sources gathered")
        if getattr(self, "scenes", None): out.append(f"script with {len(self.scenes)} scenes")
        if self._claims_ok(): out.append("claims verified")
        if getattr(self, "scenes", None) and all(s.get("gate") for s in self.scenes): out.append("frames generated and SAM-gated")
        if getattr(self, "scenes", None) and all(s.get("labeled") for s in self.scenes): out.append("labels checked")
        if (getattr(self, "proof", None) or {}).get("translation"): out.append("script translated")
        return out

    def step_gate(self, turn: int):
        if self.step_mode:
            self.emit("agent", "paused", f"Turn {turn}: waiting for you to step", turn=turn)
            self._step_event.wait(); self._step_event.clear()

    def advance(self):
        self._step_event.set()

    def run(self):
        self.setup()
        self.emit("job", "start", self.topic, dir=self.rel, mode="agent", max_turns=self.max_turns,
                  steps=[{"id": "agent", "title": "Orchestrator: choose the next tool", "tool": "Muse Spark Open"}]
                  + [{"id": a, "title": b, "tool": c} for a, b, c in steps_for(self.opts.get("language", "en"))], providers=self.providers(),
                  checklist=self.checklist)
        try:
            self.loop()
        except MissingLineError as e:
            self.stop_missing_line(e)
        except Exception as e:  # orchestrator failure -> fixed pipeline, continuing from what is already on disk
            traceback.print_exc()
            self.flags.append(f"orchestrator failed: {str(e)[:160]}; autopilot finished the run")
            self.emit("agent", "fallback", f"Orchestrator failed ({str(e)[:160]}). Switching to the fixed pipeline.", turn=len(self.turns))
            try:
                self.autopilot()
            except MissingLineError as e2:
                self.stop_missing_line(e2)
            except Exception as e2:  # noqa: BLE001
                traceback.print_exc()
                self.status = "error"; self.save_safe()
                self.emit("error", "error", str(e2)[:600])

    def stop_missing_line(self, e: "MissingLineError"):
        """Hard stop (Isah, Oct 29): a yo/ha/ig Short is never voiced by a fallback engine."""
        self.status = "error"
        self.flags.append(f"stopped: {e}")
        self.save_safe()
        self.emit("error", "error", f"Stopped: {e}", missing={"lang": e.lang, "hash": e.hash, "text": e.text})

    def autopilot(self):
        """Fixed order, still through the same tools, allowlist and checks (incl. the final check); each tool retried at most 3x."""
        order = ["scope_check", "gather_evidence", "plan_scenes", "write_script", "check_claims", "translate_script", "generate_frames",
                 "check_labels", "render_video", "finish_short"]
        skip = {"scope_check": lambda: getattr(self, "sc", None) and self.sc.allowed,
                "gather_evidence": lambda: getattr(self, "sources", None),
                "plan_scenes": lambda: (getattr(self, "plan", None) and self.plan_ok) or getattr(self, "scenes", None),
                "write_script": lambda: getattr(self, "scenes", None) and not self.script_rewrite, "check_claims": self._claims_ok,
                "translate_script": lambda: self.lang == "en" or bool((getattr(self, "proof", None) or {}).get("translation")),
                "generate_frames": lambda: getattr(self, "scenes", None) and all(s.get("gate") for s in self.scenes),
                "check_labels": lambda: getattr(self, "scenes", None) and all(s.get("labeled") for s in self.scenes)
                                        and (self.proof or {}).get("fingerprints", {}).get("frames"),
                "render_video": lambda: self.video_path and self.video_path.exists()
                                        and (self.proof or {}).get("fingerprints", {}).get("media"),
                "finish_short": lambda: False}
        fails: dict[str, int] = {}
        for _ in range(4 * len(order)):
            t = next(x for x in order if not skip[x]())
            obs = self.tool(t, {"summary": "autopilot"} if t == "finish_short" else {})
            self._log(len(self.turns) + 1, t, "autopilot", obs, by="autopilot")
            if self.status == "rejected":
                return self._end("rejected")
            if obs.get("error"):
                fails[t] = fails.get(t, 0) + 1
                if fails[t] >= MAX_RETRIES:
                    raise RuntimeError(obs["error"])
                continue
            if obs.get("status") == "done":
                return self._end("done", obs.get("summary", ""))
        raise RuntimeError("autopilot did not converge")

    def save_safe(self):
        if self.dir.exists():
            self.save()

    def _log(self, turn, tool, reason, obs, by="model"):
        refused = bool(obs.get("error"))
        rec = {"turn": turn, "tool": tool, "reason": reason, "by": by, "refused": refused, "observation": _short(obs, 600), "t": time.time()}
        self.turns.append(rec)
        self.emit("agent", "observation", ("Refused: " if refused else "") + _short(obs, 220), turn=turn, tool=tool, refused=refused, by=by,
                  checklist=self.checklist, observation=_short(obs, 600))
        self.save_safe()

    def loop(self):
        fails: dict[str, int] = {}
        start = len(self.turns)
        for turn in range(start + 1, start + self.max_turns + 1):
            self.step_gate(turn)
            d = self.decide(turn - start)
            tool, args, reason = d["tool"], d["args"], d["reason"]
            self.emit("agent", "decision", f"Turn {turn}: {tool} — {reason}", turn=turn, tool=tool, args=args, reason=reason,
                      max_turns=self.max_turns)
            try:
                obs = self.tool(tool, args if isinstance(args, dict) else {})
            except MissingLineError:   # yo/ha/ig line without pre-rendered audio: stop, never fall back to another voice
                raise
            except Exception as e:  # a tool crash is data for the model, not the end of the run
                traceback.print_exc()
                obs = {"error": f"{tool} failed: {str(e)[:300]}"}
            self._log(turn, tool, reason, obs)
            self.messages.append({"role": "user", "content": json.dumps({"turn": turn, "tool": tool, "result": obs, "stage": self.stage(),
                                                                         "allowed_tools": self.allowed_tools()}, default=str)[:4000]})
            if obs.get("error"):
                fails[tool] = fails.get(tool, 0) + 1
                if fails[tool] >= MAX_RETRIES:   # capped: escalate instead of looping
                    self.flags.append(f"escalated: {tool} failed {MAX_RETRIES}x: {obs['error'][:160]}")
                    self.emit("agent", "escalate", f"{tool} failed {MAX_RETRIES} times in a row. Escalating.", turn=turn, tool=tool)
                    raise RuntimeError(f"{tool} failed {MAX_RETRIES} times")
            else:
                fails[tool] = 0
            if obs.get("status") in ("done", "rejected"):
                return self._end(obs["status"], obs.get("summary", ""))
        # turn limit reached without finish_short
        self.flags.append(f"turn limit {self.max_turns} reached")
        if self.video_path and self.video_path.exists():
            obs = self.tool("finish_short", {"summary": "turn limit reached; video already rendered"})
            self._log(len(self.turns) + 1, "finish_short", "turn limit: final check", obs, by="autopilot")
            if obs.get("status") == "done":
                return self._end("done", obs["summary"])
            raise RuntimeError(f"turn limit {self.max_turns} reached and the final check failed")
        raise RuntimeError(f"turn limit {self.max_turns} reached without a video")

    def _end(self, status: str, summary: str = ""):
        self.status = status
        if status == "rejected":
            return   # step_scope already emitted job/rejected and removed the run folder
        agent = {"turns": len(self.turns), "tools": [t["tool"] for t in self.turns], "refusals": sum(t["refused"] for t in self.turns),
                 "checklist": self.checklist, "flags": self.flags, "usage": self.usage, "summary": summary,
                 "state": f"/outputs/{self.rel}/state.json"}
        self.final["proof"]["agent"] = agent
        sp = self.dir / "share.json"
        if sp.exists():
            d = json.loads(sp.read_text()); d["proof"] = self.final["proof"]; sp.write_text(json.dumps(d))
        self.save()
        self.emit("job", "done", "Your Short is ready", id=self.id, agent=agent, **self.final)


def make_job(job_id: str, opts: dict, emit, llm=None):
    mode = (opts.get("mode") or C.AGENT_MODE).lower()
    if mode == "fixed" or opts.get("stop_after"):
        return Job(job_id, opts, emit)
    return AgentJob(job_id, opts, emit, llm=llm)
