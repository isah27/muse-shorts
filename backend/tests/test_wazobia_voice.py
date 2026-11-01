"""PCM_ENGINE=wazobia: pre-rendered WazobiaVoice wavs matched by text hash, Kokoro fallback, real durations."""
import json
import numpy as np
import soundfile as sf
from app import config as C
from app.media import tts, wazobia


def _setup(tmp_path, monkeypatch, texts, sr=24000, secs=2.0):
    d = tmp_path / "wz"; d.mkdir()
    rows = []
    for i, t in enumerate(texts):
        f = f"{i:02}.wav"
        sf.write(str(d / f), (0.1 * np.sin(np.linspace(0, 800, int(sr * secs)))).astype("float32"), sr)
        rows.append({"index": i, "hash": wazobia.text_hash(t), "text": t, "file": f})
    (d / "manifest.json").write_text(json.dumps({"lines": rows}))
    monkeypatch.setattr(C, "PCM_ENGINE", "wazobia")
    monkeypatch.setattr(C, "WAZOBIA_AUDIO_DIR", tmp_path)
    wazobia.reset()
    calls = []
    monkeypatch.setattr(tts, "_kokoro_samples", lambda text, v, s, lang="en": (calls.append(text) or (np.full(24000, 0.05, "float32"), 24000)))
    return calls


def test_hash_is_whitespace_insensitive():
    assert wazobia.text_hash(" Na  di\ttraining. ") == wazobia.text_hash("Na di training.")
    assert wazobia.text_hash("Na di training.") != wazobia.text_hash("Na di training!")


def test_engine_routing(monkeypatch):
    monkeypatch.setattr(C, "PCM_ENGINE", "wazobia")
    assert tts.voice_engine("pcm") == "wazobia" and tts.voice_engine("en") == "kokoro"
    assert "WazobiaVoice" in tts.engine_name("pcm")


def test_uses_prerendered_wav_with_real_duration(tmp_path, monkeypatch):
    calls = _setup(tmp_path, monkeypatch, ["Vaccines dey work."], sr=22050, secs=3.0)
    out = tmp_path / "a.wav"
    d = tts.synth("Vaccines  dey work.", str(out), lang="pcm", pad=0.25)
    a, sr = sf.read(str(out))
    assert calls == [] and sr == tts.SR
    assert abs(d - len(a) / sr) < 1e-6 and abs(d - (3.0 + 0.05 + 0.25)) < 0.01


def test_missing_line_falls_back_to_kokoro(tmp_path, monkeypatch):
    calls = _setup(tmp_path, monkeypatch, ["Line one."])
    d = tts.synth("A line wey no dey manifest.", str(tmp_path / "b.wav"), lang="pcm", pad=0.25)
    assert calls == ["A line wey no dey manifest."] and wazobia.MISSES == calls
    assert abs(d - 1.3) < 0.01


def test_export_script_embeds_lines(tmp_path):
    import importlib.util, pathlib
    root = pathlib.Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("exp", root / "scripts/export_pcm_lines.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    lines = [{"index": 0, "hash": wazobia.text_hash("Na so."), "text": "Na so."}]
    (tmp_path / "notebook_lines_template.py").write_text("import json\nLINES_JSON = None  # filled by scripts/export_pcm_lines.py\nLINES = json.loads(LINES_JSON)\n")
    m.build_notebook(lines, tmp_path / "notebook_lines_template.py", tmp_path, "run")
    ns = {}; exec((tmp_path / "notebook_lines.py").read_text(), ns)
    assert ns["LINES"] == lines and (tmp_path / "c_lines.html").read_text().startswith("<textarea")


def test_lookup_is_language_keyed(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, ["Owó."])
    m = tmp_path / "wz" / "manifest.json"; d = json.loads(m.read_text())
    d["samples"] = [{"lang": "yo", "hash": wazobia.text_hash("Owó."), "text": "Owó.", "file": "00.wav"}]
    d["lines"][0]["lang"] = "pcm"; m.write_text(json.dumps(d)); wazobia.reset()
    assert wazobia.lookup("Owó.", "yo") is not None and wazobia.lookup("Owó.", "pcm") is not None
    assert wazobia.lookup("Owó.", "ha") is None
