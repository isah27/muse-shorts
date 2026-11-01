"""WazobiaVoice (ngozi) TTS on Modal: GPU class that renders narration lines for pcm/yo/ha/ig.
Same inference as kaggle_wz/notebook_langs.py (token cap, -50 dB trim, -16 LUFS, per-sentence seeds), so output matches
the pre-rendered Kaggle wavs. Access is via the Modal SDK (modal.Cls.from_name) using the caller's Modal auth, so there is
no public URL and no extra key. Weights live in Modal Volume "wazobia-weights" (/hf/merged_model, /hf/inbuilt_voices, /src).
Deploy: modal deploy modal_app/wazobia_tts.py"""
import modal

APP = "wazobia-tts"
image = (modal.Image.debian_slim(python_version="3.11")
         .apt_install("ffmpeg", "libsndfile1")
         .pip_install("numpy<2.0", "torch==2.5.1", "torchaudio==2.5.1", "transformers==4.46.3", "safetensors>=0.4.1",
                      "s3tokenizer", "einops", "omegaconf", "resemble-perth", "conformer==0.3.2", "pyloudnorm",
                      "diffusers>=0.27", "loguru", "librosa>=0.10", "soundfile", "onnxruntime", "huggingface_hub")
         .env({"HF_HUB_OFFLINE": "1", "TOKENIZERS_PARALLELISM": "false"}))
vol = modal.Volume.from_name("wazobia-weights")
app = modal.App(APP, image=image)

TOKENS_PER_SEC, CHARS_PER_SEC, SEED, PAUSE = 25, 13, 1234, 0.18
LANGS = ("pcm", "yo", "ha", "ig")


