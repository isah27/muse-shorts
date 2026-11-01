from app import config as C
from app.agent import length as L
from app.agent.pipeline import Job

def sc(words, n=1):
    return [{"narration": " ".join(["w"] * words), "lines": []} for _ in range(n)]

def test_estimate_matches_measured_kokoro_pacing():
    # measured: 93 words in 6 scenes rendered to 37.9 s
    assert abs(L.estimate_seconds(sc(15.5 and 15, 6)) - 37.9) < 4
    assert L.estimate_seconds(sc(20, 8)) > 45

def test_short_scripts_need_more_and_long_ones_do_not():
    assert L.seconds_short(sc(10, 6)) > 0
    assert L.seconds_short(sc(22, 8)) == 0
    assert L.words_for(10, 2) > 0

def test_hard_cap_cuts_scenes_before_the_closing_one():
    scenes = [{"narration": "w " * 40, "lines": [], "id": i} for i in range(12)]
    cut = L.trim_to_max(scenes)
    assert cut > 0 and L.estimate_seconds(scenes) <= C.MAX_SECONDS and scenes[-1]["id"] == 11

def test_defaults_encode_the_45_second_rule():
    assert C.MIN_SECONDS == 45 and C.IDEAL_MAX_SECONDS == 75

def test_pipeline_tops_up_a_short_script_with_new_sourced_lines_and_reports_length(tmp_path):
    ev = []
    Job("t", {"topic": "How neurons fire", "stop_after": "claims"}, ev.append).run()
    done = [e for e in ev if e["step"] == "job" and e["status"] == "done"][0]
    ln = done["proof"]["length"]
    assert ln["estimated_seconds"] >= 40 and ln["min_seconds"] == 45
    assert any(e.get("kind") == "length" for e in ev) or ln["estimated_seconds"] >= 48
    assert done["proof"]["all_verified"]
