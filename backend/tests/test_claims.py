"""Claim gate logic, driven by a scripted fake critic so every branch is deterministic."""
from app.agent.claims import ClaimGate, normalise_scenes, quote_in_source, set_narration
from app.agent.evidence import Source

SRC = Source("W1", "wikipedia", "Neuron", "u", "Myelinated axons can conduct impulses at up to about one hundred and twenty metres per second. "
             "The human brain contains roughly eighty six billion neurons.")

class Critic:
    """check_claim: supported iff the line contains none of the poison words and (for the test of anti-fabrication) a quote exists."""
    def __init__(self, poison=("three hundred",), supporting_quote="up to about one hundred and twenty metres per second", always_bad=()):
        self.poison, self.sq, self.always_bad, self.calls = poison, supporting_quote, always_bad, []
    def complete_json_ex(self, system, user, schema=""):
        import json; d = json.loads(user)
        self.calls.append(system[:20])
        if "[task:check_framing]" in system:
            return {"verdict": "unsupported" if "million" in d["line"] else "supported", "reason": "fact in framing"}, "r"
        if "[task:check_claim]" in system:
            bad = any(p in d["line"] for p in self.poison + tuple(self.always_bad))
            return ({"verdict": "contradicted", "reason": "source says one hundred and twenty", "fix": "Up to one hundred and twenty metres per second."}
                    if bad else {"verdict": "supported", "supporting_quote": self.sq}), "thinking about the claim"
        if "[task:rewrite_claim]" in system:
            if any(p in d["line"] for p in self.always_bad):
                return {"drop": True}, ""
            return {"drop": False, "text": "Fast axons conduct at up to about one hundred and twenty metres per second.", "source_id": "W1",
                    "quote": "up to about one hundred and twenty metres per second"}, ""
        raise AssertionError(system[:40])
    complete_json = lambda self, *a: self.complete_json_ex(*a)[0]

def scenes(*lines):
    return normalise_scenes([{"lines": list(l), "visual_prompt": "v", "structures": ["axon"]} for l in lines])

def claim(text, quote="up to about one hundred and twenty metres per second", sid="W1"):
    return {"kind": "claim", "text": text, "source_id": sid, "quote": quote}

def run(sc, critic=None, rounds=2):
    ev = []
    critic = critic or Critic()
    g = ClaimGate(critic, critic, [SRC], lambda step, status, msg="", **d: ev.append((step, status, msg, d)), max_rounds=rounds, workers=2)
    return g.run(sc), ev

def test_all_supported_passes_first_try():
    sc = scenes([claim("Fast axons conduct at about one hundred and twenty metres per second.")], [{"kind": "framing", "text": "Follow for more."}])
    stats, ev = run(sc)
    assert stats["supported_first_try"] == 2 and stats["rewritten"] == 0 and stats["dropped"] == 0 and stats["all_verified"]
    assert not [e for e in ev if e[1] == "retry"]
    assert all(l["quote_verified"] for s in sc for l in s["lines"])

def test_unsupported_claim_is_rewritten_and_retry_is_streamed():
    sc = scenes([claim("Fast axons conduct at three hundred metres per second.")])
    stats, ev = run(sc)
    assert stats["rewritten"] == 1 and stats["dropped"] == 0 and stats["all_verified"]
    kinds = [e[3].get("kind") for e in ev if e[1] == "retry"]
    assert kinds == ["reject", "rewrite"]
    rej = [e for e in ev if e[3].get("kind") == "reject"][0]
    assert rej[3]["verdict"] == "contradicted" and "one hundred and twenty" in rej[3]["reason"] and rej[3]["reasoning"]
    assert "one hundred and twenty" in sc[0]["narration"] and "three hundred" not in sc[0]["narration"]
    assert sc[0]["lines"][0]["status"] == "rewritten"
    c = stats["corrections"][0]
    assert c["action"] == "rewritten" and "three hundred" in c["before"] and "one hundred and twenty" in c["after"]

def test_unfixable_claim_is_dropped_and_empty_scene_removed():
    sc = scenes([claim("Neurons feel love.")], [claim("Fast axons conduct at about one hundred and twenty metres per second.")])
    stats, ev = run(sc, Critic(poison=(), always_bad=("love",)))
    assert stats["dropped"] == 1 and len(sc) == 1 and stats["all_verified"]
    assert any(e[3].get("kind") == "drop" for e in ev)

