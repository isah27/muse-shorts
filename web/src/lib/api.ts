export const API = process.env.NEXT_PUBLIC_API ?? "http://localhost:8000";
export const url = (u?: string | null) => (u ? (u.startsWith("http") ? u : API + u) : "");

export type Ev = { step: string; status: string; message: string; t: number; [k: string]: any };
export type StepState = { id: string; title: string; tool: string; status: string; message: string; logs: string[]; progress?: number; retries: number };
export type Frame = { image?: string; labeled?: string; narration?: string; qa: Ev[] };
export type Decision = { turn: number; tool: string; reason: string; by?: string; observation?: string; refused?: boolean; pending: boolean; blocked?: { stage: string; allowed: string[] } };
export type TraceRec = { attempt: number; turn: number; result: "pass" | "fail"; feedback: string[]; [k: string]: any };
export type Trace = Record<string, TraceRec[]>;
export type ClaimItem = { type: "pass" | "reject" | "rewrite" | "drop" | "length" | "more_sources" | "length_short" | "length_cut"; ev: Ev };

export const LANGS = [
  { id: "en", label: "English", ready: true },
  { id: "pcm", label: "Pidgin", ready: true },
  { id: "yo", label: "Yorùbá", ready: true },
  { id: "ha", label: "Hausa", ready: true },
  { id: "ig", label: "Igbo", ready: true },
] as const;

export const TOPICS = ["How the heart pumps blood", "How neurons fire", "Why we yawn", "What the cerebellum does", "How memory forms", "Why dopamine feels good"];

/** Fold the SSE event stream into UI state: timeline steps, storyboard frames, claim-critic cards, final result. */
export function derive(events: Ev[]) {
  const startEv = events.find(e => e.step === "job" && e.status === "start");
  const steps: StepState[] = (startEv?.steps ?? []).map((s: any) => ({ ...s, status: "waiting", message: "", logs: [], retries: 0 }));
  const frames: Record<number, Frame> = {};
  const claims: ClaimItem[] = [];
  const frame = (i: number) => frames[i] ?? (frames[i] = { qa: [] });
  let final: any = null, error: string | null = null;
  const decisions: Decision[] = [];
  let checklist: any[] = startEv?.checklist ?? [], agentNote = "";
  let trace: Trace = {}, domain: any = null, paused = false;
  for (const e of events) {
    const s = steps.find(x => x.id === e.step);
    if (e.step === "agent") {
      if (e.status === "decision") { paused = false; decisions.push({ turn: e.turn, tool: e.tool, reason: e.reason, pending: true }); }
      else if (e.status === "blocked") {
        const d = [...decisions].reverse().find(x => x.tool === e.tool && x.pending);
        const b = { stage: e.stage, allowed: e.allowed ?? [] };
        if (d) d.blocked = b; else decisions.push({ turn: e.turn, tool: e.tool, reason: "autopilot", by: "autopilot", pending: true, blocked: b });
      }
      else if (e.status === "verify") { if (e.trace) trace = e.trace; continue; }
      else if (e.status === "domain") { domain = e.domain; continue; }
      else if (e.status === "paused") { paused = true; continue; }
      else if (e.status === "observation") {
        const d = [...decisions].reverse().find(x => x.turn === e.turn && x.tool === e.tool);
        if (d && (d.pending || d.turn === e.turn)) Object.assign(d, { observation: e.message, refused: e.refused, pending: false });
        else decisions.push({ turn: e.turn, tool: e.tool, reason: "fixed pipeline (fallback)", by: e.by, observation: e.message, refused: e.refused, pending: false });
        if (e.checklist) checklist = e.checklist;
      } else agentNote = e.message;
      if (s) { s.message = e.message; s.status = "running"; s.progress = undefined; }
      continue;
    }
    if (s) {
      if (e.step === "claims" && e.kind) {
        const t = e.kind as ClaimItem["type"];
        claims.push({ type: t, ev: e });
        if (t !== "pass") s.retries++;
        if (s.status === "waiting") s.status = "running";
        if (t === "pass") s.message = e.message;
      } else if (e.step === "frame_qa" && e.status === "retry" && e.kind && e.scene != null) {
        s.retries += e.kind === "regenerate" || e.kind === "drop_label" ? 1 : 0;
        frame(e.scene).qa.push(e);
        if (s.status === "waiting") s.status = "running";
      } else if (e.status === "retry") { s.retries++; s.logs.push("↻ " + e.message); if (s.status === "waiting") s.status = "running"; }
      else if (e.status === "progress") { s.progress = e.progress; s.message = e.message; s.status = "running"; }
      else if (e.status !== "waiting") { s.status = e.status; if (e.message) s.message = e.message; if (e.status === "done") s.progress = 1; }
    }
    if (e.scenes && e.step !== "job") e.scenes.forEach((sc: any, i: number) => { frame(i).narration = sc.narration; });
    if (e.image != null && e.scene != null && !e.kind) frame(e.scene).image = e.image;
    if (e.labeled != null && e.scene != null) frame(e.scene).labeled = e.labeled;
    if (e.step === "job" && e.status === "done") { final = e; const a = steps.find(x => x.id === "agent"); if (a) a.status = "done"; }
    if (e.step === "job" && e.status === "rejected") { error = e.message + (e.suggestion ? " " + e.suggestion : ""); steps.forEach(x => x.status === "running" && (x.status = "error")); }
    if (e.status === "error") { error = e.message; steps.forEach(x => x.status === "running" && (x.status = "error")); }
  }
  if (final?.proof?.verification) trace = final.proof.verification;
  return { steps, frames, claims, final, startEv, error, decisions, checklist, agentNote, trace, domain, paused };
}

export function proofSummary(final: any) {
  const p = final?.proof ?? {}, v = p.visuals ?? {}, len = p.length ?? {};
  const kept = v.labels_kept ?? 0, dropped = v.labels_dropped ?? 0;
  return {
    claims: p.claims_final ?? 0, verified: !!p.all_verified, sources: (p.sources ?? []).length,
    labelsKept: kept, labelsDropped: dropped, labelsTotal: kept + dropped,
    corrections: (p.rewritten ?? 0) + (p.dropped ?? 0) + (v.regenerated ?? 0),
    claimFixes: (p.rewritten ?? 0) + (p.dropped ?? 0), frameFixes: v.regenerated ?? 0,
    seconds: final?.duration ?? len.actual_seconds ?? len.estimated_seconds ?? 0, firstTry: p.supported_first_try ?? 0,
  };
}

export const fmtSec = (s?: number) => (s ? `${Math.round(s)} s` : "—");
