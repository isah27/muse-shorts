# muse-shorts: Shorts you can trust

Sourced, fact-checked vertical science Shorts (9:16, 45–75 s) in **English, Nigerian Pidgin, Yoruba, Hausa and Igbo**, made by an AI agent and approved by a human creator.

Built by Isah Neziru (Lagos) for the Meta Global AI Developer Hackathon.

## Why it matters
In Nigeria, health misinformation spreads fastest in the languages that good sources ignore. Most reliable science content is in English, while millions of people learn best in Pidgin, Yoruba, Hausa or Igbo. Faceless Short generators exist, but they don't check facts. muse-shorts makes every on-screen claim traceable to a source, drops any picture label it can't verify, and checks every translation by translating it back into English.

## How it works

```
topic ─▶ scope check ─▶ evidence (Wikipedia + PubMed) ─▶ plan ─▶ sourced script
      ─▶ claim critic (rewrite/drop) ─▶ frames (Muse Image) + SAM 3.1 gate ─▶ labels
      ─▶ translate + back-translation check (pcm/yo/ha/ig) ─▶ voice + captions + 9:16 render
      ─▶ final check (claims, labels, duration, captions, sha256) ─▶ PENDING_REVIEW ─▶ human approves
```

### Meta tooling
| Role | Model | Where |
|---|---|---|
| Agent orchestrator, writer, claim critic, translation meaning check | **Muse Spark Open** `meta-models/muse-spark-open-1026` (open weights) | Baseten (`LLM_PROVIDER=baseten`), or Meta API `muse-spark-1.3` (`meta`) |
| Frame generation | Muse Image `muse-image-1.0` | Meta API |
| Label verification gate | **SAM 3.1** `sam-3.1` | Meta API (Tier B: `facebook/sam3` on Modal, see `docs/IMAGE_TIERS.md`) |
| Optional transcription | `muse-voice-transcribe-1.0`, or faster-whisper | Meta API / local |
| Yoruba fallback voice | MMS-TTS `facebook/mms-tts-yor` | local (`VOICE_ENGINE_YO=mms`) |

Other models: **WazobiaVoice** open-weights Nigerian TTS (ngozi voice) for pcm/yo/ha/ig, and **Kokoro** (ONNX) for English.

### The agent loop (`backend/app/agent/orchestrator.py`)
The model doesn't write content itself. Each turn, it picks **one tool** (`scope_check`, `gather_evidence`, `plan_scenes`, `write_script`, `check_claims`, `translate_script`, `generate_frames`, `check_labels`, `render_video`, `finish_short`) and sees the result. **Stage gates** only allow the tools that fit the current stage, so the agent can't render before its claims pass. If the model-driven orchestrator fails, it falls back to a fixed pipeline (`AGENT_MODE=fixed`). Every run writes `state.json`, `proof.json`, `sources.json` and a human-readable `VERIFICATION_SUMMARY.txt`.

### Verification gates (`backend/app/agent/verify.py`, `gate.py`, `translate.py`)
- **Scope:** only anatomy and science explainers are allowed. Diagnosis, treatment and dosage topics are refused.
- **Domain strictness:** health, finance and legal topics need 100% of claims verified. Other topics need at least 90%, and unverified lines are cut.
- **Plan and script checks:** each claim must overlap its cited source and quote it verbatim. An LLM claim judge rejects unsupported lines and sends feedback for a rewrite.
- **Length rule:** at least 45 s, ideally 45–75 s, and longer only when the verified facts support it. Scripts are never padded.
- **SAM image gate:** a frame passes only if SAM finds every named structure (score, box size and overlap rules). If not, it regenerates up to 2 times, then drops the label. No unverified label is ever shown.
- **Translation gate:** the line is back-translated without the original, then the critic compares meaning. A line is re-translated up to 2 times, then flagged.
- **Captions and final check:** captions must match the narration (≥80%) and the voice timing. Outputs are sha256-fingerprinted. The run ends as `pending_review`, and export stays locked until a human approves it.

Example trace (vaccines, English): round 1 rejected 5 of 20 lines, round 2 passed 15/15 claims, SAM confirmed 8/8 structures, and captions matched the narration 100%.

### Voices
- **en:** Kokoro.
- **pcm, yo, ha, ig:** WazobiaVoice ngozi. Lines are pre-rendered on a Kaggle GPU and looked up by text hash (`backend/app/media/wazobia.py`, `assets/wazobia/`). For yo, ha and ig, a missing line **stops the run** with a clear error, because there's no backup voice. For pcm, a missing line falls back to Kokoro with a Pidgin lexicon.
- **Optional Modal backend:** with `WAZOBIA_BACKEND=modal`, missing lines are rendered live by `modal_app/wazobia_tts.py`. It's built but not active yet, because the Modal account needs a payment card.

## Setup and run
```bash
python -m venv .venv && source .venv/bin/activate   # backend deps in .venv
# Kokoro files: models/kokoro-v1.0.onnx, models/voices-v1.0.bin
# keys in your environment or .env (never committed): BASETEN_API_KEY, MODEL_API_KEY
cd backend && uvicorn app.main:app --port 8000          # API + SSE agent timeline
cd web && npm install && npm run dev                    # http://localhost:3000
# CLI
cd backend && LLM_PROVIDER=baseten IMAGE_PROVIDER=meta SEG_PROVIDER=meta \
  python scripts/run_agent.py "How vaccines train the immune system" [--remake-from RUN --language yo]
pytest                                                  # backend tests
```
With no keys, everything runs on mock providers (`MUSE_PROVIDER=mock`).

## Creator workflow
See **[docs/CREATOR_GUIDE.md](docs/CREATOR_GUIDE.md)**: generate in the app, export lines (`scripts/export_lines.py`), voice them on Kaggle, import them (`scripts/import_wz.py`), re-voice (`backend/scripts/revoice.py`), then review and approve.

## Limitations
- New pcm, yo, ha or ig topics need a Kaggle voicing pass (about 45–60 min) until the Modal backend is turned on.
- WazobiaVoice doesn't stop on its own, so output is capped and silence-trimmed. The voice speed adjustment doesn't apply to pre-rendered lines.
- SAM 3.1 recognises whole objects (heart, neuron) but not sub-parts (axon, myelin), so the on-screen structures are kept simple. A human should still spot-check labels.
- Pidgin, Yoruba, Hausa and Igbo audio quality was checked by ear by the creator and a few listeners, not by a formal evaluation.
- The app makes educational explainers, not medical advice.

## Credits
Meta (Muse Spark Open, Muse Image, SAM 3.1, MMS-TTS), Baseten, WazobiaVoice, Kokoro, Kaggle, Wikipedia, PubMed/NCBI, faster-whisper, ffmpeg, FastAPI, Next.js.