def test_rewrite_that_still_fails_is_dropped_after_max_rounds():
    class Stubborn(Critic):
        def complete_json_ex(self, system, user, schema=""):
            if "[task:rewrite_claim]" in system:
                return {"drop": False, "text": "Still three hundred metres per second.", "source_id": "W1", "quote": "x" * 20}, ""
            return super().complete_json_ex(system, user, schema)
    sc = scenes([claim("a three hundred claim")], [claim("Fast axons conduct at about one hundred and twenty metres per second.")])
    stats, ev = run(sc, Stubborn(), rounds=2)
    assert stats["rewritten"] == 2 and stats["dropped"] == 1 and len(sc) == 1 and stats["all_verified"]
    assert sum(1 for e in ev if e[3].get("kind") == "reject") == 3   # initial + 2 re-checks, then dropped

def test_supported_without_verbatim_quote_is_not_trusted():
    # critic claims "supported" but its supporting quote is invented and the writer's quote is fake too
    sc = scenes([claim("Fast axons conduct at about one hundred and twenty metres per second.", quote="totally invented quote text")])
    stats, ev = run(sc, Critic(supporting_quote="also invented, not in the source"))
    assert stats["supported_first_try"] == 0 and stats["rewritten"] == 1   # forced through rewrite

def test_framing_line_with_fact_is_resourced_as_a_claim():
    sc = scenes([{"kind": "framing", "text": "Over a million people watched this."}], [claim("Fast axons conduct at about one hundred and twenty metres per second.")])
    stats, ev = run(sc)
    assert stats["rewritten"] == 1 and stats["dropped"] == 0 and stats["deduped"] == 1 and len(sc) == 1
    l = sc[0]["lines"][0]
    assert l["kind"] == "claim" and l["source_id"] == "W1" and l["status"] == "rewritten"

def test_framing_line_with_fact_is_dropped_when_no_source_supports_it():
    sc = scenes([{"kind": "framing", "text": "Over a million people watched this."}], [claim("Fast axons conduct at about one hundred and twenty metres per second.")])
    class C2(Critic):
        def complete_json_ex(self, system, user, schema=""):
            return ({"drop": True}, "") if "[task:rewrite_claim]" in system else super().complete_json_ex(system, user, schema)
    stats, ev = run(sc, C2())
    assert stats["dropped"] == 1 and len(sc) == 1

def test_cta_is_restored_if_dropped():
    sc = scenes([claim("Fast axons conduct at about one hundred and twenty metres per second.")])
    stats, ev = run(sc)
    assert sc[-1]["lines"][-1]["text"].startswith("Follow") and sc[-1]["narration"].endswith("body science.")

def test_unknown_source_id_fails():
    sc = scenes([claim("Fast axons conduct at about one hundred and twenty metres per second.", sid="Z9")])
    stats, ev = run(sc, rounds=1)
    assert stats["rewritten"] == 1 and sc[0]["lines"][0]["source_id"] == "W1"

def test_quote_in_source_is_punctuation_and_case_insensitive():
    assert quote_in_source("UP TO about one hundred and twenty metres per second!", SRC.text)
    assert not quote_in_source("about two hundred metres per second", SRC.text)
    assert not quote_in_source(None, SRC.text) and not quote_in_source("short", SRC.text)

def test_normalise_scenes_defaults():
    sc = normalise_scenes([{"lines": [{"text": "x fact", "source_id": "W1", "quote": "q"}, {"text": ""}, {"kind": "framing", "text": "Hi", "source_id": "W1"}]}, {"lines": []}])
    assert len(sc) == 1 and [l["kind"] for l in sc[0]["lines"]] == ["claim", "framing"] and sc[0]["lines"][1]["source_id"] is None
    set_narration(sc[0]); assert sc[0]["narration"] == "x fact. Hi."

def test_dedupe_removes_repeated_claims_but_keeps_distinct_ones():
    from app.agent.claims import dedupe
    sc = scenes([claim("Your cerebellum keeps behavior around a homeostatic baseline, automatically.")],
                [claim("It keeps behavior around a homeostatic baseline automatically.")],
                [claim("It fine tunes motor control and timing in humans.", quote="fine tunes motor control and timing")])
    assert dedupe(sc) == 1 and len(sc) == 2

def test_dedupe_drops_lines_resting_on_the_same_source_sentence():
    from app.agent.claims import dedupe
    q = "The action potential propagates without attenuation along the axon."
    sc = [{"lines": [{"kind": "claim", "text": "Signals travel the whole axon unchanged.", "quote": q},
                     {"kind": "claim", "text": "Spikes never fade out on the way.", "quote": q},
                     {"kind": "claim", "text": "Sodium rushes in first.", "quote": "Sodium ions rush in when channels open."}]}]
    assert dedupe(sc) == 1 and [l["text"] for l in sc[0]["lines"]] == ["Signals travel the whole axon unchanged.", "Sodium rushes in first."]
