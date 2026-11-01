"""Runtime configuration, driven entirely by environment variables (.env supported)."""
from __future__ import annotations
import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)

# Which provider drives each agent capability: "mock" | "meta" | "baseten" (LLM) ; image/seg also "modal" (open weights)
PROVIDER = env("MUSE_PROVIDER", "mock")             # default for everything
LLM_PROVIDER = env("LLM_PROVIDER", PROVIDER)          # planner / writer
CRITIC_PROVIDER = env("CRITIC_PROVIDER", LLM_PROVIDER) # self-review agent (try "baseten" for open weights)
IMAGE_PROVIDER = env("IMAGE_PROVIDER", "meta" if PROVIDER == "meta" else "mock")
SEG_PROVIDER = env("SEG_PROVIDER", "meta" if PROVIDER == "meta" else "mock")
ASR_PROVIDER = env("ASR_PROVIDER", "meta" if PROVIDER == "meta" else "whisper")  # meta | whisper | none

# Tier B (open weights on Modal): app deployed from backend/modal_app/muse_modal.py
MODAL_APP = env("MODAL_APP", "muse-shorts")
# SAM gate: an image passes only if every structure the scene must show is found (score + size sane, one clear instance)
# Length rule: at least 45 s, ideally 45-75 s, longer only when verified facts allow (never padded)
MIN_SECONDS = float(env("MIN_SECONDS", "45"))
IDEAL_MAX_SECONDS = float(env("IDEAL_MAX_SECONDS", "75"))
MAX_SECONDS = float(env("MAX_SECONDS", "100"))           # hard cap on the script
LENGTH_MARGIN = float(env("LENGTH_MARGIN", "3"))          # estimate must clear MIN_SECONDS by this much (TTS pacing is approximate)
LENGTH_ROUNDS = int(env("LENGTH_ROUNDS", "3"))            # extend / fetch-more-sources rounds after the claim critic
WORD_SEC = float(env("WORD_SEC", "0.37"))                 # Kokoro af_heart at speed 1.05, measured
SCENE_SEC = float(env("SCENE_SEC", "0.55"))
MIN_SOURCE_CHARS = int(env("MIN_SOURCE_CHARS", "10000"))  # fewer source characters than this -> fetch more sources before writing
GATE_MAX_REGEN = int(env("GATE_MAX_REGEN", "2"))        # regenerations after the first try, then labels that are still missing are dropped
MOCK_FLAWS = env("MOCK_FLAWS", "1") == "1"   # mock image provider forgets a structure on some first tries, to demo the gate
GATE_WORKERS = int(env("GATE_WORKERS", "6"))          # scenes processed in parallel
GATE_MIN_SCORE = float(env("GATE_MIN_SCORE", "0.5"))
GATE_MIN_AREA = float(env("GATE_MIN_AREA", "0.01"))     # box area / image area
GATE_MAX_OVERLAP = float(env("GATE_MAX_OVERLAP", "0.7"))
GATE_MAX_AREA = float(env("GATE_MAX_AREA", "0.92"))

META_API_KEY = env("MODEL_API_KEY")
META_BASE_URL = env("META_BASE_URL", "https://api.meta.ai/v1")
META_LLM_MODEL = env("META_LLM_MODEL", "muse-spark-1.3")
META_IMAGE_MODEL = env("META_IMAGE_MODEL", "muse-image-1.0")
META_SEG_MODEL = env("META_SEG_MODEL", "sam-3.1")
META_ASR_MODEL = env("META_ASR_MODEL", "muse-voice-transcribe-1.0")
META_REASONING = env("META_REASONING_EFFORT", "low")

BASETEN_API_KEY = env("BASETEN_API_KEY")
BASETEN_BASE_URL = env("BASETEN_BASE_URL", "https://inference.baseten.co/v1")
BASETEN_MODEL = env("BASETEN_MODEL", "meta-models/muse-spark-open-1026")
BASETEN_REASONING = env("BASETEN_REASONING_EFFORT", "low")  # critic/scope checks: low|medium|high; "" to omit
BASETEN_WRITER_REASONING = env("BASETEN_WRITER_REASONING_EFFORT", "medium")  # writer/planner
BASETEN_MAX_TOKENS = int(env("BASETEN_MAX_TOKENS", "12000"))  # reasoning + answer budget

KOKORO_MODEL = Path(env("KOKORO_MODEL", str(ROOT / "models/kokoro-v1.0.onnx")))
KOKORO_VOICES = Path(env("KOKORO_VOICES", str(ROOT / "models/voices-v1.0.bin")))
PIPER_MODEL = env("PIPER_MODEL")  # optional fallback .onnx voice
WHISPER_MODEL = env("WHISPER_MODEL", "base.en")

