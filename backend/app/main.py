"""Muse Shorts API: create jobs, stream agent events over SSE, serve outputs."""
from __future__ import annotations
import asyncio, json, threading, time, uuid
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from . import config as C
from .agent.orchestrator import AgentJob, make_job
from .agent import verify as V
from .media import tts
from .providers import registry

app = FastAPI(title="Muse Shorts")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/outputs", StaticFiles(directory=C.OUTPUT_DIR), name="outputs")
JOBS: dict[str, dict] = {}

class JobIn(BaseModel):
    topic: str = Field(min_length=3, max_length=160)
    voice: str = "af_heart"
    seconds: int = 60          # target length; the pipeline enforces a 45 s minimum (config.MIN_SECONDS)
    language: str = Field(default="en", pattern="^(en|pcm|yo|ha|ig)$")   # pcm/yo/ha/ig: verified English script -> translation gate -> WazobiaVoice
    labels: bool = True
    captions: bool = True
    music: bool = False
    speed: float = 1.05
    mode: str | None = Field(default=None, pattern="^(agent|fixed)$")   # default: config.AGENT_MODE
    max_turns: int | None = Field(default=None, ge=3, le=60)
    demo_faults: bool = False                  # demo: inject one plan fault + one script fault so the trace shows fail -> feedback -> retry -> pass
    step_mode: bool = False                    # pause before every orchestrator turn; POST /api/jobs/{id}/step to advance
    resume: str | None = None                  # outputs/<run> folder to resume from its state.json
    remake_from: str | None = None             # outputs/<run> whose verified facts are reused (e.g. a Yoruba remake)
    stop_after: str | None = Field(default=None, pattern="^(claims|frames)$")  # dev/test: stop after the claim gate (no media)

@app.get("/api/health")
def health():
    return {"ok": True}

@app.get("/api/config")
def cfg():
    return {"voices": [{"id": k, "label": v} for k, v in tts.VOICES.items()],
            "providers": {"writer": registry.llm("writer").name, "critic": registry.llm("critic").name,
                          "image": registry.image().name, "segment": registry.segmenter().name,
                          "tts": tts.engine_name(), "asr": registry.asr().name},
            "mock": C.LLM_PROVIDER == "mock" or C.IMAGE_PROVIDER == "mock"}

@app.post("/api/jobs")
def create(j: JobIn):
    jid = uuid.uuid4().hex[:10]
    for k in ("resume", "remake_from"):
        v = getattr(j, k)
        if v and (".." in v or "/" in v or not (C.OUTPUT_DIR / v / "state.json").exists()):
            raise HTTPException(400, f"{k}: no saved run '{v}'")
    rec = {"events": [], "done": False}
    JOBS[jid] = rec
    def emit(ev):
        rec["events"].append(ev)
        if ev["step"] in ("job", "error") and ev["status"] in ("done", "error", "rejected"):
            rec["done"] = True
    job = make_job(jid, j.model_dump(), emit)
    rec["job"] = job
    threading.Thread(target=job.run, daemon=True).start()
    return {"id": jid, "mode": "agent" if isinstance(job, AgentJob) else "fixed", "dir": job.rel}

@app.post("/api/jobs/{jid}/step")
def step(jid: str):
    """Step-through mode: let the orchestrator take its next turn."""
    job = JOBS.get(jid, {}).get("job")
    if not isinstance(job, AgentJob):
        raise HTTPException(404, "No agent job with that id")
    job.advance()
    return {"ok": True}

@app.get("/api/jobs/{jid}")
def get(jid: str):
    if jid not in JOBS:
        raise HTTPException(404)
    return {k: v for k, v in JOBS[jid].items() if k != "job"}

@app.get("/api/jobs/{jid}/events")
async def events(jid: str, since: int = 0):
    if jid not in JOBS:
        raise HTTPException(404)
    rec = JOBS[jid]
    async def gen():
        i = since
        while True:
            while i < len(rec["events"]):
                yield f"id: {i}\ndata: {json.dumps(rec['events'][i])}\n\n"; i += 1
            if rec["done"] and i >= len(rec["events"]):
                yield "event: end\ndata: {}\n\n"; return
            yield ": ping\n\n"
            await asyncio.sleep(0.25)
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _status(d: dict) -> str:
    return d.get("status") or "approved"   # Shorts made before human sign-off existed count as approved


