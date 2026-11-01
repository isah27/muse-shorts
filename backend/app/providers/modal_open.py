"""Tier B: open-weight image generation + SAM on Modal GPUs. Deployed from backend/modal_app/muse_modal.py (`modal deploy`).

Needs Modal credentials in the environment (MODAL_TOKEN_ID / MODAL_TOKEN_SECRET or ~/.modal.toml). The Modal client
is imported lazily so the rest of the backend runs without it."""
from __future__ import annotations
import io
from PIL import Image
from .. import config as C
from .base import Segment

def _cls(name: str):
    import modal
    return modal.Cls.from_name(C.MODAL_APP, name)()

class ModalImage:
    name = "Z-Image-Turbo (open weights, Modal)"
    def __init__(self):
        self._m = None
    def generate(self, prompt, out_path, seed=0, aspect="1080x1920"):
        self._m = self._m or _cls("ImageGen")
        w, h = (int(x) for x in aspect.split("x"))
        data = self._m.generate.remote(prompt, seed=seed, width=576 if h > w else 1024, height=1024 if h > w else 576)
        Image.open(io.BytesIO(data)).convert("RGB").save(out_path)
        return out_path

class ModalSAM:
    name = "SAM 3.1 (open weights, Modal)"
    def __init__(self):
        self._m = None
    def segment(self, image_path, phrase):
        self._m = self._m or _cls("Sam")
        with open(image_path, "rb") as f:
            res = self._m.segment.remote(f.read(), phrase)
        return [Segment(phrase, tuple(int(v) for v in r["box"]), score=float(r["score"])) for r in res]
