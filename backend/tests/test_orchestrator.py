"""Orchestrator loop driven by a scripted fake model (no API calls)."""
import json
import pytest
from app import config as C
from app.providers.openai_compat import Completion
from app.agent.orchestrator import AgentJob, make_job, TOOLS
from app.agent.pipeline import Job


class FakeModel:
    """Returns scripted tool choices; records what it was shown."""
    def __init__(self, script, where="content"):
        self.script, self.seen, self.where = list(script), [], where
    def chat_full(self, messages, **kw):
        self.seen.append(messages)
        step = self.script.pop(0) if self.script else {"tool": "finish_short", "args": {}, "reason": "done"}
        if isinstance(step, str):
            return Completion(step)
        body = json.dumps(step)
        return Completion("", body, usage={"prompt_tokens": 100, "completion_tokens": 10}) if self.where == "reasoning" else \
            Completion(body, usage={"prompt_tokens": 100, "completion_tokens": 10})


def T(tool, **args): return {"tool": tool, "args": args, "reason": f"next: {tool}"}
FULL = [T("scope_check"), T("set_checklist", items=[{"id": "hook", "text": "Opens with a hook"}]), T("gather_evidence"), T("plan_scenes"),
        T("write_script"), T("check_claims"), T("generate_frames"), T("check_labels")]


def fake_media(job, dur=52.0, captions=None):
    """Stand-in for step_render: writes video/voice/captions so the final check has real files to verify."""
    v = job.dir / "video.mp4"; v.write_bytes(b"0")
    (job.dir / "voiceover.wav").write_bytes(b"w"); (job.dir / "voiceover.mp3").write_bytes(b"m")
    text = captions if captions is not None else " ".join(s["narration"] for s in job.scenes)
    (job.dir / "captions.srt").write_text(f"1\n00:00:00,000 --> 00:00:{int(dur):02},000\n{text}\n")
    job.probe = lambda p: dur
    job.final = {"duration": dur, "proof": job.proof, "scenes": job.scenes, "video": job.url(v)}


def run(script, stop_media=True, **opts):
    evs = []
    job = AgentJob("t" + str(id(script))[-5:], {"topic": "How neurons fire", **opts}, evs.append, llm=FakeModel(script))
    if stop_media:   # skip voice/render in unit tests
        job.step_render = lambda: fake_media(job)
    job.run()
    return job, evs


def test_model_picks_tools_and_finishes():
    job, evs = run(FULL + [T("render_video"), T("finish_short", summary="ok")])
    assert job.status == "done"
    assert [t["tool"] for t in job.turns] == [s["tool"] for s in FULL] + ["render_video", "finish_short"]
    dec = [e for e in evs if e["step"] == "agent" and e["status"] == "decision"]
    assert len(dec) == 10 and all(e["reason"] and e["tool"] for e in dec)
    assert evs[-1]["step"] == "job" and evs[-1]["status"] == "done" and evs[-1]["agent"]["turns"] == 10
    assert any(c["id"] == "hook" for c in job.checklist)
    assert {c["id"]: c["status"] for c in job.checklist}["claims"] == "proven"


def test_tools_refuse_bad_calls_and_model_recovers():
    job, evs = run([T("render_video"), T("scope_check"), T("generate_frames"), T("finish_short"), T("gather_evidence"),
                    T("plan_scenes"), T("write_script"), T("render_video"), T("check_claims"), T("generate_frames"), T("check_labels"),
                    T("render_video"), T("finish_short")])
    refused = [t["tool"] for t in job.turns if t["refused"]]
    assert refused == ["render_video", "generate_frames", "finish_short", "render_video"]
    msgs = job.llm.seen[1]
    assert "Refused" in msgs[-1]["content"]    # the refusal went back to the model
    assert job.status == "done"


def test_unknown_tool_and_reasoning_content_answers():
    evs = []
    job = AgentJob("tr", {"topic": "How neurons fire"}, evs.append, llm=FakeModel([T("dance"), T("scope_check")], where="reasoning"))
    job.setup()
    d = job.decide(1)
    assert d["tool"] == "dance" and "Unknown tool" in job.tool("dance", {})["error"]


def test_retries_capped_then_escalate_then_fallback(monkeypatch):
    job, evs = run([T("render_video")] * 5)
    assert sum(1 for t in job.turns if t["by"] == "model") == 3      # capped at 3
    assert any(e["status"] == "escalate" for e in evs) and any(e["status"] == "fallback" for e in evs)
    assert job.status == "done" and any(t["by"] == "autopilot" for t in job.turns)


def test_garbage_model_falls_back_to_fixed_pipeline():
    job, evs = run(["not json at all"] * 6)
    assert any(e["status"] == "fallback" for e in evs) and job.status == "done"


