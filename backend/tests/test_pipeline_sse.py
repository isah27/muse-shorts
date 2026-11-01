import json, time
from fastapi.testclient import TestClient
from app.main import app

def stream(client, topic, **kw):
    jid = client.post("/api/jobs", json={"topic": topic, **kw}).json()["id"]
    evs = []
    with client.stream("GET", f"/api/jobs/{jid}/events") as r:
        for line in r.iter_lines():
            if line.startswith("data: ") and line != "data: {}":
                evs.append(json.loads(line[6:]))
    return evs

def test_sse_shows_claim_gate_retry_with_mock():
    evs = stream(TestClient(app), "How neurons fire", stop_after="claims")
    steps = [e["step"] for e in evs]
    assert steps[0] == "job" and steps.index("scope") < steps.index("evidence") < steps.index("script") < steps.index("claims")
    retries = [e for e in evs if e["step"] == "claims" and e["status"] == "retry"]
    assert any(e["kind"] == "reject" for e in retries) and any(e["kind"] == "rewrite" for e in retries)
    last = evs[-1]
    assert last["step"] == "job" and last["status"] == "done" and last["proof"]["rewritten"] >= 1 and last["proof"]["all_verified"]
    assert all(l["status"] in ("supported", "rewritten") for s in last["scenes"] for l in s["lines"])
    assert all(l["source_id"] for s in last["scenes"] for l in s["lines"] if l["kind"] == "claim")

def test_sse_rejects_medical_advice_before_any_model_or_evidence_work():
    evs = stream(TestClient(app), "What dose of ibuprofen should I take for a headache", stop_after="claims")
    steps = [(e["step"], e["status"]) for e in evs]
    assert ("scope", "rejected") in steps and steps[-1] == ("job", "rejected")
    assert not any(s == "evidence" for s, _ in steps)
    assert evs[-1]["category"] == "medical_advice" and evs[-1]["suggestion"]

def test_events_endpoint_ends_on_rejection():
    c = TestClient(app)
    evs = stream(c, "diagnose my headache", stop_after="claims")  # must terminate, not hang
    assert evs[-1]["status"] == "rejected"

def test_frames_stage_shows_sam_gate_retries_and_only_confirmed_labels():
    evs = stream(TestClient(app), "How neurons fire", stop_after="frames")
    qa = [e for e in evs if e["step"] == "frame_qa" and e["status"] == "retry"]
    assert any(e["kind"] == "reject" and e.get("missing") for e in qa) and any(e["kind"] == "regenerate" for e in qa)
    last = evs[-1]
    assert last["status"] == "done" and last["proof"]["visuals"]["regenerated"] >= 1
    for s in last["scenes"]:
        assert s["gate"]["passed"] or s["gate"]["dropped"]
        assert {l["label"] for l in s["labels"]}.isdisjoint(s["gate"]["dropped"])   # never label what SAM did not confirm


def test_share_endpoints_serve_a_finished_short_and_404_for_unknown():
    import json
    from app import config as C
    d = C.OUTPUT_DIR / "20260101-000000-demo"; d.mkdir(parents=True, exist_ok=True)
    (d / "share.json").write_text(json.dumps({"id": "abc123", "created": 1, "title": "Demo", "video": "/outputs/x/video.mp4", "duration": 50.0,
                                             "scenes": [{"image": "/outputs/x/frames/01.png"}], "proof": {"claims_final": 3, "all_verified": True}}))
    c = TestClient(app)
    assert c.get("/api/shorts/abc123").json()["title"] == "Demo"
    lst = c.get("/api/shorts").json()
    assert any(x["id"] == "abc123" and x["claims"] == 3 and x["poster"].endswith("01.png") for x in lst)
    assert c.get("/api/shorts/nope").status_code == 404
    assert c.post("/api/jobs", json={"topic": "How neurons fire", "language": "xx"}).status_code == 422
