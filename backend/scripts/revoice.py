"""Re-voice an existing Short from its saved, already-verified scenes (no re-translation, so narration text hashes still match
the pre-rendered WazobiaVoice wavs). Copies the run into a new folder, re-renders (voice, captions, video) and runs finish_short.
Usage: PCM_ENGINE=wazobia python scripts/revoice.py RUN_DIR_NAME [--lang pcm|yo|ha|ig]
yo/ha/ig use WazobiaVoice by default (VOICE_ENGINE_YO/HA/IG=wazobia); any missing line stops the run before voicing."""
import argparse, json, shutil, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import config as C
from app.agent.orchestrator import AgentJob
from app.media import wazobia

ap = argparse.ArgumentParser()
ap.add_argument("run"); ap.add_argument("--lang", choices=["pcm", "yo", "ha", "ig"])
a = ap.parse_args()
src = C.OUTPUT_DIR / a.run
st = json.loads((src / "state.json").read_text())
lang = st.get("language") or st.get("opts", {}).get("language")
if a.lang and a.lang != lang:
    sys.exit(f"{src.name} is a '{lang}' run, not '{a.lang}' (re-voicing never re-translates)")
if lang not in C.WAZOBIA_LANGS:
    sys.exit(f"{src.name}: language '{lang}' has no WazobiaVoice")
dst = C.OUTPUT_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}-{src.name.split('-', 2)[-1]}-revoice"
shutil.copytree(src, dst, ignore=shutil.ignore_patterns("video.mp4", "voiceover.*", "captions.srt", "share.json", "audio", "work"))
for sub in ("audio", "work"):
    (dst / sub).mkdir(exist_ok=True)
txt = (dst / "state.json").read_text().replace(f"/outputs/{src.name}/", f"/outputs/{dst.name}/")
(dst / "state.json").write_text(txt)
emit = lambda ev: ev["status"] != "progress" and print(f"{ev['step']:9} {ev['status']:11} {ev['message'][:160]}", flush=True)
job = AgentJob("revoice" + time.strftime("%H%M%S"), {"topic": st["topic"], "language": st["language"], "resume": dst.name}, emit)
job.setup()
wazobia.reset()
if lang in C.WAZOBIA_STRICT_LANGS:   # fail before copying work into a half-voiced Short
    try:
        wazobia.check_lines([s["narration"] for s in job.scenes], lang)
    except wazobia.MissingLineError as e:
        print("STOP:", e); print("missing hashes:", [wazobia.text_hash(x) for x in e.missing])
        shutil.rmtree(dst); sys.exit(2)
from app.media import tts
job.flags.append(f"re-voiced from {src.name} ({tts.engine_name(lang)})")
from app.agent import verify as V
if not (job.proof.get("fingerprints") or {}).get("frames"):   # runs older than fingerprinting: same as a language remake,
    rels = job._frame_files()                                   # re-fingerprint the copied, already SAM-approved frames
    assert all(s.get("gate") and s.get("labeled") for s in job.scenes), "source frames were never SAM-gated"
    assert V.fingerprint(dst, rels) == V.fingerprint(src, rels), "copied frames differ from the source run"
    job._fp("frames", rels)
wazobia.reset()
obs = job.tool("render_video", {})
print("render:", {k: v for k, v in obs.items() if k != "trace"} if "error" in obs else "ok")
print("wazobia.MISSES:", wazobia.MISSES)
fin = job.tool("finish_short", {"summary": f"re-voiced with WazobiaVoice ngozi ({lang})"})
print("finish:", json.dumps(fin)[:600])
if fin.get("status") == "done":
    job._end("done", fin["summary"])
else:
    job.save()
print("RUN DIR", dst)
sys.exit(0 if fin.get("status") == "done" and not wazobia.MISSES else 1)
