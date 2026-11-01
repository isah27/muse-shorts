"""Pre-rendered WazobiaVoice (Nigerian Pidgin, voice 'ngozi') audio, rendered on a Kaggle T4 by
kaggle_wz/notebook_lines.py. Each unzipped wz_out folder has manifest.json: {"lines": [{"index", "hash", "text", "file", ...}]}.
Lines are matched by text_hash(narration). A pcm miss falls back to Kokoro; a yo/ha/ig miss raises MissingLineError (see tts.synth)."""
from __future__ import annotations
import hashlib, json, re, unicodedata
from pathlib import Path
import soundfile as sf
from .. import config as C

class MissingLineError(RuntimeError):
    """A yo/ha/ig narration line has no pre-rendered WazobiaVoice wav. The run stops: there is no acceptable fallback voice."""
    def __init__(self, lang: str, text: str, all_missing: list[str] | None = None):
        self.lang, self.text, self.hash = lang, text, text_hash(text)
        self.missing = list(all_missing or [text])
        super().__init__(f"missing WazobiaVoice lines: {len(self.missing)} for {lang} (first hash {self.hash}): {norm_text(text)[:80]!r}. "
                         f"Render it on Kaggle (scripts/export_lines.py --lang {lang}) and unzip into {C.WAZOBIA_AUDIO_DIR}; "
                         "no fallback voice is used for yo/ha/ig.")


MISSES: list[str] = []          # narration lines that had no pre-rendered wav (fell back to Kokoro)
_index: dict[str, Path] | None = None
_index_dir: Path | None = None


def norm_text(text: str) -> str:
    t = unicodedata.normalize("NFC", text or "").strip()
    return re.sub(r"\s+", " ", t)


def text_hash(text: str) -> str:
    """Must match notebook_lines.py exactly: sha1 of NFC, whitespace-collapsed, stripped text; first 16 hex."""
    return hashlib.sha1(norm_text(text).encode("utf-8")).hexdigest()[:16]


def key(text: str, lang: str = "pcm") -> str:
    return f"{lang}:{text_hash(text)}"


def load_index(root: Path | None = None) -> dict[str, Path]:
    """Index keyed by "<lang>:<hash>" over manifest "lines" (lang defaults to pcm) and "samples"."""
    idx: dict[str, Path] = {}
    root = Path(root or C.WAZOBIA_AUDIO_DIR)
    if root.exists():
        for m in sorted(root.rglob("manifest.json")):
            try:
                data = json.loads(m.read_text())
            except Exception:  # noqa: BLE001
                continue
            for row in data.get("lines", []) + data.get("samples", []):
                f = m.parent / row.get("file", "")
                h = row.get("hash") or text_hash(row.get("text", ""))
                if row.get("file") and f.is_file():
                    idx[f"{row.get('lang') or 'pcm'}:{h}"] = f                 # later manifests (sorted) win
    return idx


def reset():
    global _index, _index_dir
    _index, _index_dir = None, None
    MISSES.clear()


def lookup(text: str, lang: str = "pcm"):
    """(samples, sr) for a pre-rendered line, or None."""
    global _index, _index_dir
    if _index is None or _index_dir != Path(C.WAZOBIA_AUDIO_DIR):
        _index, _index_dir = load_index(), Path(C.WAZOBIA_AUDIO_DIR)
    f = _index.get(key(text, lang))
    if f is None:
        return None
    a, sr = sf.read(str(f), dtype="float32", always_2d=False)
    if a.ndim > 1:
        a = a.mean(axis=1)
    return a, sr


class ModalRenderError(MissingLineError):
    """WAZOBIA_BACKEND=modal but the live Modal render failed. The run still stops (no fallback voice)."""
    def __init__(self, lang: str, texts: list[str], cause: str):
        super().__init__(lang, texts[0], texts)
        self.args = (f"Modal WazobiaVoice render failed for {len(texts)} {lang} line(s): {cause[:300]}",)


def _modal_render(lines: list[dict]) -> dict:
    import modal  # lazy: only needed for WAZOBIA_BACKEND=modal; auth comes from the caller's Modal profile/env
    cls = modal.Cls.from_name(C.WAZOBIA_MODAL_APP, "Wazobia")
    return cls().render.remote(lines, "ngozi")


def render_missing(texts, lang: str) -> int:
    """WAZOBIA_BACKEND=modal: voice every line without a wav on Modal, save under <audio dir>/modal/ with a manifest so
    lookup() finds it. Returns the number rendered. Raises ModalRenderError on any failure."""
    if C.WAZOBIA_BACKEND != "modal":
        return 0
    todo = list(dict.fromkeys(t for t in texts if lookup(t, lang) is None))
    if not todo:
        return 0
    import time
    try:
        res = _modal_render([{"text": t, "lang": lang, "index": i} for i, t in enumerate(todo)])
        rows = res["lines"]
        assert len(rows) == len(todo), f"expected {len(todo)} wavs, got {len(rows)}"
    except Exception as e:  # noqa: BLE001
        raise ModalRenderError(lang, todo, f"{type(e).__name__}: {e}") from e
    d = Path(C.WAZOBIA_AUDIO_DIR) / "modal" / f"{lang}-{time.strftime('%Y%m%d-%H%M%S')}-{text_hash(''.join(todo))[:6]}"
    d.mkdir(parents=True, exist_ok=True)
    man = {"voice": "ngozi", "backend": "modal", "gpu": res.get("gpu"), "sr": res.get("sr"), "lang": lang, "lines": []}
    for t, r in zip(todo, rows):
        h = text_hash(t); fn = f"{r.get('index', 0):02}_{h}.wav"
        (d / fn).write_bytes(r["wav"])
        man["lines"].append({"index": r.get("index"), "lang": lang, "voice": "ngozi", "hash": h, "text": t, "file": fn,
                             "seconds": r.get("seconds"), "gpu_s": r.get("gpu_s")})
    (d / "manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=2))
    global _index
    _index = None
    return len(todo)


def check_lines(texts, lang: str):
    """Fail fast before voicing anything: with WAZOBIA_BACKEND=modal, render missing lines live first; then raise
    MissingLineError listing every narration line that still has no wav."""
    texts = list(texts)
    render_missing(texts, lang)
    missing = [x for x in texts if lookup(x, lang) is None]
    if missing:
        MISSES.extend(missing)
        raise MissingLineError(lang, missing[0], missing)
