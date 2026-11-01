"use client";
import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  ArrowRight, Brain, Check, ChevronDown, FileText, Film, Image as ImageIcon, Lightbulb, Loader2, Mic, ScanEye,
  ShieldCheck, Sparkles, Subtitles, Tag, Timer, Wand2, Search, Plus, Eraser,
} from "lucide-react";
import { ClaimItem, Decision, Frame, StepState, Trace, url } from "@/lib/api";
import { Label, Pill } from "./ui";

const ICONS: Record<string, any> = { agent: Brain, scope: ShieldCheck, evidence: Search, claims: ShieldCheck, plan: Lightbulb, script: FileText, review: ShieldCheck, visuals: ImageIcon, frame_qa: ScanEye, segment: Tag, voice: Mic, captions: Subtitles, render: Film };

function toolName(s: StepState, p?: any) {
  if (!p) return s.tool;
  const m: Record<string, string> = { agent: p.orchestrator ?? "Muse Spark Open", scope: p.critic, evidence: "Wikipedia + PubMed", claims: p.critic, plan: p.writer, script: p.writer, review: p.critic, visuals: p.image, frame_qa: p.segment, segment: p.segment, voice: p.tts, captions: p.asr, render: "ffmpeg" };
  return (m[s.id] ?? s.tool).replace(/\s*\(.*\)/, "");
}

/* ---------- claim critic: gate cards ---------- */
function ClaimGate({ items }: { items: ClaimItem[] }) {
  const [showPass, setShowPass] = useState(false);
  const pass = items.filter(i => i.type === "pass").length;
  const rest = items.filter(i => i.type !== "pass");
  if (!items.length) return null;
  const rej = items.filter(i => i.type === "reject").length, rew = items.filter(i => i.type === "rewrite").length, drop = items.filter(i => i.type === "drop").length;
  return (
    <div className="mt-3 space-y-2">
      <div className="flex flex-wrap gap-1.5">
        <Pill tone="emerald"><Check size={11} />{pass} verified</Pill>
        {rej > 0 && <Pill tone="rose">{rej} rejected</Pill>}
        {rew > 0 && <Pill tone="amber">{rew} rewritten</Pill>}
        {drop > 0 && <Pill tone="slate">{drop} dropped</Pill>}
      </div>
      <AnimatePresence initial={false}>
        {rest.map((it, k) => <GateCard key={k} it={it} />)}
      </AnimatePresence>
      {pass > 0 && (
        <button onClick={() => setShowPass(!showPass)} className="flex items-center gap-1 text-xs text-white/40 hover:text-white/70">
          <ChevronDown size={12} className={showPass ? "rotate-180" : ""} />{showPass ? "Hide" : "Show"} {pass} passed lines
        </button>
      )}
      {showPass && items.filter(i => i.type === "pass").map((it, k) => (
        <p key={k} className="rounded-lg border border-emerald-300/10 bg-emerald-400/[.04] px-2.5 py-1.5 text-xs text-emerald-100/80"><b className="mr-1 text-emerald-300">✓ {it.ev.source_id ?? "framing"}</b>{it.ev.line}</p>
      ))}
    </div>
  );
}

