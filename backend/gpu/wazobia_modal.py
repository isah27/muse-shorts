import os
"""WazobiaVoice (Axiveri/WazobiaVoice, Chatterbox-based) Pidgin TTS on a Modal GPU.

NOT DEPLOYED. Setup (Isah, once):
    pip install modal && modal setup                 # browser sign-in (account already exists)
    modal secret create huggingface HF_TOKEN=...     # read token with WazobiaVoice access
Run / deploy:
    modal run backend/gpu/wazobia_modal.py --text "Your body dey fight germs every day."
    modal deploy backend/gpu/wazobia_modal.py        # then call from the backend:
        fn = modal.Function.from_name("muse-wazobia-tts", "WazobiaTTS.synthesize")
        wavs = fn.remote(lines=[...], voice="ngozi")  # list[bytes] (WAV)

Runaway fix: upstream generate() hardcodes max_new_tokens=1000 and only stops when the
model samples the stop-speech token (6562); there is no alignment-based forced EOS. We
cap tokens per line from text length (S3 tokens run at 25/s) and use slightly lower
temperature, so a line that "never stops" is cut at ~2x its expected length.
"""
import io
import modal

APP_NAME = "muse-wazobia-tts"
REPO = "https://github.com/Ememzyvisuals/wazobiavoice-TTS.git"
GPU = os.environ.get("WAZOBIA_GPU", "L4")

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("git", "ffmpeg", "libsndfile1")
    .pip_install(
        "numpy>=2.0", "torch==2.6.0", "torchaudio==2.6.0",
        "transformers>=4.45,<5.1", "huggingface_hub>=0.30", "safetensors>=0.4.1",
        "s3tokenizer", "einops", "soundfile", "omegaconf", "resemble-perth",
        "conformer==0.3.2", "librosa>=0.10", "onnxruntime", "pyloudnorm",
        "diffusers>=0.27", "loguru", "tqdm",
    )
    .run_commands(f"git clone --depth 1 {REPO} /opt/wvt", "pip install --no-deps -e /opt/wvt")
)
hf_cache = modal.Volume.from_name("wazobia-hf-cache", create_if_missing=True)
app = modal.App(APP_NAME, image=image)

TOKENS_PER_SEC = 25
CHARS_PER_SEC = 13  # conservative Pidgin speaking rate


def token_cap(text: str) -> int:
    expected = max(1.5, len(text) / CHARS_PER_SEC) * TOKENS_PER_SEC
    return int(min(1000, expected * 2 + 50))


@app.cls(gpu=GPU, timeout=900, scaledown_window=60,
         secrets=[modal.Secret.from_name("huggingface")],
         volumes={"/root/.cache/huggingface": hf_cache})
class WazobiaTTS:
    @modal.enter()
    def load(self):
        import functools
        from huggingface_hub import hf_hub_download
        from wazobiavoice_tts.mtl_tts import WazobiaVoiceMultilingualTTS
        self.model = WazobiaVoiceMultilingualTTS.from_pretrained("cuda")
        self._orig_inf = self.model.t3.inference
        self._cap = 1000

        @functools.wraps(self._orig_inf)
        def capped(*a, **kw):
            kw["max_new_tokens"] = self._cap
            return self._orig_inf(*a, **kw)
        self.model.t3.inference = capped
        self.voices = {}
        self._dl = lambda name: hf_hub_download("Axiveri/WazobiaVoice", f"inbuilt_voices/{name}.wav")
        hf_cache.commit()

    @modal.method()
    def synthesize(self, lines: list[str], voice: str = "ngozi", language_id: str = "pcm",
                   exaggeration: float = 0.5, cfg_weight: float = 0.5,
                   temperature: float = 0.7) -> list[bytes]:
        import soundfile as sf
        ref = self.voices.get(voice) or self.voices.setdefault(voice, self._dl(voice))
        self.model.prepare_conditionals(ref, exaggeration=exaggeration)
        out = []
        for line in lines:
            self._cap = token_cap(line)
            wav = self.model.generate(line, language_id=language_id, exaggeration=exaggeration,
                                      cfg_weight=cfg_weight, temperature=temperature)
            buf = io.BytesIO()
            sf.write(buf, wav.squeeze(0).numpy(), self.model.sr, format="WAV")
            out.append(buf.getvalue())
        return out

    @modal.method()
    def synthesize_timed(self, lines: list[str], voice: str = "ngozi", **kw) -> dict:
        import time, torch
        t0 = time.time()
        steps = []
        orig = self.model.t3.inference
        def counting(*a, **k):
            r = orig(*a, **k)
            steps.append((int(r.shape[-1]), self._cap))
            return r
        self.model.t3.inference = counting
        try:
            wavs = self.synthesize.local(lines, voice=voice, **kw)
        finally:
            self.model.t3.inference = orig
        return {"wavs": wavs, "meta": {"gpu_s": round(time.time() - t0, 1), "gpu": torch.cuda.get_device_name(0),
                "tokens_vs_cap": steps}}


@app.local_entrypoint()
def main(text: str = "Your body dey fight germs every day, even when you no sabi.",
         voice: str = "ngozi", lines_file: str = "", out_prefix: str = "wazobia"):
    """--lines-file: one line per row; --voice may be comma-separated. Writes <prefix>_<voice>_<i>.wav + timing json."""
    import json, time
    lines = [l.strip() for l in open(lines_file) if l.strip()] if lines_file else [text]
    tts = WazobiaTTS()
    report = {}
    for v in voice.split(","):
        t0 = time.time()
        res = tts.synthesize_timed.remote(lines, voice=v)
        report[v] = {"wall_s": round(time.time() - t0, 1), **res["meta"]}
        for i, w in enumerate(res["wavs"]):
            open(f"{out_prefix}_{v}_{i+1}.wav", "wb").write(w)
    open(f"{out_prefix}_report.json", "w").write(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
