"""Run only the text stages (scope -> evidence -> sourced script -> claim critic) and print the event stream + result.
Usage:  python scripts/run_sourced.py "How neurons fire" [--json out.json]   (provider via env: MUSE_PROVIDER=baseten ...)
"""
import argparse, json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.agent.pipeline import Job

ap = argparse.ArgumentParser(); ap.add_argument("topic"); ap.add_argument("--json"); ap.add_argument("--stop", default="claims"); ap.add_argument("--voice", default="af_heart"); a = ap.parse_args()
events, t0 = [], time.time()
def emit(ev):
    events.append(ev)
    if ev["status"] != "progress" or ev["step"] not in ("claims",):
        print(f"[{time.time() - t0:5.1f}s] {ev['step']:9} {ev['status']:9} {ev['message'][:230]}", flush=True)
Job("cli", {"topic": a.topic, "stop_after": (None if a.stop == "none" else a.stop), "voice": a.voice}, emit).run()
if a.json:
    Path(a.json).write_text(json.dumps(events, indent=1, default=str))