function GateCard({ it }: { it: ClaimItem }) {
  const e = it.ev;
  const base = "rounded-xl border px-3 py-2 text-[13px] leading-snug";
  const anim = { initial: { opacity: 0, y: 6 }, animate: { opacity: 1, y: 0 } };
  if (it.type === "reject") return (
    <motion.div {...anim} className={`${base} border-rose-300/25 bg-rose-500/[.07] text-rose-100/90`}>
      <p className="text-[10px] font-semibold uppercase tracking-[.18em] text-rose-300">Critic rejected · scene {e.scene + 1} · {e.verdict}</p>
      <p className="mt-1 text-white/85">“{e.line}”</p><p className="mt-1 text-xs text-rose-100/60">{e.reason}</p>
    </motion.div>);
  if (it.type === "rewrite") return (
    <motion.div {...anim} className={`${base} border-amber-300/25 bg-amber-400/[.06]`}>
      <p className="text-[10px] font-semibold uppercase tracking-[.18em] text-amber-300">Self-correction · rewritten from {e.source_id}</p>
      <p className="mt-1 text-white/45 line-through decoration-rose-300/50">{e.before}</p>
      <p className="mt-1 flex gap-1.5 text-white/90"><ArrowRight size={13} className="mt-0.5 shrink-0 text-amber-300" />{e.after}</p>
    </motion.div>);
  if (it.type === "drop") return (
    <motion.div {...anim} className={`${base} border-white/10 bg-white/[.03] text-white/60`}>
      <p className="flex items-center gap-1 text-[10px] font-semibold uppercase tracking-[.18em] text-white/50"><Eraser size={11} />Dropped · sources can’t support it</p>
      <p className="mt-1 line-through decoration-white/20">“{e.line}”</p>
    </motion.div>);
  if (it.type === "length") return (
    <motion.div {...anim} className={`${base} border-violet-300/25 bg-violet-400/[.07]`}>
      <p className="flex items-center gap-1 text-[10px] font-semibold uppercase tracking-[.18em] text-violet-300"><Timer size={11} />Length check · round {e.round}</p>
      <p className="mt-1 text-white/80">Script is about {Math.round(e.estimated_seconds)} s after fact-checking, under the 45 s minimum. Writing replacement lines from the sources.</p>
    </motion.div>);
  if (it.type === "more_sources") return (
    <motion.div {...anim} className={`${base} border-sky-300/25 bg-sky-400/[.06]`}>
      <p className="flex items-center gap-1 text-[10px] font-semibold uppercase tracking-[.18em] text-sky-300"><Plus size={11} />More evidence fetched</p>
      <p className="mt-1 text-white/80">{(e.sources ?? []).map((s: any) => `${s.id} ${s.title}`).join(" · ")}</p>
    </motion.div>);
  if (it.type === "length_short") return (
    <motion.div {...anim} className={`${base} border-amber-300/25 bg-amber-400/[.06] text-amber-100/90`}>Evidence ran out before 45 s. Not padding, so this one stays short.</motion.div>);
  if (it.type === "length_cut") return <motion.div {...anim} className={`${base} border-white/10 bg-white/[.03] text-white/60`}>{e.message}</motion.div>;
  return null;
}

/* ---------- SAM gate: per-frame retries with thumbnails ---------- */
function FrameGate({ frames }: { frames: Record<number, Frame> }) {
  const rows = Object.entries(frames).filter(([, f]) => f.qa.length).sort((a, b) => +a[0] - +b[0]);
  if (!rows.length) return null;
  return (
    <div className="mt-3 space-y-2">
      {rows.map(([i, f]) => {
        const rejects = f.qa.filter(q => q.kind === "reject");
        const dropped = f.qa.filter(q => q.kind === "drop_label");
        const last = rejects[rejects.length - 1];
        return (
          <motion.div key={i} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="flex gap-3 rounded-xl border border-white/10 bg-white/[.03] p-2.5">
            <div className="flex shrink-0 items-center gap-1.5">
              {rejects.map((r, k) => r.image && (
                <div key={k} className="relative">
                  <img src={url(r.image)} alt={`Rejected attempt ${k + 1}`} className="h-16 w-9 rounded-md object-cover opacity-60 ring-1 ring-rose-400/60" />
                  <span className="absolute -right-1 -top-1 grid h-4 w-4 place-items-center rounded-full bg-rose-500 text-[9px] font-bold">✗</span>
                </div>))}
              {(f.labeled || f.image) && <>
                <ArrowRight size={12} className="text-white/30" />
                <div className="relative"><img src={url(f.labeled ?? f.image)} alt="Final frame" className={`h-16 w-9 rounded-md object-cover ring-1 ${dropped.length ? "ring-amber-400/70" : "ring-emerald-400/70"}`} />
                  <span className={`absolute -right-1 -top-1 grid h-4 w-4 place-items-center rounded-full text-[9px] font-bold text-black ${dropped.length ? "bg-amber-400" : "bg-emerald-400"}`}>{dropped.length ? "⌀" : "✓"}</span></div>
              </>}
            </div>
            <div className="min-w-0 text-xs leading-snug">
              <p className="font-semibold text-white/80">Frame {+i + 1} · {rejects.length} rejected{dropped.length ? " · label omitted" : ""}</p>
              {last && <p className="mt-0.5 text-white/50">{last.reason === "exposure" ? "Flat or badly exposed." : (last.message?.replace(/^Frame \d+ try \d+: /, "").replace(/ — regenerating$/, "") ?? "")}</p>}
              {dropped.map((d, k) => <p key={k} className="mt-0.5 text-amber-200/80">Dropped the “{d.label}” label: SAM never confirmed the whole structure.</p>)}
            </div>
          </motion.div>
        );
      })}
    </div>
  );
}

