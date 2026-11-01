"""Muse Shorts open-weights GPU functions on Modal (Tier B).

  pip install modal && modal token new           # one-time auth (workspace isahnaziru27)
  modal secret create huggingface-secret HF_TOKEN=hf_...   # token of an HF account approved for facebook/sam3 + facebook/sam3.1
  modal deploy backend/modal_app/muse_modal.py
  modal run backend/modal_app/muse_modal.py      # smoke test: generates a frame, then asks SAM to find the structures

Then run the backend with IMAGE_PROVIDER=modal SEG_PROVIDER=modal.

* ImageGen  - Tongyi-MAI/Z-Image-Turbo (Apache-2.0, ungated, 8 steps), diffusers ZImagePipeline.
* Sam       - Meta SAM 3 / 3.1 promptable concept segmentation with a noun-phrase text prompt (GATED: needs the HF secret).
  SAM_VERSION=sam3   -> image model (build_sam3_image_model, facebook/sam3 weights). Default: stills need no tracker.
  SAM_VERSION=sam3.1 -> facebook/sam3.1 multiplex checkpoint run on a one-frame video session (the 3.1 release ships only the
                        multiplex video model; there is no separate 3.1 image checkpoint). Untested on a GPU as of Oct 27.
"""
import io, os
import modal

app = modal.App("muse-shorts")
hf_cache = modal.Volume.from_name("muse-hf-cache", create_if_missing=True)
SAM_VERSION = os.environ.get("SAM_VERSION", "sam3")

image_img = (modal.Image.debian_slim(python_version="3.11")
             .uv_pip_install("torch==2.8.0", "transformers>=4.56", "accelerate", "safetensors", "sentencepiece", "pillow",
                             "git+https://github.com/huggingface/diffusers")
             .env({"HF_HOME": "/cache", "HF_HUB_ENABLE_HF_TRANSFER": "0"}))

sam_image = (modal.Image.from_registry("nvidia/cuda:12.6.3-devel-ubuntu22.04", add_python="3.12")
             .apt_install("git", "libgl1", "libglib2.0-0")
             .uv_pip_install("torch==2.8.0", "torchvision", index_url="https://download.pytorch.org/whl/cu126")
             .uv_pip_install("git+https://github.com/facebookresearch/sam3.git", "einops", "pillow", "numpy", "huggingface_hub")
             .env({"HF_HOME": "/cache", "SAM_VERSION": SAM_VERSION}))

@app.cls(image=image_img, gpu="L40S", volumes={"/cache": hf_cache}, scaledown_window=300, timeout=600)
class ImageGen:
    @modal.enter()
    def load(self):
        import torch
        from diffusers import ZImagePipeline
        self.pipe = ZImagePipeline.from_pretrained("Tongyi-MAI/Z-Image-Turbo", torch_dtype=torch.bfloat16).to("cuda")
        self.torch = torch

    @modal.method()
    def generate(self, prompt: str, seed: int = 0, width: int = 576, height: int = 1024) -> bytes:
        g = self.torch.Generator("cuda").manual_seed(int(seed))
        img = self.pipe(prompt=prompt, height=height, width=width, num_inference_steps=9, guidance_scale=0.0, generator=g).images[0]
        buf = io.BytesIO(); img.save(buf, format="PNG")
        return buf.getvalue()

@app.cls(image=sam_image, gpu="L40S", volumes={"/cache": hf_cache}, secrets=[modal.Secret.from_name("huggingface-secret")],
         scaledown_window=300, timeout=600)
class Sam:
    @modal.enter()
    def load(self):
        from sam3.model_builder import build_sam3_image_model
        from sam3.model.sam3_image_processor import Sam3Processor
        # Image checkpoint = facebook/sam3 (gated; same HF approval group as sam3.1).
        self.proc = Sam3Processor(build_sam3_image_model(), confidence_threshold=0.3)

    @modal.method()
    def segment(self, image_bytes: bytes, phrase: str) -> list[dict]:
        from PIL import Image
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        state = self.proc.set_image(img)
        out = self.proc.set_text_prompt(state=state, prompt=phrase)
        boxes, scores = out["boxes"], out["scores"]
        return [{"box": [float(v) for v in b.tolist()], "score": float(s)} for b, s in zip(boxes, scores)]

@app.local_entrypoint()
def main(prompt: str = "a single neuron with dendrites, axon and myelin sheath, cinematic scientific visualization, dark background",
         phrases: str = "neuron,axon,dendrites"):
    png = ImageGen().generate.remote(prompt)
    open("/tmp/muse_smoke.png", "wb").write(png)
    for ph in phrases.split(","):
        print(ph, Sam().segment.remote(png, ph.strip()))
