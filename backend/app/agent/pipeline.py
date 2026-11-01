"""The Muse Shorts agent: plan -> write -> self-review -> visuals -> frame QA -> segment/label -> voice -> captions -> render."""
from __future__ import annotations
import json, re, shutil, time, traceback, zipfile, difflib
from pathlib import Path
from typing import Callable
import numpy as np
from PIL import Image, ImageFilter
from .. import config as C
from ..providers import registry
from ..media import tts, labels as L, captions as cap, render as R
from . import prompts as P
from . import scope as S
from . import length as L_
from .claims import ClaimGate, normalise_scenes, set_narration
from .evidence import get_evidence, llm_judge
from .gate import ImageGate
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

STATE_KEYS = ("sc", "ev", "sources", "used_queries", "plan", "script", "scenes", "gate", "proof", "review", "gated")

STEPS = [
    ("scope", "Scope guard", "Muse Spark"),
    ("evidence", "Gather sources", "Wikipedia + PubMed"),
    ("plan", "Plan the Short", "Muse Spark"),
    ("script", "Write sourced script", "Muse Spark"),
    ("claims", "Claim critic: check every line", "Muse Spark Open"),
    ("visuals", "Generate visuals", "Muse Image / Z-Image"),
    ("frame_qa", "SAM gate: find every structure", "SAM 3.1"),
    ("segment", "Label confirmed structures", "SAM 3.1"),
    ("translate", "Translate + back-translation check", "Muse Spark Open"),
    ("voice", "Record voiceover", "Kokoro / Meta MMS-TTS"),
    ("captions", "Transcribe & caption", "Muse Voice Transcribe"),
    ("render", "Render 9:16 video", "ffmpeg"),
]

def steps_for(lang: str) -> list:
    return [x for x in STEPS if x[0] != "translate" or (lang or "en") != "en"]

def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:48] or "short"

def frame_quality(path: str) -> dict:
    g = Image.open(path).convert("L").resize((270, 480))
    a = np.asarray(g, dtype=np.float32)
    edges = np.asarray(g.filter(ImageFilter.FIND_EDGES), dtype=np.float32)
    q = {"brightness": float(a.mean()), "contrast": float(a.std()), "detail": float(edges.var())}
    q["ok"] = 12 < q["brightness"] < 235 and q["contrast"] > 14 and q["detail"] > 20
    return q