export function Timeline({ steps, providers, frames, claims, compact }: { steps: StepState[]; providers?: any; frames: Record<number, Frame>; claims: ClaimItem[]; compact?: boolean }) {
  if (!steps.length) return <div className="glass h-[520px] rounded-3xl shimmer" />;
  return (
    <div className="glass rounded-3xl p-4 sm:p-6">
      <div className="mb-4 flex items-center justify-between"><Label>Agent timeline</Label><p className="text-xs tabular-nums text-white/40">{steps.filter(s => s.status === "done").length}/{steps.length} steps</p></div>
      <ol className="relative space-y-1" aria-live="polite">
        {steps.map((s, i) => {
          const I = ICONS[s.id] ?? Sparkles, active = s.status === "running";
          const showGate = s.id === "claims" || s.id === "frame_qa";
          return (
            <motion.li key={s.id} layout className={`relative flex gap-3 rounded-2xl p-2.5 transition sm:gap-4 sm:p-3 ${active ? "bg-white/[.05]" : ""}`}>
              {i < steps.length - 1 && <span className={`absolute left-[25px] top-12 h-[calc(100%-28px)] w-px sm:left-[29px] ${s.status === "done" ? "bg-sky-300/40" : "bg-white/10"}`} />}
              <span className={`relative grid h-9 w-9 shrink-0 place-items-center rounded-xl border transition ${s.status === "done" ? "border-sky-300/40 bg-sky-400/15 text-sky-200" : active ? "border-violet-300/50 bg-violet-400/15 text-violet-200" : s.status === "error" ? "border-rose-300/40 bg-rose-500/15 text-rose-200" : "border-white/10 bg-white/[.03] text-white/40"}`}>
                {s.status === "done" ? <Check size={16} /> : active ? <Loader2 size={16} className="animate-spin" /> : <I size={16} />}
                {active && <span className="absolute inset-0 animate-ping rounded-xl border border-violet-300/40" />}
              </span>
              <div className="min-w-0 flex-1 pt-0.5">
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <span className={`text-[15px] font-medium ${s.status === "waiting" ? "text-white/40" : ""}`}>{s.title}</span>
                  <span className="rounded-md bg-white/5 px-1.5 py-0.5 text-[10px] uppercase tracking-wider text-white/40">{toolName(s, providers)}</span>
                  {s.retries > 0 && <span className="text-[11px] text-amber-300/90">↻ {s.retries}</span>}
                </div>
                {s.message && <p className="mt-0.5 line-clamp-2 text-sm text-white/50">{s.message}</p>}
                {s.id === "claims" && <ClaimGate items={claims} />}
                {s.id === "frame_qa" && <FrameGate frames={frames} />}
                {!showGate && s.logs.map((l, k) => <p key={k} className="mt-1.5 rounded-lg border border-amber-300/20 bg-amber-400/[.06] px-2.5 py-1.5 text-xs text-amber-100/90">{l}</p>)}
                {active && s.progress != null && s.progress < 1 && <div className="mt-2 h-1 overflow-hidden rounded-full bg-white/10"><motion.div className="h-full bg-gradient-to-r from-sky-400 to-violet-400" animate={{ width: `${s.progress * 100}%` }} /></div>}
              </div>
            </motion.li>
          );
        })}
      </ol>
    </div>
  );
}

