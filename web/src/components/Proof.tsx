"use client";
import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { BadgeCheck, ChevronDown, ExternalLink, Quote, ScanEye, ShieldCheck, Timer, Wrench } from "lucide-react";
import { Ev, fmtSec, proofSummary, url } from "@/lib/api";
import { Label, Pill } from "./ui";

export function ProofStats({ final }: { final: any }) {
  const s = proofSummary(final);
  const tiles = [
    { k: `${s.claims}/${s.claims}`, v: "claims sourced", sub: s.verified ? "every line traced to a quote" : "check details", I: ShieldCheck, tone: "text-emerald-300" },
    { k: s.labelsTotal ? `${s.labelsKept}/${s.labelsTotal}` : "—", v: "labels verified", sub: s.labelsDropped ? `${s.labelsDropped} omitted, SAM never confirmed` : "SAM 3.1 found each one", I: ScanEye, tone: "text-sky-300" },
    { k: String(s.corrections), v: "self-corrections", sub: `${s.claimFixes} script · ${s.frameFixes} frame`, I: Wrench, tone: "text-amber-300" },
    { k: fmtSec(s.seconds), v: "duration", sub: s.seconds >= 45 ? "meets the 45 s minimum" : "evidence ran short, not padded", I: Timer, tone: "text-violet-300" },
  ];
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      {tiles.map(t => (
        <div key={t.v} className="rounded-2xl border border-white/10 bg-white/[.03] p-4">
          <t.I size={16} className={t.tone} />
          <p className="font-display mt-3 text-2xl font-semibold tabular-nums">{t.k}</p>
          <p className="text-sm text-white/70">{t.v}</p>
          <p className="mt-0.5 text-xs text-white/40">{t.sub}</p>
        </div>
      ))}
    </div>
  );
}

