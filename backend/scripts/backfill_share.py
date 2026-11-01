"""Write share.json (feeds /s/<id> and the gallery) for runs made before the pipeline did it: backfill_share.py events.json [...]"""
import json, sys, time, uuid
from pathlib import Path
from app import config as C
for f in sys.argv[1:]:
    ev = json.load(open(f))
    start = next(e for e in ev if e["step"] == "job" and e["status"] == "start")
    done = next(e for e in reversed(ev) if e["step"] == "job" and e["status"] == "done" and e.get("video"))
    d = Path(start["dir"]) if Path(start["dir"]).is_absolute() else C.OUTPUT_DIR / Path(start["dir"]).name
    d = C.OUTPUT_DIR / Path(d).name
    payload = {k: v for k, v in done.items() if k not in ("step", "status", "message", "t")}
    payload.setdefault("topic", d.name.split("-", 2)[-1].replace("-", " "))
    sid = uuid.uuid4().hex[:10]
    (d / "share.json").write_text(json.dumps({"id": sid, "created": d.stat().st_mtime, "language": "en", **payload}))
    print(d.name, sid)