def _share_path(sid: str):
    for f in C.OUTPUT_DIR.glob("*/share.json"):
        try:
            if json.loads(f.read_text()).get("id") == sid:
                return f
        except Exception:  # noqa: BLE001
            pass
    return None


@app.middleware("http")
async def gate_export(request: Request, call_next):
    """The full pack (outputs/<run>.zip) is an export: blocked until a human approved the Short."""
    path = request.url.path
    if path.startswith("/outputs/") and path.endswith(".zip"):
        sp = C.OUTPUT_DIR / path[len("/outputs/"):-4] / "share.json"
        if sp.exists():
            try:
                st = _status(json.loads(sp.read_text()))
            except Exception:  # noqa: BLE001
                st = "pending_review"
            if st != "approved":
                return JSONResponse({"detail": f"Export blocked: this Short is {st}; approve it first."}, status_code=403)
    return await call_next(request)


def _shares() -> list[dict]:
    out = []
    for f in C.OUTPUT_DIR.glob("*/share.json"):
        try:
            out.append(json.loads(f.read_text()))
        except Exception:  # noqa: BLE001
            pass
    return sorted(out, key=lambda d: d.get("created", 0), reverse=True)

@app.get("/api/shorts")
def shorts(all: int = 0):
    """Published (approved) Shorts, newest first: the landing-page gallery. ?all=1 also lists pending/rejected ones for review."""
    r = []
    for d in _shares():
        if not all and _status(d) != "approved":
            continue
        p = d.get("proof", {}); v = p.get("visuals", {})
        r.append({"id": d["id"], "title": d.get("title"), "topic": d.get("topic"), "video": d["video"], "duration": d.get("duration"),
                  "poster": (d.get("scenes") or [{}])[0].get("labeled") or (d.get("scenes") or [{}])[0].get("image"),
                  "claims": p.get("claims_final"), "all_verified": p.get("all_verified"), "labels_kept": v.get("labels_kept"),
                  "status": _status(d)})
    return r

@app.get("/api/shorts/{sid}")
def short(sid: str, preview: int = 0):
    """The public share page. Pending/rejected Shorts are only visible as a reviewer preview (?preview=1)."""
    for d in _shares():
        if d["id"] == sid:
            if _status(d) != "approved" and not preview:
                raise HTTPException(403, f"This Short is {_status(d)}: not published until a human approves it")
            return d | {"status": _status(d)}
    raise HTTPException(404, "No such Short")


class Review(BaseModel):
    decision: str = Field(pattern="^(approve|reject)$")
    note: str = Field("", max_length=500)
    reviewer: str = Field("", max_length=80)


@app.post("/api/shorts/{sid}/review")
def review(sid: str, r: Review):
    """Human sign-off. Approving re-checks the sha256 fingerprints recorded when the media passed its checks."""
    sp = _share_path(sid)
    if not sp:
        raise HTTPException(404, "No such Short")
    d = json.loads(sp.read_text())
    p = d.get("proof") or {}
    if r.decision == "approve":
        fc = p.get("final_check")
        if fc is not None and not fc.get("ok"):
            raise HTTPException(409, "Cannot approve: the final check did not pass")
        swapped = V.changed(sp.parent, (p.get("fingerprints") or {}).get("media") or {}) + \
            V.changed(sp.parent, (p.get("fingerprints") or {}).get("frames") or {})
        if swapped:
            raise HTTPException(409, f"Cannot approve: files changed since they were verified: {swapped[:6]}")
    d["status"] = "approved" if r.decision == "approve" else "rejected"
    d["review"] = {"decision": r.decision, "note": r.note, "reviewer": r.reviewer, "at": time.time()}
    sp.write_text(json.dumps(d))
    return {"id": sid, "status": d["status"], "review": d["review"]}


@app.get("/api/shorts/{sid}/export")
def export(sid: str):
    """Download the full pack (zip). Blocked until approved."""
    sp = _share_path(sid)
    if not sp:
        raise HTTPException(404, "No such Short")
    d = json.loads(sp.read_text())
    if _status(d) != "approved":
        raise HTTPException(403, f"Export blocked: this Short is {_status(d)}; approve it first")
    z = C.OUTPUT_DIR / f"{sp.parent.name}.zip"
    if not z.exists():
        raise HTTPException(404, "No pack for this Short")
    return FileResponse(z, filename=z.name, media_type="application/zip")
