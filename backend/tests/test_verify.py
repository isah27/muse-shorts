"""Deterministic verification layer (app/agent/verify.py), no model calls."""
from pathlib import Path
from app import config as C
from app.agent import verify as V
from app.agent.evidence import Source


def src(i, text): return Source(id=i, kind="mock", title=f"t{i}", url="", text=text)


SRCS = [src("S1", "Neurons fire an action potential when sodium channels open in the axon membrane."),
        src("S2", "Myelin insulates the axon so the signal jumps between nodes of Ranvier.")]


class LLM:
    def __init__(self, dom=None, boom=False): self.dom, self.boom, self.calls = dom, boom, 0
    def complete_json(self, system, user, schema=""):
        self.calls += 1
        assert "[task:domain]" in system
        if self.boom: raise RuntimeError("down")
        return {"domain": self.dom, "reason": "model"}


def test_domain_keywords_first_then_model_then_default(monkeypatch):
    m = LLM("legal")
    d = V.classify_domain("How vaccines train the immune system", m)
    assert d["domain"] == "health" and d["strict"] and d["threshold"] == 1.0 and d["layer"] == "rules" and m.calls == 0
    assert V.classify_domain("Why inflation erodes savings")["domain"] == "finance"
    d = V.classify_domain("How the cochlea hears pitch", LLM("general"))
    assert d["domain"] == "general" and not d["strict"] and d["threshold"] == C.LENIENT_CLAIM_THRESHOLD and d["layer"] == "llm"
    assert V.classify_domain("How the cochlea hears pitch", LLM(boom=True))["layer"] == "default"
    monkeypatch.setattr(C, "STRICT_DOMAINS", "legal")      # configurable: health no longer strict
    assert not V.classify_domain("How vaccines work")["strict"]


def test_plan_check():
    ok = {"claims": [{"point": "sodium channels open in the axon membrane", "source_id": "S1"},
                     {"point": "myelin insulates the axon", "source_id": "S2"}]}
    assert V.plan_check(ok, SRCS) == {"ok": True, "checked": 2, "failures": []}
    r = V.plan_check({"claims": [{"point": "myelin insulates the axon", "source_id": "S9"},
                                 {"point": "dopamine controls reward prediction errors", "source_id": "S1"}]}, SRCS)
    assert not r["ok"] and "unknown source 'S9'" in r["failures"][0] and "not found in S1" in r["failures"][1]
    assert not V.plan_check({"beats": []}, SRCS)["ok"]


def _scene(lines): return {"lines": lines, "narration": " ".join(l["text"] for l in lines)}
def _claim(sid="S1", quote="q", n=12): return {"kind": "claim", "text": " ".join(["word"] * n), "source_id": sid, "quote": quote}


def test_script_checks_layered():
    good = [_scene([_claim(n=30)]) for _ in range(5)]
    assert V.script_checks(good, SRCS)["ok"]
    r = V.script_checks([_scene([_claim(sid="S7")]), _scene([_claim(quote="")]), _scene([{"kind": "x", "text": ""}])], SRCS)
    assert not r["ok"] and any(f.startswith("source:") and "S7" in f for f in r["failures"]) \
        and any("no supporting quote" in f for f in r["failures"]) and any(f.startswith("schema:") for f in r["failures"])
    r = V.script_checks([_scene([_claim(n=2)]) for _ in range(3)], SRCS)
    assert not r["ok"] and r["failures"][0].startswith("length:")


def test_claim_policy_strict_vs_lenient():
    drop = lambda n: [{"action": "dropped", "before": f"bad {i}"} for i in range(n)]
    p = {"claims_final": 9, "all_verified": True, "corrections": drop(1)}
    assert V.claim_policy(p, V.policy_for("general"))["ok"]                 # 90% with the bad line cut
    s = V.claim_policy(p, V.policy_for("health"))
    assert not s["ok"] and s["cut"] == ["bad 0"] and s["strict"]
    assert not V.claim_policy({"claims_final": 8, "all_verified": True, "corrections": drop(2)}, V.policy_for("general"))["ok"]
    assert V.claim_policy({"claims_final": 5, "all_verified": True, "corrections": []}, V.policy_for("finance"))["ok"]
    assert not V.claim_policy({"claims_final": 0, "all_verified": True, "corrections": []}, V.policy_for("general"))["ok"]


def test_fingerprints_detect_swap(tmp_path: Path):
    (tmp_path / "a.png").write_bytes(b"one"); (tmp_path / "b.mp4").write_bytes(b"two")
    fp = V.fingerprint(tmp_path, ["a.png", "b.mp4", "missing.wav"])
    assert set(fp) == {"a.png", "b.mp4"} and len(fp["a.png"]) == 64 and V.changed(tmp_path, fp) == []
    (tmp_path / "b.mp4").write_bytes(b"swapped")
    (tmp_path / "a.png").unlink()
    assert sorted(V.changed(tmp_path, fp)) == ["a.png", "b.mp4"]


def test_captions_match_voice(tmp_path: Path):
    srt = tmp_path / "c.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:02,500\nNeurons fire fast.\n\n2\n00:00:02,500 --> 00:00:50,200\nMyelin helps.\n")
    assert V.captions_match(srt, "Neurons fire fast. Myelin helps!", 50.0)["ok"]
    assert not V.captions_match(srt, "Something else entirely is said here", 50.0)["ok"]
    assert not V.captions_match(srt, "Neurons fire fast. Myelin helps.", 58.0)["ok"]      # captions end 8 s before the voice
    assert not V.captions_match(tmp_path / "none.srt", "x", 1)["ok"]
