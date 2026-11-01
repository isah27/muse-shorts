"""Human sign-off: new Shorts are pending_review; publish (gallery/share page) and export are blocked until approved."""
import json
from fastapi.testclient import TestClient
from app import config as C
from app.main import app
from app.agent import verify as V


def make(name, sid, status="pending_review", proof=None):
    d = C.OUTPUT_DIR / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "video.mp4").write_bytes(b"verified video")
    (C.OUTPUT_DIR / f"{name}.zip").write_bytes(b"PK")
    proof = proof if proof is not None else {"claims_final": 3, "all_verified": True, "final_check": {"ok": True},
                                             "fingerprints": {"media": V.fingerprint(d, ["video.mp4"])}}
    body = {"id": sid, "created": 1, "title": "T", "video": f"/outputs/{name}/video.mp4", "zip": f"/outputs/{name}.zip",
            "scenes": [{}], "proof": proof}
    if status:
        body["status"] = status
    (d / "share.json").write_text(json.dumps(body))
    return d


def test_pending_short_is_hidden_and_export_blocked_until_approved():
    make("rv1", "rv1id"); c = TestClient(app)
    assert all(x["id"] != "rv1id" for x in c.get("/api/shorts").json())
    assert any(x["id"] == "rv1id" and x["status"] == "pending_review" for x in c.get("/api/shorts?all=1").json())
    assert c.get("/api/shorts/rv1id").status_code == 403
    assert c.get("/api/shorts/rv1id?preview=1").json()["status"] == "pending_review"
    assert c.get("/api/shorts/rv1id/export").status_code == 403
    assert c.get("/outputs/rv1.zip").status_code == 403
    r = c.post("/api/shorts/rv1id/review", json={"decision": "approve", "note": "checked"})
    assert r.status_code == 200 and r.json()["status"] == "approved"
    assert c.get("/api/shorts/rv1id").status_code == 200
    assert any(x["id"] == "rv1id" for x in c.get("/api/shorts").json())
    assert c.get("/api/shorts/rv1id/export").status_code == 200 and c.get("/outputs/rv1.zip").status_code == 200


def test_reject_and_bad_decision():
    make("rv2", "rv2id"); c = TestClient(app)
    assert c.post("/api/shorts/rv2id/review", json={"decision": "maybe"}).status_code == 422
    assert c.post("/api/shorts/rv2id/review", json={"decision": "reject", "note": "label wrong"}).json()["status"] == "rejected"
    assert c.get("/api/shorts/rv2id/export").status_code == 403 and c.get("/api/shorts/rv2id").status_code == 403
    assert c.post("/api/shorts/none/review", json={"decision": "approve"}).status_code == 404


def test_approve_refuses_swapped_video_or_failed_final_check():
    d = make("rv3", "rv3id"); c = TestClient(app)
    (d / "video.mp4").write_bytes(b"swapped after verification")
    r = c.post("/api/shorts/rv3id/review", json={"decision": "approve"})
    assert r.status_code == 409 and "video.mp4" in r.json()["detail"]
    make("rv4", "rv4id", proof={"final_check": {"ok": False}})
    assert c.post("/api/shorts/rv4id/review", json={"decision": "approve"}).status_code == 409


def test_legacy_short_without_status_counts_as_approved():
    make("rv5", "rv5id", status=None); c = TestClient(app)
    assert c.get("/api/shorts/rv5id").status_code == 200 and c.get("/api/shorts/rv5id/export").status_code == 200


def test_pipeline_marks_new_shorts_pending_review():
    import inspect
    from app.agent import pipeline
    assert '"status": "pending_review"' in inspect.getsource(pipeline.Job.step_render)
