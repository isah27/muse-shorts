"""Live checks against Baseten (Muse Spark Open) with real Wikipedia text. Run: RUN_LIVE=1 pytest -m live -s"""
import os, pytest
pytestmark = [pytest.mark.live, pytest.mark.skipif(not os.environ.get("RUN_LIVE") or not os.environ.get("BASETEN_API_KEY"), reason="live test")]

def _gate():
    from app.agent.claims import ClaimGate
    from app.agent.evidence import wikipedia, Source
    from app.providers.baseten import baseten_llm
    llm = baseten_llm()
    w = wikipedia("action potential", 1)[0]
    src = Source("W1", "wikipedia", w["title"], w["url"], w["text"])
    return ClaimGate, llm, src

def test_critic_catches_a_planted_false_number_and_fixes_it():
    ClaimGate, llm, src = _gate()
    from app.agent.claims import normalise_scenes
    events = []
    import re
    sentence = next(s for s in re.split(r"(?<=[.!?])\s+", src.text) if re.search(r"\d", s) and len(s) < 220)
    good = {"kind": "claim", "text": "An action potential occurs when the membrane potential of a specific cell rapidly rises and falls.", "source_id": "W1",
            "quote": "An action potential occurs when the membrane potential of a specific cell rapidly rises and falls"}
    bad = {"kind": "claim", "text": "Action potentials are a graded response that gets bigger when the stimulus is stronger.", "source_id": "W1", "quote": "graded response"}
    sc = normalise_scenes([{"lines": [good, bad]}])
    stats = ClaimGate(llm, llm, [src], lambda step, status, msg="", **d: events.append((status, d.get("kind"), msg)), max_rounds=2).run(sc)
    print("\n".join(map(str, events)))
    assert any(k == "reject" for _, k, _ in events), "critic should reject the planted false claim"
    final = " ".join(l["text"] for s in sc for l in s["lines"]).lower()
    assert "graded response that gets bigger" not in final
    assert stats["all_verified"]