/* ---------- storyboard: frames appear as Muse Image draws them, then get SAM-labeled ---------- */
export function Storyboard({ frames, steps }: { frames: Record<number, Frame>; steps: StepState[] }) {
  const list = Object.entries(frames).sort((a, b) => +a[0] - +b[0]);
  const current = steps.find(s => s.status === "running");
  return (
    <div className="glass rounded-3xl p-4 sm:p-6 lg:sticky lg:top-4">
      <div className="mb-4 flex items-center justify-between"><Label>Storyboard</Label>
        {current && <p className="flex items-center gap-2 text-xs text-violet-200"><span className="h-1.5 w-1.5 animate-pulse rounded-full bg-violet-300" />{current.title}</p>}</div>
      {!list.length ? <div className="grid grid-cols-4 gap-2.5">{Array.from({ length: 8 }).map((_, i) => <div key={i} className="aspect-[9/16] rounded-xl shimmer" />)}</div> : (
        <div className="grid grid-cols-4 gap-2.5">
          {list.map(([i, f]) => {
            const regen = f.qa.filter(q => q.kind === "regenerate").length, dropped = f.qa.some(q => q.kind === "drop_label");
            return (
              <motion.figure key={i} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="relative aspect-[9/16] overflow-hidden rounded-xl border border-white/10 bg-white/[.03]">
                {f.labeled || f.image ? <motion.img key={f.labeled ?? f.image} initial={{ opacity: 0, scale: 1.04 }} animate={{ opacity: 1, scale: 1 }} transition={{ duration: .5 }} src={url(f.labeled ?? f.image)} alt={`Frame ${+i + 1}`} className="h-full w-full object-cover" /> : <div className="h-full w-full shimmer" />}
                <span className="absolute left-1.5 top-1.5 rounded-md bg-black/60 px-1.5 py-0.5 text-[10px] font-semibold">{+i + 1}</span>
                {regen > 0 && <span className="absolute right-1.5 top-1.5 rounded-md bg-sky-500/85 px-1.5 py-0.5 text-[10px] font-semibold">↻{regen}</span>}
                {dropped && <span className="absolute inset-x-1.5 bottom-1.5 rounded-md bg-amber-400 px-1 py-0.5 text-center text-[9px] font-semibold text-black">label omitted</span>}
              </motion.figure>
            );
          })}
        </div>
      )}
      <p className="mt-4 text-xs leading-relaxed text-white/40">Muse Image draws each frame. SAM 3.1 then has to find every structure we name; if it can’t, the frame is redrawn, and failing that, the label is left off.</p>
    </div>
  );
}

