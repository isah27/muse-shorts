from pathlib import Path
from PIL import Image
from app import config as C
from app.agent.gate import ImageGate, check_image
from app.providers.base import Segment

class FakeGen:
    name = "fake"
    def __init__(self): self.prompts = []
    def generate(self, prompt, out_path, seed=0, aspect=""):
        self.prompts.append((seed, prompt))
        Image.new("RGB", (100, 200), (90, 120, 200)).save(out_path); return out_path

class ScriptedSeg:
    """seg.script[(phrase, call_index)] -> list of (box, score); anything else -> found nothing."""
    name = "fake-sam"
    def __init__(self, script): self.script, self.calls = script, {}
    def segment(self, path, phrase):
        k = self.calls[phrase] = self.calls.get(phrase, 0) + 1
        return [Segment(phrase, b, score=s) for b, s in self.script.get((phrase, k), self.script.get((phrase, "*"), []))]

BOX2 = (0, 130, 60, 190)
BOX = (20, 40, 80, 120)   # 60x80 of 100x200 = 24% of the frame
def run(tmp_path, seg, structs=("axon", "myelin sheath"), regen=2):
    ev = []
    gate = ImageGate(FakeGen(), seg, lambda step, status, msg="", **d: ev.append({"step": step, "status": status, "message": msg, **d}),
                     lambda p: "/x/" + p.name, max_regen=regen)
    res = gate.run_scene(0, list(structs), lambda missing, n: f"p{n} missing={missing}", tmp_path / "f.png", tmp_path / "att")
    return res, ev, gate

def test_passes_first_try_when_everything_found(tmp_path):
    seg = ScriptedSeg({("axon", "*"): [(BOX, .9)], ("myelin sheath", "*"): [(BOX2, .8)]})
    res, ev, gate = run(tmp_path, seg)
    assert res.passed and res.first_try and res.attempts == 1 and not res.dropped and len(res.labels) == 2
    assert not [e for e in ev if e["status"] == "retry"] and (tmp_path / "f.png").exists()

def test_missing_structure_triggers_regeneration_then_passes(tmp_path):
    seg = ScriptedSeg({("axon", "*"): [(BOX, .9)], ("myelin sheath", 2): [(BOX2, .7)]})   # missing on try 1, found on try 2
    res, ev, gate = run(tmp_path, seg)
    assert res.passed and res.attempts == 2 and not res.first_try and not res.dropped
    kinds = [e["kind"] for e in ev if e["status"] == "retry"]
    assert kinds == ["reject", "regenerate"]
    assert ev[0]["missing"] == ["myelin sheath"] and ev[0]["image"].endswith("01_try1.png")
    assert "myelin sheath" in gate.gen.prompts[1][1] and gate.gen.prompts[1][0] == 1   # new seed, missing part called out

def test_label_dropped_after_max_regenerations_but_frame_kept(tmp_path):
    seg = ScriptedSeg({("axon", "*"): [(BOX, .9)]})   # myelin sheath never found
    res, ev, gate = run(tmp_path, seg)
    assert not res.passed and res.attempts == 3 and res.dropped == ["myelin sheath"]
    assert [l.label for l in res.labels] == ["axon"]
    kinds = [e["kind"] for e in ev if e["status"] == "retry"]
    assert kinds.count("reject") == 3 and kinds.count("regenerate") == 2 and kinds[-1] == "drop_label"
    assert (tmp_path / "f.png").exists()

def test_low_score_and_bad_size_do_not_count(tmp_path):
    p = tmp_path / "i.png"; Image.new("RGB", (100, 200)).save(p)
    seg = ScriptedSeg({("a", "*"): [(BOX, .3)], ("b", "*"): [((0, 0, 100, 200), .95)], ("c", "*"): [((0, 0, 3, 3), .95)]})
    chk = check_image(seg, str(p), ["a", "b", "c"])
    assert chk.missing == ["a", "b", "c"] and "low confidence" in chk.detail["a"] and "too large" in chk.detail["b"] and "too small" in chk.detail["c"]

def test_two_similar_instances_are_ambiguous_but_a_clear_winner_is_fine(tmp_path):
    p = tmp_path / "i.png"; Image.new("RGB", (100, 200)).save(p)
    seg = ScriptedSeg({("x", "*"): [(BOX, .9), ((0, 130, 60, 190), .85)], ("y", "*"): [(BOX, .9), ((0, 130, 60, 190), .4)]})
    chk = check_image(seg, str(p), ["x", "y"])
    assert chk.ambiguous == ["x"] and "y" in chk.found and "y" not in chk.bad

def test_no_structures_means_nothing_to_gate(tmp_path):
    res, ev, _ = run(tmp_path, ScriptedSeg({}), structs=())
    assert res.passed and res.attempts == 1 and res.labels == []

def test_same_region_for_two_structures_fails_the_later_one(tmp_path):
    p = tmp_path / "i.png"; Image.new("RGB", (100, 200)).save(p)
    seg = ScriptedSeg({("brain", "*"): [(BOX, 1.0)], ("cerebellum", "*"): [(BOX, 1.0)]})
    chk = check_image(seg, str(p), ["brain", "cerebellum"])
    assert chk.ambiguous == ["cerebellum"] and "same region as brain" in chk.detail["cerebellum"]
    seg = ScriptedSeg({("brain", "*"): [(BOX, 1.0)], ("cerebellum", "*"): [((30, 60, 50, 90), 1.0)]})
    assert check_image(seg, str(p), ["brain", "cerebellum"]).passed   # a part inside the whole is fine

def test_equal_scores_from_meta_sam_label_the_largest_instance(tmp_path):
    p = tmp_path / "i.png"; Image.new("RGB", (100, 200)).save(p)
    seg = ScriptedSeg({("cell", "*"): [((0, 0, 30, 40), 1.0), (BOX, 1.0), ((0, 130, 60, 190), 1.0)]})
    chk = check_image(seg, str(p), ["cell"])
    assert chk.passed and chk.found["cell"].box == BOX
