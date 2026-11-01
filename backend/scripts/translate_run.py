"""Translation-only language remake: reuse a verified (English or other-language) run, run the translation gate
(translate -> back-translate -> claim critic) for --language, and save the new run WITHOUT rendering. Its narration lines
are then exported for the WazobiaVoice Kaggle run (scripts/export_lines.py); revoice.py renders once the wavs exist.
Usage: LLM_PROVIDER=baseten python scripts/translate_run.py SOURCE_RUN --language ha|ig|yo|pcm"""
import argparse, json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.agent.orchestrator import AgentJob

ap = argparse.ArgumentParser(); ap.add_argument("source"); ap.add_argument("--language", required=True, choices=["yo", "pcm", "ha", "ig"])
a = ap.parse_args()
src = json.loads((Path(__file__).resolve().parents[2] / "outputs" / a.source / "state.json").read_text())
emit = lambda ev: ev["status"] != "progress" and print(f"{ev['step']:9} {ev['status']:11} {ev['message'][:200]}", flush=True)
job = AgentJob("tr" + time.strftime("%H%M%S"), {"topic": src["topic"], "language": a.language, "remake_from": a.source}, emit)
job.setup()
obs = job.tool("translate_script", {})
job.save()
print("translate:", json.dumps({k: v for k, v in obs.items() if k != "trace"}, ensure_ascii=False)[:600])
print("RUN DIR", job.dir)
sys.exit(0 if obs.get("ok") and not obs.get("flagged") else 1)