OUTPUT_DIR = Path(env("OUTPUT_DIR", str(ROOT / "outputs")))
MUSIC_DIR = Path(env("MUSIC_DIR", str(ROOT / "assets/music")))
FONT_DIR = Path(env("FONT_DIR", "/usr/share/fonts/truetype/google"))
CAPTION_FONT = env("CAPTION_FONT", "Montserrat")
MAX_REVIEW_ROUNDS = int(env("MAX_REVIEW_ROUNDS", "2"))
MAX_CLAIM_ROUNDS = int(env("MAX_CLAIM_ROUNDS", "2"))   # rewrite attempts per unsupported line before it is dropped
# Evidence retrieval: "web" (Wikipedia + PubMed) or "mock" (offline fixtures). Defaults to mock when the LLM is the mock.
EVIDENCE_PROVIDER = env("EVIDENCE_PROVIDER", "mock" if LLM_PROVIDER == "mock" else "web")
EVIDENCE_CACHE = Path(env("EVIDENCE_CACHE", str(ROOT / "outputs" / ".evidence_cache")))
CONTACT_EMAIL = env("CONTACT_EMAIL", "muse-shorts@example.com")  # sent in User-Agent / NCBI tool params
# Orchestrator: "agent" (model picks tools) | "fixed" (old pipeline). Agent falls back to fixed on orchestrator failure.
AGENT_MODE = env("AGENT_MODE", "agent")
AGENT_MAX_TURNS = int(env("AGENT_MAX_TURNS", "30"))
AGENT_REASONING = env("AGENT_REASONING_EFFORT", "low")
# ---- verification layer (Agents 102): strictness by domain, layered checks, final check
STRICT_DOMAINS = env("STRICT_DOMAINS", "health,finance,legal")      # these need 100% of claims verified
LENIENT_CLAIM_THRESHOLD = float(env("LENIENT_CLAIM_THRESHOLD", "0.9"))  # other topics: >=90%, unverified claims are cut
PLAN_MIN_OVERLAP = float(env("PLAN_MIN_OVERLAP", "0.5"))          # planned claim must share this share of its words with its source
SCRIPT_MIN_FRACTION = float(env("SCRIPT_MIN_FRACTION", "0.4"))    # deterministic draft length floor (x MIN_SECONDS) before the judge
CAPTION_MIN_MATCH = float(env("CAPTION_MIN_MATCH", "0.8"))
CAPTION_MAX_DRIFT = float(env("CAPTION_MAX_DRIFT", "2.0"))        # seconds between last caption and end of voice track
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ---- voices for Yoruba / Nigerian Pidgin (translation gate)
VOICE_ENGINE_YO = env("VOICE_ENGINE_YO", "wazobia")             # wazobia: pre-rendered WazobiaVoice ngozi (Isah, Oct 29) | mms: Meta MMS-TTS facebook/mms-tts-yor
VOICE_ENGINE_HA = env("VOICE_ENGINE_HA", "wazobia")             # Hausa: pre-rendered WazobiaVoice ngozi only
VOICE_ENGINE_IG = env("VOICE_ENGINE_IG", "wazobia")             # Igbo: pre-rendered WazobiaVoice ngozi only
WAZOBIA_LANGS = ("pcm", "yo", "ha", "ig")                        # languages WazobiaVoice can voice
WAZOBIA_STRICT_LANGS = ("yo", "ha", "ig")                       # a missing pre-rendered line STOPS the run (Kokoro has no voice for these)
VOICE_ENGINE_PCM = env("VOICE_ENGINE_PCM", "kokoro")            # kokoro (English voice reading the Pidgin text; A/B: whisper word-match 0.81 vs 0.42 for mms-tts-pcm) | mms
MMS_RATE_YO = float(env("MMS_RATE_YO", "0.8"))                  # MMS speaks fast; slow to match the English pacing
PCM_LEXICON = env("PCM_LEXICON", "1") == "1"                   # Kokoro reads Pidgin through app/media/pidgin_lexicon.py (dey=dɛ, wey=wɛ, una=una...)
PCM_VOICE = env("PCM_VOICE", "am_fenrir")                       # deeper male; replaces the default af_heart for Pidgin (A/B Oct 2026: YarnGPT2/2b dropped words, WazobiaVoice gated, SpeechT5-pcm/MMS-pcm robotic)
PCM_ENGINE = env("PCM_ENGINE", "")                             # "wazobia": use pre-rendered WazobiaVoice (ngozi) wavs from Kaggle, Kokoro+lexicon for any missing line
WAZOBIA_BACKEND = env("WAZOBIA_BACKEND", "prerendered")         # prerendered: Kaggle wavs only | modal: render missing lines live on Modal (modal_app/wazobia_tts.py)
WAZOBIA_MODAL_APP = env("WAZOBIA_MODAL_APP", "wazobia-tts")
WAZOBIA_AUDIO_DIR = Path(env("WAZOBIA_AUDIO_DIR", str(ROOT / "assets/wazobia")))  # unzipped wz_out.zip folders (manifest.json + wavs), searched recursively
MMS_RATE_PCM = float(env("MMS_RATE_PCM", "0.9"))
MMS_THREADS = int(env("MMS_THREADS", "4"))
SENTENCE_PAUSE = float(env("SENTENCE_PAUSE", "0.18"))
TARGET_LUFS = float(env("TARGET_LUFS", "-16"))                  # every voice track is loudness-normalised to this