class Job:
    def __init__(self, job_id: str, opts: dict, emit: Callable[[dict], None]):
        self.id, self.opts, self._emit = job_id, opts, emit
        self.topic = opts["topic"].strip()
        lang = opts.get("language", "en") or "en"
        self.dir = C.OUTPUT_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}-{slug(self.topic)}{'' if lang == 'en' else '-' + lang}"
        for sub in ("frames", "labeled", "audio", "work"):
            (self.dir / sub).mkdir(parents=True, exist_ok=True)
        self.rel = self.dir.relative_to(C.OUTPUT_DIR).as_posix()

    def emit(self, step, status, message="", **data):
        self._emit({"step": step, "status": status, "message": message, "t": time.time(), **data})

    def url(self, p: Path) -> str:
        return f"/outputs/{p.relative_to(C.OUTPUT_DIR).as_posix()}"

    def run(self):
        try:
            self._run()
        except Exception as e:
            traceback.print_exc()
            self.emit("error", "error", str(e)[:600])

    # ---- length rule: >= MIN_SECONDS, never padded
    def _more_sources(self, ev, sources, sc, critic, used_queries):
        topic = sc.topic_clean or self.topic
        try:
            qs = critic.complete_json(P.MORE_QUERIES, json.dumps({"topic": topic, "used_queries": used_queries, "have": [x.title for x in sources]}),
                                      P.MORE_QUERIES_SCHEMA).get("queries") or []
        except Exception:  # noqa: BLE001
            qs = []
        qs = [str(q) for q in qs if str(q).strip()][:3] or [f"{topic} physiology", f"{topic} anatomy function", f"{topic} mechanism"]
        used_queries.extend(qs)
        try:
            return ev.expand(sources, qs, topic=topic, judge=llm_judge(critic) if C.EVIDENCE_PROVIDER == "web" else None)
        except Exception:  # noqa: BLE001 — never lose the run because extra sources could not be fetched
            return []

    def _lengthen(self, scenes, gate, sources, ev, sc, critic, writer, plan, proof, used_queries, topic):
        info = {"min_seconds": C.MIN_SECONDS, "rounds": 0, "extra_sources": [], "added_scenes": 0, "short": False}
        expansions = 0
        for rnd in range(1, C.LENGTH_ROUNDS + 1):
            short = L_.seconds_short(scenes)
            if short <= 0:
                break
            info["rounds"] = rnd
            est = L_.estimate_seconds(scenes)
            need_words = int(short / (C.WORD_SEC + 0.03) * 1.15) + 6
            self.emit("claims", "retry", f"Script is about {est:.0f}s, under the {C.MIN_SECONDS:.0f}s minimum after fact-checking: writing replacement sourced lines (~{need_words} words)",
                      kind="length", round=rnd, estimated_seconds=est, need_seconds=short, need_words=need_words)
            dropped = [c["before"] for c in proof.get("corrections", []) if c.get("action") == "dropped"]
            before_est = est
            try:
                ext = writer.complete_json(P.EXTEND_SOURCED, json.dumps({
                    "topic": topic, "plan": plan, "need_seconds": short, "need_words": need_words,
                    "current_script": [{"scene": i + 1, "lines": [l["text"] for l in x["lines"]]} for i, x in enumerate(scenes)],
                    "dropped_points": dropped, "sources": [{"id": x.id, "title": x.title, "text": x.text} for x in sources]}), P.EXTEND_SOURCED_SCHEMA)
            except Exception as e:  # noqa: BLE001
                ext = {}
                self.emit("claims", "retry", f"Replacement writer call failed ({str(e)[:120]})", kind="length_error", round=rnd)
            new = normalise_scenes(ext.get("scenes", []))
            if new:
                for sn in new:
                    set_narration(sn)
                scenes[len(scenes) - 1:len(scenes) - 1] = new     # before the closing scene (which carries the CTA)
                st = gate.run(scenes)
                for k in ("claims", "framing", "supported_first_try", "rewritten", "dropped", "checks", "deduped"):
                    proof[k] = proof.get(k, 0) + st.get(k, 0)
                proof.setdefault("corrections", []).extend(st.get("corrections", []))
                proof["claims_final"], proof["all_verified"] = st["claims_final"], st["all_verified"]
                info["added_scenes"] += len(new)
            gained = L_.estimate_seconds(scenes) - before_est
            if L_.seconds_short(scenes) > 0 and expansions < 2 and gained < 0.6 * short:
                more = self._more_sources(ev, sources, sc, critic, used_queries)
                expansions += 1
                if more:
                    sources.extend(more); gate.add_sources(more)
                    info["extra_sources"] += [x.id for x in more]
                    self.emit("claims", "retry", f"Not enough verified material: fetched {len(more)} more source(s): " + ", ".join(f"{x.id} {x.title[:50]}" for x in more),
                              kind="more_sources", sources=[x.public() | {"text": x.text[:300]} for x in more])
                elif not new:
                    break
            elif not new:
                break
        cut = L_.trim_to_max(scenes)
        if cut:
            self.emit("claims", "retry", f"Script ran past {C.MAX_SECONDS:.0f}s: cut {cut} scene(s) before the closing one", kind="length_cut")
            for sn in scenes: set_narration(sn)
        est = L_.estimate_seconds(scenes)
        info.update(estimated_seconds=est, words=L_.total_words(scenes), scenes=len(scenes), cut=cut)
        if est < C.MIN_SECONDS:
            info["short"] = True
            self.emit("claims", "retry", f"Verified evidence ran out at about {est:.0f}s (minimum {C.MIN_SECONDS:.0f}s). Not padding: continuing with what the sources support.", kind="length_short")
        proof["length"] = info

    STATE = None

    def setup(self):
        self.writer, self.critic = registry.llm("writer"), registry.llm("critic")
        self.img_gen, self.seg, self.asr = registry.image(), registry.segmenter(), registry.asr()
        self.status = "running"
        if getattr(self, "used_queries", None) is None:
            self.used_queries = []

    def providers(self) -> dict:
        return {"writer": self.writer.name, "critic": self.critic.name, "image": self.img_gen.name, "segment": self.seg.name,
                "tts": tts.engine_name(self.opts.get("language", "en") or "en"), "asr": self.asr.name}

    def _store(self, loc: dict):
        for k in STATE_KEYS:
            if k in loc and loc[k] is not None:
                setattr(self, k, loc[k])

    def step_scope(self):
        """Scope guard: anatomy / neuroscience explainers only."""
        o, writer, critic, img_gen, seg, asr = self.opts, self.writer, self.critic, self.img_gen, self.seg, self.asr
        sc, ev, sources, used_queries, plan, script, scenes, gate, proof, review, gated = (getattr(self, k, None) for k in STATE_KEYS)
        _save = self._store
        # 0. SCOPE GUARD — anatomy / neuroscience explainers only; no medical advice
        self.emit("scope", "running", "Checking the topic is an explainer, not medical advice…")
        sc = S.check(self.topic, critic)
        if not sc.allowed:
            self.emit("scope", "rejected", sc.reason, category=sc.category, suggestion=sc.suggestion, layer=sc.layer, reasoning=sc.reasoning[:700])
            self.emit("job", "rejected", sc.reason, category=sc.category, suggestion=sc.suggestion)
            shutil.rmtree(self.dir, ignore_errors=True)
            self.status = "rejected"
            _save(locals()); return
        self.emit("scope", "done", f"In scope · searching: {' | '.join(sc.search_queries)}", category="ok", layer=sc.layer,
                  search_queries=sc.search_queries, reasoning=sc.reasoning[:700])

        _save(locals())

    def step_evidence(self):
        """Wikipedia + PubMed evidence (adds more sources if already gathered)."""
        o, writer, critic, img_gen, seg, asr = self.opts, self.writer, self.critic, self.img_gen, self.seg, self.asr
        sc, ev, sources, used_queries, plan, script, scenes, gate, proof, review, gated = (getattr(self, k, None) for k in STATE_KEYS)
        _save = self._store
        # 1. EVIDENCE — Wikipedia + PubMed; every source gets an id the script must cite
        ev = get_evidence()
        self.emit("evidence", "running", f"Searching {ev.name}…")
        sources = ev.gather(sc.search_queries, topic=sc.topic_clean or self.topic, judge=llm_judge(critic) if C.EVIDENCE_PROVIDER == "web" else None)
        if not sources:
            raise RuntimeError("No sources found for this topic, so there is nothing to fact-check against. Try a more specific anatomy or neuroscience topic.")
        used_queries = list(sc.search_queries)
        if sum(len(x.text) for x in sources) < C.MIN_SOURCE_CHARS:   # too thin for 45+ s: fetch more sources before writing anything
            more = self._more_sources(ev, sources, sc, critic, used_queries)
            sources = sources + more
            if more:
                self.emit("evidence", "running", f"Evidence was thin, fetched {len(more)} more source(s)")
        for src in sources:
            self.emit("evidence", "progress", f"{src.id} · {src.title}", source=src.public() | {"text": src.text[:300]}, progress=0.5)
        self.emit("evidence", "done", f"{len(sources)} sources: " + ", ".join(f"{x.id}" for x in sources), sources=[x.public() for x in sources])
        (self.dir / "sources.json").write_text(json.dumps([x.public() for x in sources], indent=2))

        _save(locals())

    def step_plan(self):
        """Plan the Short from the sources."""
        o, writer, critic, img_gen, seg, asr = self.opts, self.writer, self.critic, self.img_gen, self.seg, self.asr
        sc, ev, sources, used_queries, plan, script, scenes, gate, proof, review, gated = (getattr(self, k, None) for k in STATE_KEYS)
        _save = self._store
        # 2. PLAN (grounded in the sources)
        self.emit("plan", "running", f"Thinking about the best angle with {writer.name}…")
        brief = [{"id": x.id, "title": x.title, "text": x.text[:350]} for x in sources]
        plan = writer.complete_json(P.PLAN, json.dumps({"topic": sc.topic_clean or self.topic, "target_seconds": max(55, min(int(o.get("seconds", 60)), 90)), "sources": brief}
                                                    | ({"feedback": self.plan_feedback} if getattr(self, "plan_feedback", None) else {})), P.PLAN_SCHEMA)
        self.emit("plan", "done", plan.get("angle", ""), plan=plan)

        _save(locals())

    def step_script(self):
        """Write the sourced script."""
        o, writer, critic, img_gen, seg, asr = self.opts, self.writer, self.critic, self.img_gen, self.seg, self.asr
        sc, ev, sources, used_queries, plan, script, scenes, gate, proof, review, gated = (getattr(self, k, None) for k in STATE_KEYS)
        _save = self._store
        # 3. SOURCED SCRIPT — every line is a claim with source_id + verbatim quote, or pure framing
        self.emit("script", "running", "Writing narration where every claim cites a source…")
        script = writer.complete_json(P.WRITE_SOURCED, json.dumps({"topic": sc.topic_clean or self.topic, "plan": plan,
                                      "sources": [{"id": x.id, "title": x.title, "text": x.text} for x in sources]}
                                      | ({"feedback": self.script_feedback} if getattr(self, "script_feedback", None) else {})), P.WRITE_SOURCED_SCHEMA)
        scenes = normalise_scenes(script.get("scenes", []))
        if len(scenes) < 3:
            raise RuntimeError("The writer returned too few usable scenes.")
        for sn in scenes:
            set_narration(sn)
        self.emit("script", "done", f"{len(scenes)} scenes · {sum(1 for x in scenes for l in x['lines'] if l['kind'] == 'claim')} sourced claims drafted",
                  scenes=scenes)

        _save(locals())

    def step_claims(self):
        """Claim critic + length rule."""
        o, writer, critic, img_gen, seg, asr = self.opts, self.writer, self.critic, self.img_gen, self.seg, self.asr
        sc, ev, sources, used_queries, plan, script, scenes, gate, proof, review, gated = (getattr(self, k, None) for k in STATE_KEYS)
        _save = self._store
        # 4. CLAIM CRITIC — check each line vs its source; rewrite or drop what is unsupported (retries are visible)
        self.emit("claims", "running", "Checking every claim against its source…")
        gate = ClaimGate(critic, writer, sources, self.emit, max_rounds=C.MAX_CLAIM_ROUNDS)
        proof = gate.run(scenes)
        self._lengthen(scenes, gate, sources, ev, sc, critic, writer, plan, proof, used_queries, sc.topic_clean or self.topic)
        proof["sources"] = [{"id": x.id, "title": x.title, "url": x.url, "kind": x.kind} for x in sources]
        if len(scenes) < 3:
            raise RuntimeError("After fact-checking, too little verified material was left for a Short. Try a broader topic.")
        self.emit("claims", "done", f"{proof['claims_final']} claims verified · {proof['rewritten']} rewritten · {proof['dropped']} dropped",
                  proof=proof, scenes=scenes)
        (self.dir / "proof.json").write_text(json.dumps({"topic": self.topic, "proof": proof, "scenes": scenes}, indent=2))
        review = {"approved": True, "score": None, "notes": "fact-checked by claim critic", "issues": []}
        _save(locals())

    def step_translate(self):
        """Translation gate (yo / pcm): translate the verified script, back-translate, critic checks meaning."""
        lang = self.opts.get("language", "en") or "en"
        if lang == "en":
            return
        from .translate import translate_scenes
        self.proof["translation"] = translate_scenes(self.scenes, lang, self.writer, self.critic, self.emit)
        (self.dir / "proof.json").write_text(json.dumps({"topic": self.topic, "proof": self.proof, "scenes": self.scenes}, indent=2, ensure_ascii=False))

    def step_frames(self):
        """Generate frames behind the SAM gate."""
        o, writer, critic, img_gen, seg, asr = self.opts, self.writer, self.critic, self.img_gen, self.seg, self.asr
        sc, ev, sources, used_queries, plan, script, scenes, gate, proof, review, gated = (getattr(self, k, None) for k in STATE_KEYS)
        _save = self._store
        # 4. VISUALS + SAM GATE: a frame passes only if SAM finds every structure it must show; else regenerate, else drop that label
        self.emit("visuals", "running", f"Generating {len(scenes)} frames with {img_gen.name}…")
        self.emit("frame_qa", "running", f"{seg.name} gate: every structure must be found (up to {C.GATE_MAX_REGEN} regenerations, then the label is dropped)")
        t_vis = time.time()
        igate = ImageGate(img_gen, seg, self.emit, self.url, quality=frame_quality)
        gated: dict[int, object] = {}

        def make_prompt_for(s):
            structs = s.get("structures") or ["subject"]
            def make(missing, attempt):
                base = f"{s['visual_prompt']}, {P.STYLE} — clearly showing: {', '.join(structs)}"
                return base + (f". Show {', '.join(missing)} as a single whole object in full view, centered, large and sharp, with empty dark space around it, "
                               f"clearly separated from everything else (not a close-up, not a texture)" if missing else "")
            return make

        def do_scene(i):
            s = scenes[i]
            res = igate.run_scene(i, [x for x in (s.get("structures") or [])[:3]], make_prompt_for(s),
                                 self.dir / "frames" / f"{i + 1:02}.png", self.dir / "frames" / "attempts")
            s["image"] = self.url(self.dir / "frames" / f"{i + 1:02}.png")
            s["quality"] = frame_quality(str(self.dir / "frames" / f"{i + 1:02}.png"))
            s["gate"] = {"attempts": res.attempts, "passed": res.passed, "labels": [l.label for l in res.labels], "dropped": res.dropped}
            gated[i] = res
            s["gate_found"] = [{"label": l.label, "box": l.box, "score": float(l.score)} for l in res.labels]
            self.emit("visuals", "progress", f"Frame {i + 1}/{len(scenes)}" + (" · passed first try" if res.first_try else f" · {res.attempts} tries"),
                      scene=i, image=s["image"], progress=len(gated) / len(scenes))
        with ThreadPoolExecutor(max_workers=C.GATE_WORKERS) as ex:
            list(ex.map(do_scene, range(len(scenes))))
        vis = {"frames": len(scenes), "first_try": sum(1 for g in gated.values() if g.first_try),
               "regenerated": sum(g.attempts - 1 for g in gated.values()), "labels_dropped": sum(len(g.dropped) for g in gated.values()),
               "labels_kept": sum(len(g.labels) for g in gated.values())}
        vis["first_try_pass_rate"] = round(vis["first_try"] / max(1, len(scenes)), 2)
        vis["structure_pass_rate"] = round(vis["labels_kept"] / max(1, vis["labels_kept"] + vis["labels_dropped"]), 2)
        vis["provider_stats"] = {k: o.stats.public() for k, o in (("image", img_gen), ("segment", seg)) if hasattr(o, "stats")}
        vis["gate_seconds"] = round(time.time() - t_vis, 1)
        proof["visuals"] = vis
        (self.dir / "proof.json").write_text(json.dumps({"topic": self.topic, "proof": proof, "scenes": scenes}, indent=2))
        self.emit("visuals", "done", f"{len(scenes)} frames ready")
        self.emit("frame_qa", "done", f"{vis['labels_kept']} structures confirmed by {seg.name} · {vis['regenerated']} regenerated · {vis['labels_dropped']} labels dropped", visuals=vis)

        _save(locals())

    def step_labels(self):
        """Draw SAM-confirmed labels."""
        o, writer, critic, img_gen, seg, asr = self.opts, self.writer, self.critic, self.img_gen, self.seg, self.asr
        sc, ev, sources, used_queries, plan, script, scenes, gate, proof, review, gated = (getattr(self, k, None) for k in STATE_KEYS)
        _save = self._store
        # 6. LABEL — boxes come from the gate's confirmed detections (no second SAM pass)
        self.emit("segment", "running", "Drawing labels on confirmed structures…")
        for i, s in enumerate(scenes):
            src = self.dir / "frames" / f"{i + 1:02}.png"
            found = gated[i].labels if gated and i in gated else [SimpleNamespace(**d) for d in s.get("gate_found", [])]
            dst = self.dir / "labeled" / f"{i + 1:02}.png"
            L.draw_labels(str(src), str(dst), found) if found else shutil.copy(src, dst)
            s["labeled"], s["labels"] = self.url(dst), [{"label": f.label, "box": f.box, "score": round(f.score, 3)} for f in found]
            self.emit("segment", "progress", f"Frame {i + 1}: {', '.join(f.label for f in found) or 'no labels (none confirmed)'}",
                      scene=i, labeled=s["labeled"], progress=(i + 1) / len(scenes))
        self.emit("segment", "done", f"{sum(len(s['labels']) for s in scenes)} structures labeled")

        _save(locals())

    def step_render(self):
        """Voice, captions, render, package."""
        o, writer, critic, img_gen, seg, asr = self.opts, self.writer, self.critic, self.img_gen, self.seg, self.asr
        sc, ev, sources, used_queries, plan, script, scenes, gate, proof, review, gated = (getattr(self, k, None) for k in STATE_KEYS)
        _save = self._store
        # 7. VOICE
        lang = o.get("language", "en") or "en"
        if lang != "en" and not (proof or {}).get("translation"):
            raise RuntimeError(f"Refusing to voice a '{lang}' Short from an untranslated script")
        self.emit("voice", "running", f"Recording with {tts.engine_name(lang)}" + (f" · {tts.pcm_voice(o.get('voice', 'af_heart')) if lang == 'pcm' else o.get('voice', 'af_heart')}" if tts.voice_engine(lang) == "kokoro" else ""))
        if tts.voice_engine(lang) == "wazobia" and (lang in C.WAZOBIA_STRICT_LANGS or C.WAZOBIA_BACKEND == "modal"):
            from ..media import wazobia
            wazobia.check_lines([s["narration"] for s in scenes], lang)   # stops the run; never a fallback voice for yo/ha/ig
        speed = float(o.get("speed", 1.05))
        for attempt in range(2):
            t, wavs = 0.0, []
            for i, s in enumerate(scenes):
                w = self.dir / "audio" / f"{i + 1:02}.wav"
                s["audio_seconds"] = tts.synth(s["narration"], str(w), voice=o.get("voice", "af_heart"), speed=speed, lang=lang)
                s["start"] = t; t += s["audio_seconds"]; wavs.append(str(w))
                self.emit("voice", "progress", f"Scene {i + 1} · {s['audio_seconds']:.1f}s", progress=(i + 1) / len(scenes))
            # translated text runs longer/shorter than the English it was timed for: nudge the pace (max ±15%) to stay in the length rule
            fit = (t / (C.MAX_SECONDS - 1)) if t > C.MAX_SECONDS else (t / (C.MIN_SECONDS + 1)) if t < C.MIN_SECONDS else 1.0
            if lang == "en" or fit == 1.0 or attempt:
                break
            new = speed * min(1.15, max(0.87, fit))
            self.emit("voice", "retry", f"{t:.1f}s is outside {C.MIN_SECONDS:.0f}-{C.MAX_SECONDS:.0f}s; re-recording at {new / speed:.2f}x pace")
            speed = new
        proof.setdefault("length", {})["voice_speed"] = round(speed, 3)
        voice = self.dir / "voiceover.wav"
        R.concat_audio(wavs, str(voice))
        R.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(voice), "-b:a", "192k", str(self.dir / "voiceover.mp3")])
        self.emit("voice", "done", f"{t:.1f}s voiceover", audio=self.url(self.dir / "voiceover.mp3"))

        # 8. CAPTIONS + transcript verification
        full_text = " ".join(s["narration"] for s in scenes)
        words = cap.words_from_scenes(scenes)
        match = None
        if lang == "en":
            self.emit("captions", "running", f"Transcribing with {asr.name} to verify the read…")
            tr = asr.transcribe(str(voice), keywords=[x for s in scenes for x in s.get("structures", [])])
            if tr.words and len(tr.words) >= 0.9 * len(words):
                words = tr.words  # real word timestamps (whisper)
            match = difflib.SequenceMatcher(None, re.sub(r"\W+", " ", full_text.lower()).split(),
                                            re.sub(r"\W+", " ", tr.text.lower()).split()).ratio() if tr.text else None
        else:   # whisper can't transcribe Yoruba/Pidgin reliably: captions come from the known script + per-scene TTS timing
            self.emit("captions", "running", "Timing captions from the translated script and the voice timing…")
        cap.write_srt(words, str(self.dir / "captions.srt"))
        ass = self.dir / "work" / "captions.ass"
        ass.parent.mkdir(parents=True, exist_ok=True)
        cap.write_ass(words, str(ass), lang=lang)
        self.emit("captions", "done", f"{len(words)} words timed" + (f" · read accuracy {match:.0%}" if match is not None else ""),
                  transcript_match=match)

        # 9. RENDER
        self.emit("render", "running", "Animating shots, crossfades and captions…")
        clips, durs = [], [s["audio_seconds"] for s in scenes]
        use_labels = o.get("labels", True)
        for i, s in enumerate(scenes):
            src = self.dir / ("labeled" if use_labels and s["labels"] else "frames") / f"{i + 1:02}.png"
            big = R.cover(str(src), str(self.dir / "work" / f"big{i:02}.jpg"))
            clip = self.dir / "work" / f"clip{i:02}.mp4"
            R.scene_clip(big, durs[i] + R.XF, i, str(clip)); clips.append(str(clip))
            self.emit("render", "progress", f"Shot {i + 1}/{len(scenes)}", progress=(i + 1) / (len(scenes) + 1))
        music = None
        if o.get("music"):
            tracks = sorted(C.MUSIC_DIR.glob("*.mp3")) + sorted(C.MUSIC_DIR.glob("*.wav"))
            music = str(tracks[0]) if tracks else None
        video = self.dir / "video.mp4"
        R.final(clips, durs, str(voice), str(ass) if o.get("captions", True) else None, str(video), music=music)
        dur = R.probe_duration(str(video))

        # PACKAGE
        (self.dir / "script.txt").write_text(
            f"{plan.get('title', self.topic)}\n\n" + "\n\n".join(f"[{i + 1}] {s['narration']}" + (f"\n    (English: {s['narration_en']})" if lang != "en" and s.get("narration_en") else "")
                                                         for i, s in enumerate(scenes))
            + f"\n\nCaption: {script.get('caption', '')}\n{' '.join(script.get('hashtags', []))}\n")
        meta = {"topic": self.topic, "plan": plan, "scenes": scenes, "review": review, "caption": script.get("caption"),
                "hashtags": script.get("hashtags"), "duration": dur, "proof": proof, "sources": [x.public() for x in sources], "providers": {"writer": writer.name, "critic": critic.name,
                "image": img_gen.name, "segment": seg.name, "tts": tts.engine_name(lang), "asr": asr.name if lang == "en" else "script-timed captions"}}
        (self.dir / "plan.json").write_text(json.dumps(meta, indent=2))
        shutil.rmtree(self.dir / "work", ignore_errors=True)
        zpath = self.dir.with_suffix(".zip")
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
            for f in self.dir.rglob("*"):
                if f.is_file() and not f.name.endswith(".boxes.json"):
                    z.write(f, f.relative_to(self.dir.parent))
        proof.setdefault("length", {})["actual_seconds"] = round(dur, 1)
        (self.dir / "proof.json").write_text(json.dumps({"topic": self.topic, "proof": proof, "scenes": scenes}, indent=2))
        self.emit("render", "done", f"{dur:.1f}s · 1080×1920 · 30fps")
        final = dict(video=self.url(video), zip=f"/outputs/{zpath.name}",
                     srt=self.url(self.dir / "captions.srt"), script=self.url(self.dir / "script.txt"),
                     scenes=scenes, caption=script.get("caption"), hashtags=script.get("hashtags"), duration=dur,
                     title=plan.get("title", self.topic), proof=proof, topic=self.topic, language=lang, requested_language=lang)
        (self.dir / "share.json").write_text(json.dumps({"id": self.id, "created": time.time(), "status": "pending_review", **final}))   # feeds /s/<id> and the gallery
        self.final = final
        _save(locals())

    def _run(self):
        """Fixed pipeline (AGENT_MODE=fixed, and the fallback when the orchestrator fails)."""
        self.setup()
        o = self.opts
        self.emit("job", "start", self.topic, dir=self.rel, steps=[{"id": a, "title": b, "tool": c} for a, b, c in steps_for(o.get("language", "en"))],
                  providers=self.providers(), mode="fixed")
        self.step_scope()
        if self.status == "rejected":
            return
        self.step_evidence(); self.step_plan(); self.step_script(); self.step_claims()
        if o.get("stop_after") == "claims":
            self.emit("job", "done", "Sourced script verified (stopped before media)", proof=self.proof, scenes=self.scenes,
                      title=self.plan.get("title", self.topic), caption=self.script.get("caption"), hashtags=self.script.get("hashtags"))
            return
        self.step_translate()
        self.step_frames(); self.step_labels()
        if o.get("stop_after") == "frames":
            self.emit("job", "done", "Frames generated, SAM-gated and labeled (stopped before voice/render)", proof=self.proof, scenes=self.scenes,
                      title=self.plan.get("title", self.topic), dir=self.rel)
            return
        self.step_render()
        self.emit("job", "done", "Your Short is ready", id=self.id, **self.final)
