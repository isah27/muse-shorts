"""Agents 102 upgrades in the orchestrator: allowlist, plan check, layered checks, strict domains, final check, trace."""
import json
from app.agent import verify as V
from app.agent import orchestrator as O
from app.agent.orchestrator import AgentJob
from test_orchestrator import FakeModel, T, FULL, run, fake_media


def tools_of(job, refused=None):
    return [t["tool"] for t in job.turns if refused is None or t["refused"] == refused]


def test_stage_allowlist_refuses_and_logs_blocked_event():
    job, evs = run([T("scope_check"), T("plan_scenes"), T("finish_short"), T("gather_evidence"), T("check_claims")] + FULL[3:]
                   + [T("render_video"), T("finish_short")])
    assert job.status == "done"
    assert tools_of(job, refused=True) == ["plan_scenes", "finish_short", "check_claims"]
    blocked = [e for e in evs if e["step"] == "agent" and e["status"] == "blocked"]
    assert [(e["tool"], e["stage"]) for e in blocked] == [("plan_scenes", "evidence"), ("finish_short", "evidence"), ("check_claims", "plan")]
    assert all("gather_evidence" in e["allowed"] and "finish_short" not in e["allowed"] for e in blocked[:2])
    # every result shown to the model carries the stage and the tools it may call
    last = json.loads(job.messages[-1]["content"])
    assert last["stage"] and last["allowed_tools"]
    first = json.loads(job.messages[1]["content"])
    assert first["allowed_tools"] == ["set_checklist", "scope_check"]


def test_allowlist_by_stage_and_language():
    job = AgentJob("al", {"topic": "How neurons fire"}, [].append, llm=FakeModel([]))
    job.setup()
    assert job.stage() == "scope" and job.allowed_tools() == ["set_checklist", "scope_check"]
    job.tool("scope_check", {}); assert job.stage() == "evidence"
    job.tool("gather_evidence", {}); assert job.stage() == "plan" and "write_script" not in job.allowed_tools()
    job.tool("plan_scenes", {}); job.tool("write_script", {}); assert job.stage() == "claims"
    job.tool("check_claims", {})
    assert job.stage() == "media" and "translate_script" not in job.allowed_tools() and "finish_short" not in job.allowed_tools()


def test_demo_trace_fail_feedback_retry_pass_and_write_script_waits_for_plan():
    job, evs = run([T("scope_check"), T("gather_evidence"), T("plan_scenes"), T("write_script"), T("plan_scenes"), T("write_script"),
                    T("check_claims"), T("write_script"), T("check_claims"), T("generate_frames"), T("check_labels"),
                    T("render_video"), T("finish_short")], demo_faults=True)
    assert job.status == "done"
    tr = job.check_trace
    assert [r["result"] for r in tr["plan_check"]] == ["fail", "pass"] and "S99" in tr["plan_check"][0]["feedback"][0]
    assert [r["result"] for r in tr["script_checks"]] == ["fail", "pass"] and tr["script_checks"][0]["feedback"][0].startswith("source:")
    assert "claim_judge" in tr and all(r["turn"] == tr["claim_judge"][-1]["turn"] for r in tr["claim_judge"])  # the judge never ran on the failing draft
    assert all(tr[k][-1]["result"] == "pass" for k in ("claim_judge", "labels", "render", "final_check"))
    # write_script was refused while the plan check was failing; the feedback reached the model
    assert job.turns[3]["tool"] == "write_script" and job.turns[3]["refused"]
    assert any("S99" in m["content"] for m in job.messages if m["role"] == "user")
    verify = [e for e in evs if e["step"] == "agent" and e["status"] == "verify"]
    assert [e["result"] for e in verify if e["check"] == "plan_check"] == ["fail", "pass"]
    assert job.proof["verification"] == tr


def test_strict_domain_needs_every_claim(monkeypatch):
    monkeypatch.setattr(O.V, "classify_domain", lambda topic, llm=None: V.policy_for("health") | {"layer": "rules", "reason": "test"})
    seen = {"n": 0}
    job = AgentJob("sd", {"topic": "How neurons fire"}, [].append,
                   llm=FakeModel(FULL[:6] + [T("generate_frames"), T("write_script"), T("check_claims"), T("generate_frames"),
                                 T("check_labels"), T("render_video"), T("finish_short")]))
    orig = job.step_claims
    def claims_with_one_cut():
        orig(); seen["n"] += 1
        if seen["n"] == 1:   # first judge pass: one unsupported line was cut -> 7/8 verified, not enough for health
            job.proof["corrections"].append({"action": "dropped", "before": "Neurons cure headaches."})
    job.step_claims = claims_with_one_cut
    job.step_render = lambda: fake_media(job)
    job.run()
    assert job.status == "done" and job.domain["strict"]
    cj = job.check_trace["claim_judge"]
    pol_fail = [r for r in cj if r["result"] == "fail" and "round" not in r]   # policy failures (not judge rounds)
    assert cj[-1]["result"] == "pass" and len(pol_fail) == 1
    assert job.turns[6]["tool"] == "generate_frames" and job.turns[6]["refused"]   # no frames for a failed policy
    assert "Neurons cure headaches." in pol_fail[0]["feedback"][1]
    assert job.proof["policy"]["ok"] and job.proof["policy"]["threshold"] == 1.0


