"""Meta MMS-TTS (VITS, CC-BY-NC 4.0 weights on Hugging Face) run locally on CPU for Yoruba and Nigerian Pidgin.

facebook/mms-tts-yor's vocabulary contains the Yoruba tone marks and dot-below letters, so text goes in as NFC Unicode
(no romanisation): the tones written by the translator are what the voice reads.
"""
from __future__ import annotations
import threading, unicodedata
import numpy as np
from .. import config as C

MODELS = {"yo": "facebook/mms-tts-yor", "pcm": "facebook/mms-tts-pcm"}
_cache: dict[str, tuple] = {}
_lock = threading.Lock()


def _load(lang: str):
    with _lock:
        if lang not in _cache:
            import torch
            from transformers import VitsModel, AutoTokenizer
            torch.set_num_threads(max(1, C.MMS_THREADS))
            name = MODELS[lang]
            _cache[lang] = (AutoTokenizer.from_pretrained(name), VitsModel.from_pretrained(name).eval())
        return _cache[lang]


def clean(text: str, lang: str) -> str:
    t = unicodedata.normalize("NFC", text)
    t = t.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    if lang == "pcm":   # vocab is a-z, digits and '-' only; punctuation is dropped by the tokenizer anyway
        t = t.lower()
    return t


def synth(text: str, lang: str, speaking_rate: float = 1.0, seed: int = 0) -> tuple[np.ndarray, int]:
    """Returns (float32 mono samples, sample_rate). Sentences are synthesised one by one with a short pause between them."""
    import re, torch
    tok, model = _load(lang)
    model.speaking_rate = speaking_rate
    sr = model.config.sampling_rate
    parts = [p for p in re.split(r"(?<=[.!?…])\s+", clean(text, lang)) if p.strip()]
    out = []
    for p in parts:
        ids = tok(p, return_tensors="pt")
        if ids.input_ids.shape[1] < 2:
            continue
        torch.manual_seed(seed)
        with torch.no_grad():
            w = model(**ids).waveform[0].numpy().astype("float32")
        out += [w, np.zeros(int(sr * C.SENTENCE_PAUSE), dtype="float32")]
    if not out:
        raise RuntimeError(f"MMS ({lang}) produced no audio for: {text[:80]}")
    return np.concatenate(out[:-1]), sr