function Fold({ title, count, open: o = false, children }: { title: string; count?: string | number; open?: boolean; children: React.ReactNode }) {
  const [open, set] = useState(o);
  return (
    <div className="rounded-2xl border border-white/10 bg-white/[.02]">
      <button onClick={() => set(!open)} className="flex w-full items-center justify-between gap-3 px-4 py-3.5 text-left" aria-expanded={open}>
        <span className="flex items-center gap-2 text-[15px] font-medium">{title}{count != null && <span className="rounded-md bg-white/5 px-1.5 py-0.5 text-[11px] text-white/50">{count}</span>}</span>
        <ChevronDown size={16} className={`text-white/40 transition ${open ? "rotate-180" : ""}`} />
      </button>
      <AnimatePresence initial={false}>
        {open && <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden"><div className="px-4 pb-4">{children}</div></motion.div>}
      </AnimatePresence>
    </div>
  );
}

function Line({ l, src }: { l: any; src?: any }) {
  const [open, set] = useState(false);
  const rewritten = l.status === "rewritten";
  const before = (l.history ?? []).find((h: any) => h.rewrite_from)?.rewrite_from;
  return (
    <li className="rounded-xl border border-white/5 bg-black/20 p-3">
      <p className="text-[15px] leading-snug text-white/90">{l.text}</p>
      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        {l.kind === "framing" ? <Pill tone="slate">framing · no facts</Pill> : (
          <>
            <button onClick={() => set(!open)} className="inline-flex items-center gap-1" aria-expanded={open}><Pill tone="emerald"><BadgeCheck size={11} />{l.source_id}{src ? ` · ${src.title}` : ""}</Pill></button>
            {rewritten && <Pill tone="amber">rewritten after critic</Pill>}
            {l.quote_verified && <Pill tone="slate">quote found in source</Pill>}
          </>
        )}
      </div>
      <AnimatePresence initial={false}>
        {open && l.kind !== "framing" && (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
            <blockquote className="mt-2.5 flex gap-2 border-l-2 border-emerald-300/40 pl-3 text-sm italic text-white/60"><Quote size={13} className="mt-1 shrink-0 text-emerald-300/60" />“{l.supporting_quote ?? l.quote}”</blockquote>
            {before && <p className="mt-2 text-xs text-white/40"><span className="uppercase tracking-wider text-amber-300/70">Critic rejected </span><s>{before}</s></p>}
            {src?.url && <a href={src.url} target="_blank" rel="noreferrer" className="mt-2 inline-flex items-center gap-1 text-xs text-sky-300 hover:underline">Open source <ExternalLink size={11} /></a>}
          </motion.div>
        )}
      </AnimatePresence>
    </li>
  );
}

export function ProofPanel({ final, compact = false }: { final: any; compact?: boolean }) {
  const p = final?.proof ?? {}, v = p.visuals ?? {};
  const srcs: Record<string, any> = Object.fromEntries((p.sources ?? []).map((s: any) => [s.id, s]));
  const scenes: any[] = final?.scenes ?? [];
  return (
    <section aria-label="Proof panel" className="space-y-4">
      <div className="flex items-end justify-between gap-3">
        <div><Label>Proof panel</Label><h2 className="font-display mt-1 text-2xl font-semibold">Every claim, traced.</h2></div>
        {p.all_verified && <Pill tone="emerald"><ShieldCheck size={12} />all claims verified</Pill>}
      </div>
      <ProofStats final={final} />
      <Fold title="Script with citations" count={`${p.claims_final ?? 0} claims`}>
        <p className="mb-3 text-xs text-white/40">Tap a source tag to see the exact quote the critic matched.</p>
        <ol className="space-y-4">
          {scenes.map((s, i) => (
            <li key={i} className="flex gap-3">
              <span className="mt-1 w-6 shrink-0 font-mono text-xs text-white/30">{String(i + 1).padStart(2, "0")}</span>
              <ul className="min-w-0 flex-1 space-y-2">{(s.lines ?? []).map((l: any, k: number) => <Line key={k} l={l} src={srcs[l.source_id]} />)}</ul>
            </li>
          ))}
        </ol>
      </Fold>
      <Fold title="Sources" count={(p.sources ?? []).length}>
        <ul className="space-y-2">
          {(p.sources ?? []).map((s: any) => (
            <li key={s.id}><a href={s.url} target="_blank" rel="noreferrer" className="flex items-center justify-between gap-3 rounded-xl border border-white/5 bg-black/20 px-3 py-2.5 text-sm hover:border-white/20">
              <span className="min-w-0"><span className="mr-2 font-mono text-xs text-emerald-300">{s.id}</span><span className="truncate">{s.title}</span><span className="ml-2 text-xs text-white/40">{s.kind === "pubmed" ? "PubMed" : "Wikipedia"}</span></span>
              <ExternalLink size={13} className="shrink-0 text-white/40" /></a></li>
          ))}
        </ul>
      </Fold>
      {(p.corrections ?? []).length > 0 && (
        <Fold title="What the critic caught" count={p.corrections.length}>
          <ul className="space-y-3">
            {p.corrections.map((c: any, i: number) => (
              <li key={i} className="rounded-xl border border-amber-300/15 bg-amber-400/[.04] p-3 text-sm">
                <p className="text-white/50"><span className="mr-1.5 text-[10px] uppercase tracking-wider text-rose-300">rejected</span><s>{c.before}</s></p>
                {c.after && <p className="mt-1 text-white/90"><span className="mr-1.5 text-[10px] uppercase tracking-wider text-emerald-300">rewrote</span>{c.after}{c.source_id && <span className="ml-1.5 font-mono text-xs text-emerald-300/80">{c.source_id}</span>}</p>}
                {!c.after && <p className="mt-1 text-white/60"><span className="mr-1.5 text-[10px] uppercase tracking-wider text-white/40">dropped</span>sources could not support it</p>}
                <p className="mt-1.5 text-xs text-white/40">{c.reason}</p>
              </li>
            ))}
          </ul>
        </Fold>
      )}
      <Fold title="Visual verification (SAM 3.1 gate)" count={`${v.frames ?? 0} frames`}>
        <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
          {[["Passed first try", v.first_try_pass_rate != null ? `${Math.round(v.first_try_pass_rate * 100)}%` : "—"], ["Structures confirmed", v.structure_pass_rate != null ? `${Math.round(v.structure_pass_rate * 100)}%` : "—"],
            ["Regenerations", v.regenerated ?? 0], ["Labels omitted", v.labels_dropped ?? 0]].map(([k, val]) => (
            <div key={String(k)} className="rounded-xl bg-white/[.03] p-3"><dt className="text-xs text-white/40">{k}</dt><dd className="font-display mt-1 text-xl tabular-nums">{val}</dd></div>))}
        </dl>
        <p className="mt-3 text-xs leading-relaxed text-white/40">A label only appears if SAM finds the whole structure in the frame. Otherwise the frame is regenerated, and after {2} retries the label is left off. We never show a label we could not verify.</p>
        {scenes.some(s => s.image) && (
          <div className="mt-4 grid grid-cols-4 gap-2 sm:grid-cols-6">{scenes.map((s, i) => (
            <figure key={i} className="relative aspect-[9/16] overflow-hidden rounded-lg border border-white/10">
              <img src={url(s.labeled ?? s.image)} alt={`Frame ${i + 1}`} className="h-full w-full object-cover" loading="lazy" />
              {s.gate && <span className={`absolute bottom-1 left-1 rounded px-1 text-[9px] font-semibold ${s.gate.dropped?.length ? "bg-amber-400 text-black" : "bg-emerald-500/90 text-black"}`}>{s.gate.dropped?.length ? "label omitted" : `${s.gate.attempts} ${s.gate.attempts > 1 ? "tries" : "try"}`}</span>}
            </figure>))}</div>
        )}
      </Fold>
    </section>
  );
}
