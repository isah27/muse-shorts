"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { ArrowRight, BadgeCheck, Globe2, Play, ScanEye, ShieldCheck, Wand2 } from "lucide-react";
import { API, LANGS, TOPICS, url } from "@/lib/api";
import { Label, Pill } from "./ui";

export function Create({ topic, setTopic, start, voice, setVoice, labels, setLabels, lang, setLang, cfg }: any) {
  const disabled = topic.trim().length < 3 || cfg?.offline;
  const chosen = LANGS.find(l => l.id === lang)!;
  return (
    <motion.section initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }} transition={{ duration: .5 }} className="mx-auto max-w-3xl pt-8 text-center sm:pt-14">
      <div className="glass mx-auto mb-6 inline-flex items-center gap-2 rounded-full px-3.5 py-1.5 text-xs text-white/70"><ShieldCheck size={13} className="text-emerald-300" />Meta Global AI Developer Hackathon · open-weights agent</div>
      <h1 className="font-display text-[2.6rem] font-semibold leading-[1.02] tracking-tight sm:text-7xl">Shorts you<br /><span className="text-gradient">can trust.</span></h1>
      <p className="mx-auto mt-5 max-w-xl text-base leading-relaxed text-white/60 sm:text-lg">Type a science topic. An agent finds sources, writes only what they support, draws the frames, and checks its own work before it labels a thing. Watch it catch its own mistakes.</p>

      <form onSubmit={(e) => { e.preventDefault(); if (!disabled) start(); }} className="mx-auto mt-8 max-w-2xl text-left">
        <div className="glass flex items-center gap-2 rounded-2xl p-2 shadow-2xl shadow-black/40 transition focus-within:border-sky-300/40 focus-within:shadow-sky-500/10">
          <Wand2 size={20} className="ml-3 shrink-0 text-white/40" />
          <input value={topic} onChange={e => setTopic(e.target.value)} maxLength={160} placeholder="How does the heart pump blood?" aria-label="Topic" className="min-w-0 flex-1 bg-transparent py-3 text-base outline-none placeholder:text-white/30 sm:text-lg" />
          <button disabled={disabled} className="inline-flex shrink-0 items-center gap-2 rounded-xl bg-white px-4 py-3 text-sm font-semibold text-black transition enabled:hover:bg-sky-100 disabled:opacity-40 sm:px-5">Make it <ArrowRight size={16} /></button>
        </div>

        <div className="mt-4 flex flex-wrap items-center justify-center gap-2" role="radiogroup" aria-label="Language">
          <Globe2 size={15} className="text-white/40" />
          {LANGS.map(l => (
            <button type="button" key={l.id} role="radio" aria-checked={lang === l.id} onClick={() => setLang(l.id)}
              className={`inline-flex items-center gap-1.5 rounded-full border px-3.5 py-1.5 text-sm transition ${lang === l.id ? "border-sky-300/50 bg-sky-400/15 text-white" : "border-white/10 bg-white/[.03] text-white/60 hover:text-white"}`}>
              {l.label}{!l.ready && <span className="rounded bg-white/10 px-1 text-[9px] uppercase tracking-wider text-white/50">soon</span>}
            </button>))}
        </div>
        {!chosen.ready && <p className="mt-2 text-center text-xs text-amber-200/80">{chosen.label} script + voice land with the translation gate. This run will be in English.</p>}

        <div className="mt-5 flex flex-wrap justify-center gap-2">
          {TOPICS.map(s => <button type="button" key={s} onClick={() => { setTopic(s); }} className="rounded-full border border-white/10 bg-white/[.03] px-3.5 py-1.5 text-sm text-white/65 transition hover:border-white/25 hover:text-white">{s}</button>)}
        </div>

        <div className="mt-6 flex flex-wrap items-center justify-center gap-x-5 gap-y-3 text-sm text-white/55">
          <label className="flex items-center gap-2">Voice
            <select value={voice} onChange={e => setVoice(e.target.value)} className="rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-white outline-none">
              {(cfg?.voices ?? [{ id: "af_heart", label: "Heart (US)" }]).map((v: any) => <option key={v.id} value={v.id} className="bg-neutral-900">{v.label}</option>)}
            </select></label>
          <label className="flex cursor-pointer items-center gap-2"><input type="checkbox" checked={labels} onChange={e => setLabels(e.target.checked)} className="accent-sky-400" />SAM-verified labels</label>
          <Pill tone="violet">45–75 s</Pill>
        </div>
      </form>

      <div className="mx-auto mt-12 grid max-w-2xl gap-3 text-left sm:grid-cols-3">
        {[[ShieldCheck, "Sourced script", "Wikipedia + PubMed. A critic rejects any line the source does not say."], [ScanEye, "Verified labels", "SAM 3.1 must find the whole structure, or the label is left off."], [BadgeCheck, "Proof panel", "Every claim links to its quote. You can audit the Short in a minute."]].map(([I, t, d]: any) => (
          <div key={t} className="rounded-2xl border border-white/8 bg-white/[.02] p-4"><I size={16} className="text-sky-300" /><p className="mt-2 text-sm font-medium">{t}</p><p className="mt-1 text-xs leading-relaxed text-white/45">{d}</p></div>))}
      </div>
    </motion.section>
  );
}

export function Gallery() {
  const [items, setItems] = useState<any[] | null>(null);
  useEffect(() => { fetch(`${API}/api/shorts`).then(r => r.json()).then(setItems).catch(() => setItems([])); }, []);
  if (!items?.length) return null;
  return (
    <section className="mx-auto mt-20 max-w-5xl">
      <div className="mb-5 flex items-end justify-between"><div><Label>Gallery</Label><h2 className="font-display mt-1 text-2xl font-semibold">Made by the agent</h2></div></div>
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
        {items.slice(0, 8).map(it => (
          <Link key={it.id} href={`/s/${it.id}`} className="group relative aspect-[9/16] overflow-hidden rounded-2xl border border-white/10 bg-white/[.03]">
            {it.poster && <img src={url(it.poster)} alt={it.title} loading="lazy" className="h-full w-full object-cover transition duration-500 group-hover:scale-105" />}
            <span className="absolute inset-0 bg-gradient-to-t from-black/90 via-black/10 to-transparent" />
            <span className="absolute right-3 top-3 grid h-9 w-9 place-items-center rounded-full bg-white/90 text-black opacity-0 transition group-hover:opacity-100"><Play size={14} fill="currentColor" /></span>
            <span className="absolute inset-x-3 bottom-3"><span className="font-display block text-sm font-semibold leading-snug">{it.title}</span>
              <span className="mt-1.5 flex flex-wrap gap-1"><Pill tone="emerald"><BadgeCheck size={10} />{it.claims} sourced</Pill>{it.duration && <Pill tone="slate">{Math.round(it.duration)} s</Pill>}</span></span>
          </Link>))}
      </div>
    </section>
  );
}