def test_turn_limit():
    job, evs = run([T("scope_check")] * 10, max_turns=4)
    assert sum(1 for t in job.turns if t["by"] == "model") == 4
    assert any("turn limit" in f for f in job.flags) and job.status == "done"   # autopilot finished it


def test_state_persisted_and_resume_reuses_it():
    job, _ = run(FULL[:6] + ["bad"] * 3 + [T("finish_short")] * 0, stop_media=True)
    st = json.loads((job.dir / "state.json").read_text())
    assert st["evidence"] and st["scenes"] and st["proof"]["all_verified"] and st["turns"] and st["checklist"]
    evs = []
    r = AgentJob("res", {"topic": "How neurons fire", "resume": job.rel}, evs.append, llm=FakeModel([T("generate_frames")]))
    assert r.dir == job.dir and r._claims_ok() and len(r.turns) == len(st["turns"])


def test_language_remake_reuses_verified_facts():
    job, _ = run(FULL + [T("render_video"), T("finish_short")])
    # the model tries to render first and is refused (still English), then translates
    fake = FakeModel([T("scope_check"), T("render_video"), T("translate_script"), T("render_video"), T("finish_short")])
    evs = []
    r = AgentJob("yo", {"topic": "How neurons fire", "language": "yo", "remake_from": job.rel}, evs.append, llm=fake)
    # verified facts AND the SAM-gated frames are reused (copied into the new run); nothing is redrawn
    assert r.dir != job.dir and r._claims_ok() and all(s.get("image") and s.get("labeled") for s in r.scenes)
    assert all((r.dir / "labeled" / f"{i + 1:02}.png").exists() for i in range(len(r.scenes)))
    r.step_render = lambda: fake_media(r, 50.0)
    r.run()
    tools = [t["tool"] for t in r.turns]
    assert r.status == "done" and not {"gather_evidence", "generate_frames", "check_claims"} & set(tools)
    assert [t["tool"] for t in r.turns if t["refused"]] == ["render_video"]
    tr = r.proof["translation"]
    assert tr["language"] == "yo" and tr["flagged"] == [] and tr["verified_same"] == tr["lines"]
    for s in r.scenes:
        assert s["narration"].startswith("[yo]") and s["narration_en"]
        for l in s["lines"]:   # each translated line keeps its claim's source id and English quote
            assert l["text"].startswith("[yo]") and l["text_en"] and l["tr"]["back"] == l["text_en"]
            if l["kind"] == "claim":
                assert l["source_id"] and l["quote"]
    assert {c["id"]: c["status"] for c in r.checklist}["translation"] == "proven"
    # a Pidgin remake of the Yoruba remake starts again from the verified English, not from Yoruba
    p = AgentJob("pcm", {"topic": "How neurons fire", "language": "pcm", "remake_from": r.rel}, [].append,
                 llm=FakeModel([T("translate_script"), T("render_video"), T("finish_short")]))
    assert not p.proof.get("translation") and not any(s["narration"].startswith("[yo]") for s in p.scenes)
    p.step_render = lambda: fake_media(p, 50.0)
    p.run()
    assert p.status == "done" and all(s["narration"].startswith("[pcm]") for s in p.scenes)


def test_fresh_yoruba_run_and_english_refuses_translate():
    job, _ = run(FULL + [T("translate_script"), T("render_video"), T("finish_short")], language="yo")
    assert job.status == "done" and job.proof["translation"]["language"] == "yo"
    job, _ = run(FULL + [T("translate_script"), T("render_video"), T("finish_short")])
    assert job.turns[len(FULL)]["refused"] and job.status == "done"


def test_autopilot_translates_for_pidgin():
    job, _ = run(["not json"] * 5, language="pcm")
    assert job.status == "done" and job.proof["translation"]["language"] == "pcm"
    assert "translate_script" in [t["tool"] for t in job.turns]


def test_out_of_scope_topic_ends_run():
    evs = []
    job = AgentJob("oos", {"topic": "What dose of ibuprofen should I take"}, evs.append, llm=FakeModel([T("scope_check")]))
    job.run()
    assert job.status == "rejected" and ("job", "rejected") in [(e["step"], e["status"]) for e in evs] and len(job.turns) == 1


def test_mode_switch(monkeypatch):
    assert isinstance(make_job("a", {"topic": "x y z"}, print), AgentJob)
    assert type(make_job("b", {"topic": "x y z", "mode": "fixed"}, print)) is Job
    monkeypatch.setattr(C, "AGENT_MODE", "fixed")
    assert type(make_job("c", {"topic": "x y z"}, print)) is Job
    assert "finish_short" in TOOLS and len(TOOLS) == 11