@app.cls(gpu="T4", volumes={"/w": vol}, scaledown_window=120, timeout=900, max_containers=1)
class Wazobia:
    @modal.enter()
    def load(self):
        import os, sys, shutil, time, functools, importlib.metadata as im
        sys.path.insert(0, "/w/src")
        _v = im.version
        def safe_version(n):
            try: return _v(n)
            except im.PackageNotFoundError: return "0.0.0"
        im.version = safe_version
        import perth
        if getattr(perth, "PerthImplicitWatermarker", None) is None:
            perth.PerthImplicitWatermarker = perth.DummyWatermarker
        import torch
        from pathlib import Path
        from safetensors.torch import load_file
        from wazobiavoice_tts.mtl_tts import (WazobiaVoiceMultilingualTTS, VoiceEncoder, T3, T3Config, S3Gen,
                                              MTLTokenizer, Conditionals)
        t = time.time(); src, ck = "/w/hf/merged_model", Path("/tmp/merged_model"); ck.mkdir(exist_ok=True)
        for fn in os.listdir(src):     # sequential copy to local disk (lazy mmap reads off network storage are slow)
            if os.path.isfile(f"{src}/{fn}"): shutil.copyfile(f"{src}/{fn}", ck / fn)
        self.copy_s = round(time.time() - t, 1); dev = "cuda"
        ve = VoiceEncoder(); ve.load_state_dict(torch.load(ck / "ve.pt", map_location="cpu", weights_only=True)); ve.to(dev).eval()
        t3 = T3(T3Config.multilingual()); sd = load_file(str(ck / "t3_mtl23ls_v2.safetensors"), device="cpu")
        if "model" in sd.keys(): sd = sd["model"][0]
        t3.load_state_dict(sd); del sd; t3.to(dev).eval()
        s3 = S3Gen(); sd = torch.load(ck / "s3gen.pt", map_location="cpu", weights_only=True, mmap=True)
        s3.load_state_dict(sd); del sd; s3.to(dev).eval()
        tok = MTLTokenizer(str(ck / "grapheme_mtl_merged_expanded_v1.json"))
        conds = Conditionals.load(ck / "conds.pt", map_location="cpu").to(dev) if (ck / "conds.pt").exists() else None
        self.model = WazobiaVoiceMultilingualTTS(t3, s3, ve, tok, dev, conds=conds)
        self.model.prepare_conditionals("/w/hf/inbuilt_voices/ngozi.wav", exaggeration=0.5)
        self.state = {"cap": 1000, "tokens": None}
        orig = self.model.t3.inference
        @functools.wraps(orig)
        def capped(*a, **kw):
            kw["max_new_tokens"] = self.state["cap"]; r = orig(*a, **kw); self.state["tokens"] = int(r.shape[-1]); return r
        self.model.t3.inference = capped
        self.load_s = round(time.time() - t, 1)
        print(f"model ready in {self.load_s}s (copy {self.copy_s}s) on {torch.cuda.get_device_name(0)}")

    def _trim_norm(self, a, sr, thr_db=-50.0, pad=0.3, target_lufs=-16.0):
        import numpy as np, pyloudnorm as pyln
        win = max(1, int(sr * 0.02)); n = len(a) // win
        if n:
            rms = np.sqrt(np.mean(a[:n * win].reshape(n, win) ** 2, axis=1) + 1e-12)
            loud = np.where(20 * np.log10(rms) > thr_db)[0]
            if len(loud):
                p = int(pad * sr); a = a[max(0, loud[0] * win - p): min(len(a), (loud[-1] + 1) * win + p)]
        try:
            l = pyln.Meter(sr).integrated_loudness(a)
            if np.isfinite(l): a = pyln.normalize.loudness(a, l, target_lufs)
        except Exception: pass
        pk = np.max(np.abs(a)) if len(a) else 0
        if pk > 0.99: a = a * (0.99 / pk)
        return a.astype("float32")

    @modal.method()
    def render(self, lines: list, voice: str = "ngozi") -> dict:
        """lines: [{"text", "lang", "index"?}] -> {"sr", "gpu", "load_s", "lines": [{"index","lang","text","wav"(bytes),"seconds","gpu_s"}]}"""
        import io, re, time, random, numpy as np, soundfile as sf, torch
        if voice != "ngozi": raise ValueError("only voice 'ngozi' is hosted")
        sr = int(self.model.sr); out = []
        for i, L in enumerate(lines):
            lang, text, idx = L["lang"], L["text"], int(L.get("index", i))
            if lang not in LANGS: raise ValueError(f"unsupported lang {lang}")
            sents = [p.strip() for p in re.split(r"(?<=[.!?])\s+", text) if p.strip()] or [text]
            pieces, t0 = [], time.time()
            for k, s in enumerate(sents):
                seed = SEED + 1000 * idx + k
                random.seed(seed); np.random.seed(seed); torch.manual_seed(seed); torch.cuda.manual_seed_all(seed)
                exp = max(1.5, len(s) / CHARS_PER_SEC) * TOKENS_PER_SEC
                self.state["cap"] = int(min(1000, int(1.3 * exp) + 40))
                wav = self.model.generate(s, language_id=lang, exaggeration=0.5, cfg_weight=0.5, temperature=0.7)
                a = self._trim_norm(wav.squeeze().detach().cpu().numpy().astype("float32"), sr, pad=0.12)
                if pieces: pieces.append(np.zeros(int(PAUSE * sr), dtype="float32"))
                pieces.append(a)
            a = self._trim_norm(np.concatenate(pieces), sr, pad=0.15)
            buf = io.BytesIO(); sf.write(buf, a, sr, format="WAV")
            out.append({"index": idx, "lang": lang, "text": text, "wav": buf.getvalue(),
                        "seconds": round(len(a) / sr, 2), "gpu_s": round(time.time() - t0, 2)})
        return {"sr": sr, "gpu": torch.cuda.get_device_name(0), "load_s": self.load_s, "lines": out}


@app.local_entrypoint()
def smoke(text: str = "Abeg, no look am say na small money.", lang: str = "pcm"):
    r = Wazobia().render.remote([{"text": text, "lang": lang}])
    open("/tmp/wz_modal_smoke.wav", "wb").write(r["lines"][0]["wav"])
    print({k: v for k, v in r.items() if k != "lines"}, [(x["seconds"], x["gpu_s"]) for x in r["lines"]])
