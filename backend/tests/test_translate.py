"""Translation gate + MMS voice + script-timed captions, all with mocked model and TTS."""
import json, re
import numpy as np
from app import config as C
import soundfile as sf
from app.agent.translate import translate_scenes
from app.media import tts, captions as cap


def scenes():
    return [{"lines": [{"kind": "claim", "text": "Memory cells last for decades.", "source_id": "W1", "quote": "Memory cells last up to several decades."},
                       {"kind": "framing", "text": "Here's how."}], "narration": "Memory cells last for decades. Here's how."},
            {"lines": [{"kind": "claim", "text": "Antibodies bind one antigen.", "source_id": "P1", "quote": "Each antibody binds a specific antigen."}],
             "narration": "Antibodies bind one antigen."}]


class Fake:
    """Translator that gets line 1.1 wrong (drops 'decades') until it is told the problem; `stubborn` never fixes it."""
    def __init__(self, stubborn=False):
        self.calls, self.stubborn = [], stubborn
    def complete_json_ex(self, system, user, schema=""):
        task = re.search(r"\[task:(\w+)\]", system).group(1); d = json.loads(user); self.calls.append(task)
        if task == "translate":
            out = []
            for x in d["lines"]:
                t = "Àwọn sẹ́ẹ̀lì ìrántí " + x["text"]
                if x["id"] == "1.1" and (self.stubborn or "problem" not in x):
                    t = t.replace(" for decades", "")
                out.append({"id": x["id"], "text": t})
            return {"lines": out}, ""
        if task == "back_translate":
            return {"lines": [{"id": x["id"], "text": x["text"].replace("Àwọn sẹ́ẹ̀lì ìrántí ", "")} for x in d["lines"]]}, ""
        if task == "check_meaning":
            return {"lines": [{"id": x["id"], "verdict": "same" if x["original"] == x["back_translation"] else "changed",
                               "reason": "drops 'for decades'"} for x in d["lines"]]}, ""


def test_back_translation_rewrites_then_passes():
    sc, evs, f = scenes(), [], Fake()
    r = translate_scenes(sc, "yo", f, f, lambda *a, **k: evs.append((a, k)))
    assert r["flagged"] == [] and r["rewritten"] == 1 and r["verified_same"] == 3
    l = sc[0]["lines"][0]
    assert l["tr"]["rounds"] == 1 and len(l["tr"]["history"]) == 2 and l["source_id"] == "W1" and l["text_en"] == "Memory cells last for decades."
    assert "ẹ́" in sc[0]["narration"] and sc[0]["narration_en"].startswith("Memory")   # tone marks preserved (NFC)
    kinds = [k.get("kind") for a, k in evs if a[1] == "retry"]
    assert kinds == ["reject", "rewrite"]


def test_back_translation_flags_after_two_rounds():
    sc, f = scenes(), Fake(stubborn=True)
    r = translate_scenes(sc, "pcm", f, f, lambda *a, **k: None)
    assert r["flagged"] == ["1.1"] and sc[0]["lines"][0]["tr"]["flagged"] and len(sc[0]["lines"][0]["tr"]["history"]) == 3
    assert f.calls.count("translate") == 3   # first pass + 2 re-translations


def test_mms_voice_is_normalised_and_dispatched(monkeypatch, tmp_path):
    from app.media import mms
    seen = {}
    def fake(text, lang, speaking_rate=1.0, seed=0):
        seen.update(text=text, lang=lang, rate=speaking_rate)
        return (0.02 * np.sin(np.linspace(0, 2000, 32000))).astype("float32"), 16000
    monkeypatch.setattr(mms, "synth", fake)
    monkeypatch.setattr(C, "VOICE_ENGINE_YO", "mms")   # default is now wazobia; MMS stays available via VOICE_ENGINE_YO=mms
    out = tmp_path / "a.wav"
    d = tts.synth("Ẹ káàbọ̀.", str(out), lang="yo")
    x, sr = sf.read(out)
    assert seen["lang"] == "yo" and sr == 24000 and abs(d - 2.3) < 0.05
    import pyloudnorm as pyln
    assert abs(pyln.Meter(sr).integrated_loudness(x[int(0.05 * sr):int(2.05 * sr)]) - (-16)) < 1.5
    assert tts.engine_name("yo").startswith("Meta MMS") and tts.engine_name("en") != tts.engine_name("yo")


def test_captions_from_known_script_keep_tone_marks(tmp_path):
    sc = [{"narration": "Àwọn sẹ́ẹ̀lì ìrántí wà.", "start": 0.0, "audio_seconds": 2.0}, {"narration": "Ó dára.", "start": 2.0, "audio_seconds": 1.5}]
    w = cap.words_from_scenes(sc)
    assert [x["word"] for x in w] == "Àwọn sẹ́ẹ̀lì ìrántí wà. Ó dára.".split() and w[3]["end"] <= 2.0 and w[4]["start"] >= 2.0
    cap.write_ass(w, str(tmp_path / "c.ass"))
    assert "SẸ́Ẹ̀LÌ" in (tmp_path / "c.ass").read_text()
