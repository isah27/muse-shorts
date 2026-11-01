# Image + SAM gate: provider tiers

The gate (`backend/app/agent/gate.py`) is provider-independent: an image passes only if SAM finds every structure the scene must show
(score >= 0.5, box 1-92% of frame, two structures may not share one region (IoU > 0.7), one clear instance). Otherwise regenerate (new seed, missing parts named in the prompt) up to 2 times,
then drop that label and keep the best frame. Events: step `frame_qa`, status `retry`, kind `reject | regenerate | drop_label`.

| Tier | Env | Needs |
|---|---|---|
| A (Meta API) | `IMAGE_PROVIDER=meta SEG_PROVIDER=meta MODEL_API_KEY=...` | Meta Model API key (Muse Image + SAM via /responses) |
| B (open weights on Modal) | `IMAGE_PROVIDER=modal SEG_PROVIDER=modal` | `modal token new`; `modal secret create huggingface-secret HF_TOKEN=...` (account with access to facebook/sam3 and sam3.1); `modal deploy backend/modal_app/muse_modal.py` |
| Offline mock | default | nothing (mock flaws on by default, `MOCK_FLAWS=0` to disable) |

Tier B image model: Tongyi-MAI/Z-Image-Turbo (Apache-2.0, ungated). SAM: `facebook/sam3` image model by default.
`facebook/sam3.1` is a video-multiplex checkpoint only (no still-image API), so 3.1 would run through a one-frame video session: not implemented or verified.

## Tier A: verified live (2026-10-27)

- Image: `POST /v1/images/generations`, `muse-image-1.0`, `size=1080x1920` -> 1152x2048 PNG (b64_json). 7-25 s per image; `usage` reports roughly 15-28k total tokens per image.
- SAM: `POST /v1/responses`, `sam-3.1`, noun phrase + data-URL image -> `<|box;...|><|mask;...|>` per instance. 1.6-4 s per phrase. No confidence score is returned (the gate treats it as 1.0 and labels the largest instance); an empty string means "not found".
- SAM 3.1 vocabulary: finds whole, discrete objects named by simple nouns (heart, neuron, brain, cerebellum, cell). It does not find sub-parts, surfaces or processes (axon, membrane, ion channel, myelin, aorta, left ventricle, impulse). The writer prompt therefore restricts on-screen structures to such nouns and the retry prompt asks for "one whole object, centered, with empty space around it".
- Muse Image paints text and infographic panels unless the prompt forbids them strongly (see `STYLE`).
- Result with the tuned prompts (3 topics, 5-6 frames each): structure pass rate 80-100%, first-try frame pass rate 17-60%, <= 1 dropped label per topic, 2 minutes of gate time per topic.
- Known limit: SAM answers by name, not by anatomy. A painted brain can be accepted as "cerebellum"; the same-region rule stops the worst case (brain and cerebellum on the same box) but a human should still spot-check labels.
