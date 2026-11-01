"""Yoruba (switched to WazobiaVoice ngozi), Hausa and Igbo: routing, hard stop on a missing line, API, translation, captions, export."""
import json, sys
from pathlib import Path
import numpy as np
import pytest
import soundfile as sf
from app import config as C
from app.agent import translate as T, prompts as P
from app.media import tts, wazobia, captions as cap

ROOT = Path(__file__).resolve().parents[2]


def _wz(tmp_path, monkeypatch, rows):
    d = tmp_path / "wz"; d.mkdir()
    out = []
    for i, (lang, text) in enumerate(rows):
        f = f"{i:02}.wav"
        sf.write(str(d / f), (0.1 * np.sin(np.linspace(0, 800, 48000))).astype("float32"), 24000)
        out.append({"index": i, "lang": lang, "hash": wazobia.text_hash(text), "text": text, "file": f})
    (d / "manifest.json").write_text(json.dumps({"lines": out}, ensure_ascii=False))
    monkeypatch.setattr(C, "WAZOBIA_AUDIO_DIR", tmp_path)
    wazobia.reset()
    kokoro = []
    monkeypatch.setattr(tts, "_kokoro_samples", lambda *a, **k: (kokoro.append(a[0]) or (np.zeros(2400, "float32"), 24000)))
    return kokoro


def test_defaults_route_yo_ha_ig_to_wazobia():
    assert C.VOICE_ENGINE_YO == C.VOICE_ENGINE_HA == C.VOICE_ENGINE_IG == "wazobia"
    for lang in ("yo", "ha", "ig"):
        assert tts.voice_engine(lang) == "wazobia"
        assert "ngozi" in tts.engine_name(lang) and "stops the run" in tts.engine_name(lang)
    assert tts.voice_engine("en") == "kokoro"


def test_yo_can_still_use_mms_but_ha_ig_never_kokoro(monkeypatch):
    monkeypatch.setattr(C, "VOICE_ENGINE_YO", "mms")
    assert tts.voice_engine("yo") == "mms"
    monkeypatch.setattr(C, "VOICE_ENGINE_HA", "kokoro")
    with pytest.raises(ValueError):
        tts.voice_engine("ha")


@pytest.mark.parametrize("lang,text", [("yo", "Àjẹsára ń kọ́ ara."), ("ha", "Ƙwayoyin cuta suna ɗaukar ɓangare."), ("ig", "Ọrịa na-emetụta ụmụ mmadụ.")])
def test_hit_uses_prerendered_wav(tmp_path, monkeypatch, lang, text):
    kokoro = _wz(tmp_path, monkeypatch, [(lang, text)])
    d = tts.synth(text, str(tmp_path / "a.wav"), lang=lang, pad=0.25)
    assert abs(d - 2.3) < 0.05 and not kokoro and not wazobia.MISSES


@pytest.mark.parametrize("lang", ["yo", "ha", "ig"])
def test_miss_is_a_hard_error_never_a_fallback(tmp_path, monkeypatch, lang):
    kokoro = _wz(tmp_path, monkeypatch, [])
    with pytest.raises(wazobia.MissingLineError) as e:
        tts.synth("Line with no wav.", str(tmp_path / "a.wav"), lang=lang)
    assert not kokoro and not (tmp_path / "a.wav").exists()
    assert "missing WazobiaVoice lines: 1" in str(e.value) and f"--lang {lang}" in str(e.value) and e.value.lang == lang


def test_lang_is_part_of_the_key(tmp_path, monkeypatch):
    _wz(tmp_path, monkeypatch, [("ha", "Same text.")])
    assert wazobia.lookup("Same text.", "ha") is not None and wazobia.lookup("Same text.", "ig") is None


def test_check_lines_lists_every_missing_line(tmp_path, monkeypatch):
    _wz(tmp_path, monkeypatch, [("ig", "Have.")])
    with pytest.raises(wazobia.MissingLineError) as e:
        wazobia.check_lines(["Have.", "Miss one.", "Miss two."], "ig")
    assert e.value.missing == ["Miss one.", "Miss two."] and "lines: 2" in str(e.value)
    wazobia.check_lines(["Have."], "ig")


def test_pcm_miss_still_falls_back_to_kokoro(tmp_path, monkeypatch):
    kokoro = _wz(tmp_path, monkeypatch, [])
    monkeypatch.setattr(C, "PCM_ENGINE", "wazobia")
    tts.synth("Wetin dey happen.", str(tmp_path / "a.wav"), lang="pcm")
    assert kokoro == ["Wetin dey happen."]


def test_api_accepts_ha_ig_and_rejects_others():
    from pydantic import ValidationError
    from app import main
    model = next(v for v in vars(main).values() if isinstance(v, type) and "language" in getattr(v, "model_fields", {}))
    for lang in ("en", "pcm", "yo", "ha", "ig"):
        assert model(topic="How vaccines work", language=lang).language == lang
    for bad in ("fr", "hau", "ibo", "IG", ""):
        with pytest.raises(ValidationError):
            model(topic="How vaccines work", language=bad)


def test_translate_langs_and_prompt_rules():
    assert T.LANGS["ha"] == "Hausa" and T.LANGS["ig"] == "Igbo" and T.LANGS["yo"] == "Yoruba"
    for ch in "ƙɗɓ":
        assert ch in P.TRANSLATE
    for ch in "ịọụṅ":
        assert ch in P.TRANSLATE
    assert "Hausa" in P.CHECK_MEANING and "Igbo" in P.CHECK_MEANING