def _to_render(job):
    job.setup()
    for t in ["scope_check", "gather_evidence", "plan_scenes", "write_script", "check_claims", "generate_frames", "check_labels"]:
        assert not job.tool(t, {}).get("error"), t
    job.step_render = lambda: fake_media(job)
    assert not job.tool("render_video", {}).get("error")


def test_final_check_passes_and_records_fingerprints():
    job = AgentJob("fc", {"topic": "How neurons fire"}, [].append, llm=FakeModel([])); _to_render(job)
    r = job.tool("finish_short", {"summary": "ok"})
    assert r["status"] == "done" and all(r["final_check"].values())
    fps = job.proof["fingerprints"]
    assert set(fps["media"]) == {"video.mp4", "voiceover.wav", "voiceover.mp3", "captions.srt"} and "labeled/01.png" in fps["frames"]


def test_final_check_refuses_swapped_frame_or_video():
    job = AgentJob("sw", {"topic": "How neurons fire"}, [].append, llm=FakeModel([])); _to_render(job)
    (job.dir / "labeled" / "02.png").write_bytes(b"not the approved frame")
    r = job.tool("finish_short", {})
    assert "Refused: final check failed" in r["error"] and "labeled/02.png" in r["error"]
    job2 = AgentJob("sv", {"topic": "How neurons fire"}, [].append, llm=FakeModel([])); _to_render(job2)
    (job2.dir / "video.mp4").write_bytes(b"other video")
    assert "video.mp4" in job2.tool("finish_short", {})["error"]
    assert {c["id"]: c["status"] for c in job2.checklist}["final"] == "open"


def test_final_check_duration_and_captions():
    job = AgentJob("du", {"topic": "How neurons fire"}, [].append, llm=FakeModel([])); _to_render(job)
    job.probe = lambda p: 30.0
    assert "duration" in job.tool("finish_short", {})["error"]
    job.probe = lambda p: 120.0
    assert "duration" in job.tool("finish_short", {})["error"]
    job2 = AgentJob("ca", {"topic": "How neurons fire"}, [].append, llm=FakeModel([])); _to_render(job2)
    (job2.dir / "captions.srt").write_text("1\n00:00:00,000 --> 00:00:52,000\nan unrelated caption track\n")
    err = job2.tool("finish_short", {})["error"]
    assert "captions" in err and "fingerprints" in err   # mismatch AND swapped after it passed


def test_render_check_rejects_captions_that_do_not_match_voice():
    job = AgentJob("rc", {"topic": "How neurons fire"}, [].append, llm=FakeModel([])); job.setup()
    for t in ["scope_check", "gather_evidence", "plan_scenes", "write_script", "check_claims", "generate_frames", "check_labels"]:
        job.tool(t, {})
    job.step_render = lambda: fake_media(job, captions="lorem ipsum dolor")
    r = job.tool("render_video", {})
    assert "Render check failed" in r["error"] and job.check_trace["render"][0]["result"] == "fail"
    assert not job.proof.get("fingerprints", {}).get("media")


def test_claim_judge_rejections_inside_gate_show_in_trace():
    """Real-run bug: the judge rejected 5 lines and rewrote them, but the trace showed only a first-try pass."""
    job = AgentJob("gr", {"topic": "How neurons fire"}, [].append, llm=FakeModel(FULL))
    orig = job.step_claims
    def judged():
        orig()
        job.proof["rounds"] = [{"round": 1, "checked": 20, "rejected": ["scene 1 unsupported: No infection needed."]},
                               {"round": 2, "checked": 1, "rejected": []}]
    job.step_claims = judged
    job.step_render = lambda: fake_media(job)
    job.run()
    tr = job.check_trace["claim_judge"]
    assert [r["result"] for r in tr] == ["fail", "pass"] and job.status == "done"
    assert "1/20 lines rejected" in tr[0]["feedback"][0] and "No infection needed." in tr[0]["feedback"][1]


def test_claim_gate_records_rejected_rounds(monkeypatch):
    from app.agent import claims as CL
    calls = {"n": 0}
    def check(self, line):
        calls["n"] += 1
        return {"verdict": "unsupported", "reason": "x"} if calls["n"] == 1 else {"verdict": "supported", "quote_verified": True}
    monkeypatch.setattr(CL.ClaimGate, "check_line", check)
    monkeypatch.setattr(CL.ClaimGate, "rewrite_line", lambda self, l, v: {"text": "Fixed line.", "source_id": "W1"})
    g = CL.ClaimGate(None, None, {}, lambda *a, **k: None, max_rounds=2)
    scenes = [{"lines": [{"kind": "claim", "text": "Bad line.", "source_id": "W1", "history": []}]}]
    monkeypatch.setattr(CL, "ensure_cta", lambda s: None); monkeypatch.setattr(CL, "dedupe", lambda s: 0)
    st = g.run(scenes)
    assert [len(r["rejected"]) for r in st["rounds"]] == [1, 0] and "Bad line." in st["rounds"][0]["rejected"][0]
