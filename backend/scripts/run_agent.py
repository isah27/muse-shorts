"""Run the orchestrator agent end to end from the CLI and print each decision.
Usage: LLM_PROVIDER=baseten IMAGE_PROVIDER=meta SEG_PROVIDER=meta python scripts/run_agent.py "How vaccines train the immune system" [--mode agent|fixed] [--max-turns 30] [--resume RUN] [--remake-from RUN --language yo]
"""
import argparse, json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.agent.orchestrator import make_job

ap = argparse.ArgumentParser(); ap.add_argument("topic"); ap.add_argument("--mode", default=None); ap.add_argument("--max-turns", type=int)
ap.add_argument("--resume"); ap.add_argument("--remake-from"); ap.add_argument("--language", default="en"); ap.add_argument("--json"); a = ap.parse_args()
events, t0 = [], time.time()
def emit(ev):
    events.append(ev)
    if ev["status"] != "progress":
        print(f"[{time.time() - t0:6.1f}s] {ev['step']:9} {ev['status']:11} {ev['message'][:200]}", flush=True)
job = make_job("cli" + time.strftime("%H%M%S"), {"topic": a.topic, "mode": a.mode, "max_turns": a.max_turns, "resume": a.resume,
               "remake_from": a.remake_from, "language": a.language}, emit)
job.run()
print("RUN DIR", job.dir)
if a.json:
    Path(a.json).write_text(json.dumps(events, indent=1, default=str))
