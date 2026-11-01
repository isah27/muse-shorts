"""Meta Model API adapters (https://api.meta.ai/v1). Shapes follow dev.meta.ai docs (Oct 2026)."""
from __future__ import annotations
import base64, io, json, re, time, uuid, threading
import httpx
from PIL import Image
from .. import config as C
from .base import Segment, Transcript
from .openai_compat import ChatLLM

def _h():
    if not C.META_API_KEY:
        raise RuntimeError("MODEL_API_KEY not set — create one at dev.meta.ai > API keys")
    return {"Authorization": f"Bearer {C.META_API_KEY}"}

def meta_llm() -> ChatLLM:
    # Muse Spark always reasons; reasoning_effort "none" -> HTTP 400.
    return ChatLLM("Muse Spark (Meta API)", C.META_BASE_URL, C.META_API_KEY, C.META_LLM_MODEL,
                   json_mode=True, extra={"reasoning_effort": C.META_REASONING})

class _Stats:
    """Call count / wall seconds / provider usage, so the proof file can report latency and cost per frame."""
    def __init__(self): self.calls, self.seconds, self.usage, self._l = 0, 0.0, {}, threading.Lock()
    def add(self, dt, usage=None):
        with self._l:
            self.calls += 1; self.seconds += dt
            for k, v in (usage or {}).items():
                if isinstance(v, (int, float)): self.usage[k] = self.usage.get(k, 0) + v
    def public(self): return {"calls": self.calls, "avg_seconds": round(self.seconds / self.calls, 2) if self.calls else 0, "usage": self.usage}

class MetaImage:
    name = "Muse Image"
    def __init__(self): self.stats = _Stats()
    def generate(self, prompt, out_path, seed=0, aspect="1080x1920"):
        # POST /v1/images/generations — size only sets aspect ratio; default response is b64_json.
        t0 = time.time()
        r = httpx.post(f"{C.META_BASE_URL}/images/generations", headers=_h(), timeout=300, json={
            "model": C.META_IMAGE_MODEL, "prompt": prompt, "n": 1, "size": aspect,
            "response_format": "b64_json", "output_format": "png"})
        r.raise_for_status()
        self.stats.add(time.time() - t0, r.json().get("usage"))
        img = Image.open(io.BytesIO(base64.b64decode(r.json()["data"][0]["b64_json"]))).convert("RGB")
        img.save(out_path)
        return out_path

_BOX = re.compile(r"<\|box;x1=(\d+);y1=(\d+);x2=(\d+);y2=(\d+);w=(\d+);h=(\d+)\|>")

class MetaSAM:
    name = "SAM 3.1"
    def __init__(self): self.stats = _Stats()
    def segment(self, image_path, phrase):
        # POST /v1/responses with model sam-3.1: input_text noun phrase + input_image (data URL ok).
        b64 = base64.b64encode(open(image_path, "rb").read()).decode()
        t0 = time.time()
        r = httpx.post(f"{C.META_BASE_URL}/responses", headers=_h(), timeout=180, json={
            "model": C.META_SEG_MODEL,
            "input": [{"type": "message", "role": "user", "content": [
                {"type": "input_text", "text": phrase},
                {"type": "input_image", "image_url": f"data:image/png;base64,{b64}"}]}]})
        r.raise_for_status()
        self.stats.add(time.time() - t0, (r.json().get("usage") or {}) | {"images_processed": (r.json().get("usage") or {}).get("images_processed", 1)})
        text = _output_text(r.json())
        W, H = Image.open(image_path).size
        segs = []
        try:  # official parser decodes masks if installed: pip install meta_sam_parser
            import meta_sam_parser  # noqa: F401  (wire up mask decoding here once tested with a key)
        except ImportError:
            pass
        for m in _BOX.finditer(text):  # boxes are in the model's w/h space; rescale to image
            x1, y1, x2, y2, w, h = map(int, m.groups())
            sx, sy = W / w, H / h
            segs.append(Segment(phrase, (int(x1 * sx), int(y1 * sy), int(x2 * sx), int(y2 * sy))))
        return segs

def _output_text(resp: dict) -> str:
    if resp.get("output_text"):
        return resp["output_text"]
    out = []
    for item in resp.get("output", []):
        for c in item.get("content", []) or []:
            if c.get("type") in ("output_text", "text"):
                out.append(c.get("text", ""))
    return "".join(out)

class MetaTranscribe:
    name = "Muse Voice Transcribe"
    def transcribe(self, wav_path, keywords=None):
        # POST /v1/asr/transcribe multipart: request(JSON) + audio (mono s16 WAV 16/24 kHz).
        # Returns transcript + turn-level timestamps (no word timestamps).
        req = {"model": C.META_ASR_MODEL, "audioEncoding": "WAV", "mode": "ENDPOINTING"}
        if keywords:
            req["keywords"] = keywords[:50]
        with open(wav_path, "rb") as f:
            r = httpx.post(f"{C.META_BASE_URL}/asr/transcribe", params={"sessionId": uuid.uuid4().hex},
                           headers={**_h(), "Accept": "application/json"}, timeout=300,
                           files={"request": (None, json.dumps(req), "application/json"),
                                  "audio": ("voice.wav", f, "audio/wav")})
        r.raise_for_status()
        return Transcript(r.json().get("transcript", ""))
