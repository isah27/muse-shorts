"""TTS. English: Kokoro-82M (ONNX, Apache-2.0) with Piper fallback. Yoruba / Nigerian Pidgin: Meta MMS-TTS on CPU
(Pidgin defaults to Kokoro with a Pidgin pronunciation lexicon, see pidgin_lexicon.py). Every scene is loudness-normalised (TARGET_LUFS) and written as 24 kHz mono WAV."""
from __future__ import annotations
import subprocess
import numpy as np
import soundfile as sf
from .. import config as C

VOICES = {"af_heart": "Heart · warm female", "am_michael": "Michael · confident male",
          "bf_emma": "Emma · British female", "am_fenrir": "Fenrir · deep male", "af_bella": "Bella · bright female"}
SR = 24000
_kokoro = None


def voice_engine(lang: str = "en") -> str:
    if lang == "pcm" and C.PCM_ENGINE == "wazobia":
        return "wazobia"
    eng = {"yo": C.VOICE_ENGINE_YO, "ha": C.VOICE_ENGINE_HA, "ig": C.VOICE_ENGINE_IG}.get(lang)
    if eng == "wazobia":
        return "wazobia"
    if lang == "yo" and eng == "mms":
        return "mms"
    if lang in ("ha", "ig"):    # Kokoro has no Hausa/Igbo voice; never read them with English phonetics
        raise ValueError(f"VOICE_ENGINE_{lang.upper()}={eng!r}: only 'wazobia' is supported for {lang}")
    if lang == "pcm" and C.VOICE_ENGINE_PCM == "mms":
        return "mms"
    return "kokoro"


def engine_name(lang: str = "en") -> str:
    if voice_engine(lang) == "wazobia":
        fb = "no fallback: missing line stops the run" if lang in C.WAZOBIA_STRICT_LANGS else "Kokoro fallback"
        if C.WAZOBIA_BACKEND == "modal":
            return f"WazobiaVoice (ngozi, {lang}, live on Modal GPU); Modal failure stops the run"
        return f"WazobiaVoice (ngozi, {lang}, pre-rendered on Kaggle T4); {fb}"
    if voice_engine(lang) == "mms":
        return f"Meta MMS-TTS ({ {'yo': 'mms-tts-yor', 'pcm': 'mms-tts-pcm'}[lang]})"
    if lang == "pcm" and C.KOKORO_MODEL.exists() and C.PCM_LEXICON:
        return "Kokoro-82M + Pidgin lexicon"
    return "Kokoro-82M" if C.KOKORO_MODEL.exists() else ("Piper" if C.PIPER_MODEL else "none")


def _resample(x: np.ndarray, sr: int, to: int = SR) -> np.ndarray:
    if sr == to:
        return x
    n = int(round(len(x) * to / sr))
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype("float32")


def normalize(x: np.ndarray, sr: int, target: float | None = None) -> np.ndarray:
    """Integrated-loudness normalisation (ITU-R BS.1770 via pyloudnorm), peak-limited to -1 dBFS."""
    target = C.TARGET_LUFS if target is None else target
    try:
        import pyloudnorm as pyln
        lufs = pyln.Meter(sr).integrated_loudness(x.astype("float64"))
        if np.isfinite(lufs):
            x = x * (10 ** ((target - lufs) / 20))
    except Exception:  # noqa: BLE001  (too-short clip or lib missing: fall back to peak normalisation)
        pk = float(np.abs(x).max() or 1)
        x = x * (0.5 / pk)
    pk = float(np.abs(x).max() or 0)
    if pk > 0.891:
        x = x * (0.891 / pk)
    return x.astype("float32")


def pcm_voice(voice: str) -> str:
    """Pidgin keeps an explicitly picked voice; the app-wide default (af_heart) is swapped for PCM_VOICE."""
    return C.PCM_VOICE if (voice in (None, "", "af_heart") and C.PCM_VOICE) else voice


def _kokoro_samples(text, voice, speed, lang="en"):
    global _kokoro
    if C.KOKORO_MODEL.exists():
        from kokoro_onnx import Kokoro
        if _kokoro is None:
            _kokoro = Kokoro(str(C.KOKORO_MODEL), str(C.KOKORO_VOICES))
        if lang == "pcm":
            voice = pcm_voice(voice)
        voice = voice if voice in VOICES else "af_heart"
        if lang == "pcm" and C.PCM_LEXICON:
            from .pidgin_lexicon import phonemize
            ph = phonemize(text, lambda chunk: _kokoro.tokenizer.phonemize(chunk, "en-us"))
            return _kokoro.create(ph, voice=voice, speed=speed, is_phonemes=True)
        return _kokoro.create(text, voice=voice, speed=speed, lang="en-us")
    if C.PIPER_MODEL:
        import tempfile, os
        tmp = tempfile.mktemp(suffix=".wav")
        subprocess.run(["piper", "--model", C.PIPER_MODEL, "--output_file", tmp], input=text.encode(), check=True)
        s, sr = sf.read(tmp); os.unlink(tmp)
        return s, sr
    raise RuntimeError("No TTS engine: download Kokoro model files (scripts/setup.sh)")


def synth(text: str, out_wav: str, voice: str = "af_heart", speed: float = 1.05, pad: float = 0.25, lang: str = "en") -> float:
    """Synthesize one scene; returns duration in seconds (including trailing pad)."""
    eng = voice_engine(lang)
    if eng == "wazobia":
        from . import wazobia
        hit = wazobia.lookup(text, lang)
        if hit is None and C.WAZOBIA_BACKEND == "modal":
            wazobia.render_missing([text], lang)          # raises ModalRenderError (run stops) if Modal fails
            hit = wazobia.lookup(text, lang)
        if hit is not None:
            samples, sr = hit
            samples = normalize(_resample(np.asarray(samples, dtype="float32"), sr), SR)
            samples = np.concatenate([np.zeros(int(SR * 0.05)), samples, np.zeros(int(SR * pad))]).astype("float32")
            sf.write(out_wav, samples, SR, subtype="PCM_16")
            return len(samples) / SR          # real wav length drives scene start / caption timing
        wazobia.MISSES.append(text)
        if lang in C.WAZOBIA_STRICT_LANGS:
            raise wazobia.MissingLineError(lang, text)
        samples, sr = _kokoro_samples(text, voice, speed, lang)
    elif eng == "mms":
        from . import mms
        samples, sr = mms.synth(text, lang, speaking_rate=(C.MMS_RATE_YO if lang == "yo" else C.MMS_RATE_PCM) * speed / 1.05)
    else:
        samples, sr = _kokoro_samples(text, voice, speed, lang)
    samples = normalize(_resample(np.asarray(samples, dtype="float32"), sr), SR)
    samples = np.concatenate([np.zeros(int(SR * 0.05)), samples, np.zeros(int(SR * pad))]).astype("float32")
    sf.write(out_wav, samples, SR, subtype="PCM_16")
    return len(samples) / SR