@pytest.mark.parametrize("lang", ["ha", "ig"])
def test_translation_gate_runs_for_new_langs(lang):
    from app.providers.mock import MockLLM as MockProvider
    scenes = [{"narration": "Vaccines train your immune system.", "lines": [{"text": "Vaccines train your immune system."}]}]
    m = MockProvider()
    r = T.translate_scenes(scenes, lang, m, m, lambda *a, **k: None)
    assert r["language"] == lang and scenes[0]["lines"][0]["text"].startswith(f"[{lang}]")


def test_web_picker_lists_ha_ig():
    ts = (ROOT / "web/src/lib/api.ts").read_text()
    assert '{ id: "ha", label: "Hausa"' in ts and '{ id: "ig", label: "Igbo"' in ts


def test_caption_style_mixed_case_and_fonts():
    for lang in ("yo", "ha", "ig"):
        font, up = cap.caption_style(lang)
        assert up("ƙɗɓ ịọụ") == "ƙɗɓ ịọụ"
    assert cap.caption_style("ha")[0] == "DejaVu Sans" and cap.caption_style("ig")[0] == "Noto Sans"
    assert cap.caption_style("en")[1]("abc") == "ABC"


def _font_file(family):
    import subprocess
    out = subprocess.run(["fc-match", "-f", "%{file}", f"{family}:bold"], capture_output=True, text=True)
    return out.stdout.strip() if out.returncode == 0 else ""


@pytest.mark.parametrize("lang,chars", [("yo", "ẸẹỌọṢṣÀàÁá\u0300\u0301\u0323"), ("ha", "ƘƙƊɗƁɓ"), ("ig", "ỊịỌọỤụṄṅ")])
def test_caption_font_has_the_glyphs(lang, chars):
    fontTools = pytest.importorskip("fontTools.ttLib")
    family = cap.caption_style(lang)[0]
    f = _font_file(family)
    if family.split()[0].lower() not in Path(f).name.lower():
        pytest.skip(f"{family} not installed here")
    cmap = fontTools.TTFont(f).getBestCmap()
    assert [c for c in chars if ord(c) not in cmap] == []


def test_hausa_font_draws_hooked_k_differently_from_k():
    PIL = pytest.importorskip("PIL.ImageFont")
    from PIL import Image, ImageDraw
    f = _font_file(cap.caption_style("ha")[0])
    if "dejavu" not in f.lower():
        pytest.skip("DejaVu Sans not installed")
    font = PIL.truetype(f, 80)
    def ink(ch):
        im = Image.new("L", (120, 120)); ImageDraw.Draw(im).text((10, 0), ch, font=font, fill=255)
        return np.asarray(im) > 0
    assert (ink("Ƙ") ^ ink("K")).sum() > 50


def test_write_ass_uses_lang_font(tmp_path):
    w = [{"word": "Ƙwayoyin", "start": 0, "end": .4}, {"word": "ɗaya", "start": .4, "end": .8}]
    cap.write_ass(w, str(tmp_path / "c.ass"), lang="ha")
    s = (tmp_path / "c.ass").read_text()
    assert "Style: Cap,DejaVu Sans,78," in s and "Ƙwayoyin" in s


def _run(tmp_path, lang, text, translated=True):
    d = tmp_path / f"run-{lang}"; d.mkdir()
    (d / "state.json").write_text(json.dumps({"language": lang, "proof": {"translation": {"lines": 1}} if translated else {},
                                              "scenes": [{"narration": text}, {"narration": "Ọ̀rọ̀  kejì."}]}, ensure_ascii=False))
    return d


def test_export_lines_multi_lang_notebook(tmp_path):
    sys.path.insert(0, str(ROOT / "scripts"))
    import export_lines as E
    (tmp_path / "nb").mkdir()
    (tmp_path / "nb/notebook_langs_template.py").write_text((ROOT / "scripts/kaggle_notebook_langs_template.py").read_text())
    runs = [_run(tmp_path, "yo", "Àjẹsára."), _run(tmp_path, "ha", "Ƙwayoyin cuta."), _run(tmp_path, "ig", "Ọrịa.")]
    by = E.main(["--lang", "yo", str(runs[0]), "--lang", "ha", str(runs[1]), "--lang", "ig", str(runs[2]), "--notebook", str(tmp_path / "nb")])
    assert list(by) == ["yo", "ha", "ig"] and by["ha"][0]["hash"] == wazobia.text_hash("Ƙwayoyin cuta.")
    assert by["yo"][1]["text"] == "Ọ̀rọ̀ kejì."
    page = (tmp_path / "nb/c_langs.html").read_text(encoding="utf-8")
    assert page.startswith('<meta charset="utf-8">') and "Ƙwayoyin" in page
    code = (tmp_path / "nb/notebook_langs.py").read_text(encoding="utf-8")
    assert "LINES_JSON = None" not in code and 'language_id=LID' in code
    compile(code, "nb", "exec")


def test_export_lines_refuses_wrong_lang_or_untranslated(tmp_path):
    sys.path.insert(0, str(ROOT / "scripts"))
    import export_lines as E
    with pytest.raises(SystemExit):
        E.lines_for(_run(tmp_path, "ha", "x."), "ig")
    with pytest.raises(SystemExit):
        E.lines_for(_run(tmp_path, "ig", "x.", translated=False), "ig")
