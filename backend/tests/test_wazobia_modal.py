import io, json
import numpy as np, pytest, soundfile as sf
from app import config as C
from app.media import wazobia


def _wav(sec=0.5, sr=24000):
    b = io.BytesIO(); sf.write(b, np.zeros(int(sec * sr), dtype="float32") + 0.01, sr, format="WAV"); return b.getvalue()


@pytest.fixture
def modal_env(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "WAZOBIA_AUDIO_DIR", tmp_path)
    monkeypatch.setattr(C, "WAZOBIA_BACKEND", "modal")
    wazobia.reset(); yield tmp_path; wazobia.reset()


def test_modal_renders_missing_then_lookup_hits(modal_env, monkeypatch):
    calls = []
    def fake(lines):
        calls.append(lines)
        return {"sr": 24000, "gpu": "T4", "lines": [{"index": l["index"], "wav": _wav(), "seconds": .5, "gpu_s": 1} for l in lines]}
    monkeypatch.setattr(wazobia, "_modal_render", fake)
    wazobia.check_lines(["Ẹ kú àárọ̀.", "Ẹ kú àárọ̀.", "Ọ dị mma."], "yo")
    assert len(calls) == 1 and len(calls[0]) == 2
    assert wazobia.lookup("Ọ dị mma.", "yo") is not None
    m = json.loads(next(modal_env.rglob("manifest.json")).read_text())
    assert m["backend"] == "modal" and len(m["lines"]) == 2
    wazobia.check_lines(["Ọ dị mma."], "yo"); assert len(calls) == 1   # cached, no second call


def test_modal_failure_stops_run(modal_env, monkeypatch):
    def boom(lines): raise RuntimeError("no GPU")
    monkeypatch.setattr(wazobia, "_modal_render", boom)
    with pytest.raises(wazobia.MissingLineError) as e:
        wazobia.check_lines(["Abeg."], "pcm")
    assert isinstance(e.value, wazobia.ModalRenderError) and "no GPU" in str(e.value)


def test_prerendered_backend_never_calls_modal(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "WAZOBIA_AUDIO_DIR", tmp_path); monkeypatch.setattr(C, "WAZOBIA_BACKEND", "prerendered")
    monkeypatch.setattr(wazobia, "_modal_render", lambda l: pytest.fail("called"))
    wazobia.reset()
    with pytest.raises(wazobia.MissingLineError):
        wazobia.check_lines(["Missing."], "ha")