/* ---------- agent decisions: one row per orchestrator turn (plan / act / observe) ---------- */
export function AgentDecisions({ decisions, checklist, note, maxTurns }: { decisions: Decision[]; checklist: any[]; note?: string; maxTurns?: number }) {
  if (!decisions.length && !checklist.length) return null;
  const refused = decisions.filter(d => d.refused).length;
  return (
    <div className="glass rounded-3xl p-4 sm:p-6">
      <div className="mb-3 flex items-center justify-between"><Label>Agent decisions</Label>
        <p className="text-xs tabular-nums text-white/40">{decisions.length}{maxTurns ? `/${maxTurns}` : ""} turns{refused ? ` · ${refused} refused` : ""}</p></div>
      {checklist.length > 0 && <div className="mb-3 flex flex-wrap gap-1.5">{checklist.map((c: any) => (
        <Pill key={c.id} tone={c.status === "proven" ? "emerald" : "slate"}>{c.status === "proven" ? <Check size={11} /> : "○"} {c.text}</Pill>))}</div>}
      {note && <p className="mb-2 rounded-lg border border-amber-300/20 bg-amber-400/[.06] px-2.5 py-1.5 text-xs text-amber-100/90">{note}</p>}
      <ol className="space-y-1.5">
        {decisions.map((d, k) => (
          <motion.li key={k} initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }}
            className={`rounded-xl border px-3 py-2 text-xs leading-snug ${d.refused ? "border-rose-300/25 bg-rose-500/[.06]" : "border-white/10 bg-white/[.03]"}`}>
            <div className="flex items-center gap-2">
              <span className="tabular-nums text-white/35">#{d.turn}</span>
              <code className={`rounded bg-white/5 px-1.5 py-0.5 text-[11px] ${d.refused ? "text-rose-200" : "text-sky-200"}`}>{d.tool}</code>
              {d.by === "autopilot" && <span className="text-[10px] uppercase tracking-wider text-amber-300/80">autopilot</span>}
              {d.blocked && <span title={`Allowed in this stage: ${d.blocked.allowed.join(", ")}`} className="rounded bg-rose-500/15 px-1.5 py-0.5 text-[10px] uppercase tracking-wider text-rose-200">blocked · stage {d.blocked.stage}</span>}
              {d.pending && <Loader2 size={12} className="animate-spin text-violet-300" />}
            </div>
            {d.reason && <p className="mt-1 text-white/70">{d.reason}</p>}
            {d.observation && <p className={`mt-0.5 line-clamp-2 font-mono text-[11px] ${d.refused ? "text-rose-100/70" : "text-white/40"}`}>{d.observation}</p>}
          </motion.li>
        ))}
      </ol>
    </div>
  );
}

const CHECK_TITLES: Record<string, string> = {
  plan_check: "Plan → evidence", script_checks: "Script: schema · sources · length", claim_judge: "Claim judge + domain policy",
  labels: "Frame labels (SAM)", render: "Captions = voice", final_check: "Final check",
};

/** Every verification check, attempt by attempt: fail -> feedback -> retry -> pass. */
export function VerificationTrace({ trace, domain }: { trace: Trace; domain?: any }) {
  const keys = Object.keys(CHECK_TITLES).filter(k => trace?.[k]?.length).concat(Object.keys(trace ?? {}).filter(k => !(k in CHECK_TITLES)));
  if (!keys.length && !domain) return null;
  const retried = keys.filter(k => trace[k].some(r => r.result === "fail")).length;
  return (
    <div className="glass rounded-3xl p-4 sm:p-6">
      <div className="mb-3 flex items-center justify-between"><Label>Verification trace</Label>
        <p className="text-xs tabular-nums text-white/40">{keys.length} checks{retried ? ` · ${retried} needed a retry` : ""}</p></div>
      {domain && <p className="mb-3 text-xs text-white/60"><Pill tone={domain.strict ? "amber" : "slate"}>{domain.domain}</Pill>{" "}
        {domain.strict ? "strict: 100% of claims must be verified" : `lenient: ≥ ${Math.round((domain.threshold ?? 0.9) * 100)}% verified, unverified claims cut`}
        <span className="text-white/35"> · {domain.layer}: {domain.reason}</span></p>}
      <ol className="space-y-2">
        {keys.map(k => (
          <li key={k} className="rounded-xl border border-white/10 bg-white/[.03] px-3 py-2 text-xs">
            <p className="mb-1 font-medium text-white/80">{CHECK_TITLES[k] ?? k}</p>
            <div className="flex flex-wrap items-start gap-1.5">
              {trace[k].map((r, i) => (
                <div key={i} className="flex items-start gap-1.5">
                  {i > 0 && <span className="pt-0.5 text-white/30">→ retry →</span>}
                  <div className={`max-w-[280px] rounded-lg px-2 py-1 ${r.result === "pass" ? "bg-emerald-500/10 text-emerald-200" : "bg-rose-500/10 text-rose-200"}`}>
                    <span className="font-semibold uppercase">{r.result}</span> <span className="text-white/35">#{r.attempt} · turn {r.turn}</span>
                    {r.feedback?.length > 0 && <p className="mt-0.5 font-mono text-[11px] text-rose-100/70">feedback: {r.feedback.slice(0, 2).join("; ")}</p>}
                  </div>
                </div>
              ))}
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}
