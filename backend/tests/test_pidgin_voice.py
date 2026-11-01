"""Pidgin voice: lexicon substitution and Kokoro routing (Kokoro mocked)."""
import numpy as np
from app import config as C
from app.media import tts
from app.media.pidgin_lexicon import phonemize, LEXICON


def fake_g2p(chunk):
    return "<" + chunk.strip() + ">"


def test_lexicon_overrides_pidgin_words_only():
    ph = phonemize("Your vaccine don plant cells wey dey wait. Na di training.", fake_g2p)
    for w in ("don", "wey", "dey", "na", "di"):
        assert LEXICON[w] in ph
    assert "<Your vaccine>" in ph and "<plant cells>" in ph and "<wait.>" in ph
    assert "day" not in ph


def test_lexicon_is_word_bounded():
    ph = phonemize("Dena wants a donut and a deyo.", fake_g2p)   # no partial-word matches
    assert ph == "<Dena wants a donut and a deyo.>"


class FakeKokoro:
    class tokenizer:
        @staticmethod
        def phonemize(t, lang):
            return fake_g2p(t)

    def __init__(self):
        self.calls = []

    def create(self, text, voice, speed=1.0, lang="en-us", is_phonemes=False):
        self.calls.append(dict(text=text, voice=voice, is_phonemes=is_phonemes))
        return np.sin(np.linspace(0, 800, 24000)).astype("float32") * 0.3, 24000


def test_pidgin_routes_through_lexicon_and_pcm_voice(tmp_path, monkeypatch):
    fk = FakeKokoro()
    monkeypatch.setattr(tts, "_kokoro", fk)
    monkeypatch.setattr(C, "VOICE_ENGINE_PCM", "kokoro")
    monkeypatch.setattr(C, "PCM_LEXICON", True)
    monkeypatch.setattr(C, "PCM_VOICE", "am_fenrir")
    monkeypatch.setattr(C, "KOKORO_MODEL", tmp_path)          # .exists() -> True
    tts.synth("Una dey wait.", str(tmp_path / "a.wav"), lang="pcm")
    tts.synth("Una dey wait.", str(tmp_path / "b.wav"), voice="bf_emma", lang="pcm")   # explicit pick is kept
    tts.synth("They wait.", str(tmp_path / "c.wav"), lang="en")
    a, b, c = fk.calls
    assert a["is_phonemes"] and a["voice"] == "am_fenrir" and LEXICON["dey"] in a["text"]
    assert b["voice"] == "bf_emma"
    assert not c["is_phonemes"] and c["voice"] == "af_heart"
    assert "lexicon" in tts.engine_name("pcm")
