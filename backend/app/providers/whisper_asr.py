"""Local fallback ASR (faster-whisper) — also gives word timestamps for tight captions."""
from __future__ import annotations
from .. import config as C
from .base import Transcript

_model = None
class WhisperASR:
    name = "faster-whisper (local)"
    def transcribe(self, wav_path, keywords=None):
        global _model
        from faster_whisper import WhisperModel
        if _model is None:
            _model = WhisperModel(C.WHISPER_MODEL, device="cpu", compute_type="int8")
        import subprocess, numpy as np
        pcm = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", wav_path, "-f", "s16le", "-ac", "1", "-ar", "16000", "-"],
                             capture_output=True, check=True).stdout
        audio = np.frombuffer(pcm, np.int16).astype(np.float32) / 32768.0
        segs, _ = _model.transcribe(audio, word_timestamps=True,
                                    initial_prompt=", ".join(keywords or []) or None)
        words, text = [], []
        for s in segs:
            text.append(s.text)
            for w in s.words or []:
                words.append({"word": w.word.strip(), "start": w.start, "end": w.end})
        return Transcript(" ".join(t.strip() for t in text), words)
