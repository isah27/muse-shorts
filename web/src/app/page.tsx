"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, RotateCcw } from "lucide-react";
import { API, Ev, derive } from "@/lib/api";
import { Nav, Shell } from "@/components/ui";
import { Create, Gallery } from "@/components/Create";
import { AgentDecisions, Storyboard, Timeline, VerificationTrace } from "@/components/Timeline";
import { Result } from "@/components/Result";

export default function Home() {
  const [topic, setTopic] = useState("");
  const [voice, setVoice] = useState("af_heart");
  const [labels, setLabels] = useState(true);
  const [lang, setLang] = useState("en");
  const [cfg, setCfg] = useState<any>(null);
  const [events, setEvents] = useState<Ev[]>([]);
  const [stepMode, setStepMode] = useState(false);
  const [demoFaults, setDemoFaults] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [phase, setPhase] = useState<"idle" | "running" | "done" | "error">("idle");
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => { fetch(`${API}/api/config`).then(r => r.json()).then(setCfg).catch(() => setCfg({ offline: true })); }, []);

  const start = async (t = topic) => {
    if (t.trim().length < 3) return;
    setTopic(t); setEvents([]); setPhase("running");
    try {
      const r = await fetch(`${API}/api/jobs`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ topic: t, voice, labels, language: lang, step_mode: stepMode, demo_faults: demoFaults }) });
      if (!r.ok) throw new Error(`API ${r.status}`);
      const { id } = await r.json();
      setJobId(id);
      const es = new EventSource(`${API}/api/jobs/${id}/events`);
      esRef.current = es;
      es.onmessage = (m) => {
        const ev: Ev = JSON.parse(m.data);
        setEvents(p => [...p, ev]);
        if (ev.step === "job" && ev.status === "done") setPhase("done");
        if ((ev.step === "job" && ev.status === "rejected") || ev.status === "error") setPhase("error");
      };
      es.addEventListener("end", () => es.close());
    } catch (e: any) { setEvents([{ step: "job", status: "error", message: `Could not reach the API at ${API}. ${e.message}`, t: 0 }]); setPhase("error"); }
  };
  const reset = () => { esRef.current?.close(); setPhase("idle"); setEvents([]); };

  const { steps, frames, claims, final, startEv, error, decisions, checklist, agentNote, trace, domain, paused } = useMemo(() => derive(events), [events]);
  const step = () => jobId && fetch(`${API}/api/jobs/${jobId}/step`, { method: "POST" });

  return (
    <Shell>
      <Nav cfg={cfg} onHome={reset} />
      <div className="relative z-10 mx-auto max-w-7xl px-4 pb-24 sm:px-8">
        <AnimatePresence mode="wait">
          {phase === "idle" ? (
            <motion.div key="idle" exit={{ opacity: 0 }}>
              <Create {...{ topic, setTopic, start, voice, setVoice, labels, setLabels, lang, setLang, cfg }} />
              <div className="mx-auto -mt-4 mb-8 flex max-w-3xl flex-wrap justify-center gap-4 text-xs text-white/55">
                <label className="inline-flex items-center gap-1.5"><input type="checkbox" checked={stepMode} onChange={e => setStepMode(e.target.checked)} /> Step through each agent turn</label>
                <label className="inline-flex items-center gap-1.5"><input type="checkbox" checked={demoFaults} onChange={e => setDemoFaults(e.target.checked)} /> Demo: inject one plan + one script fault to show retries</label>
              </div>
              <Gallery />
            </motion.div>
          ) : (
            <motion.section key="work" initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="pt-4">
              <div className="mb-7 flex flex-wrap items-end justify-between gap-4">
                <div className="min-w-0">
                  <p className="text-xs uppercase tracking-[.25em] text-sky-300/80">{phase === "done" ? "Ready to post" : phase === "error" ? "Something broke" : "Agent at work"}</p>
                  <h1 className="font-display mt-2 text-3xl font-semibold sm:text-5xl">{final?.title ?? topic}</h1>
                </div>
                <button onClick={reset} className="glass inline-flex items-center gap-2 rounded-full px-4 py-2 text-sm text-white/80 transition hover:text-white"><RotateCcw size={15} /> New Short</button>
              </div>
              {error && <div role="alert" className="mb-6 flex items-start gap-3 rounded-2xl border border-rose-400/30 bg-rose-500/10 p-4 text-sm text-rose-100"><AlertTriangle size={18} className="mt-0.5 shrink-0" /><span>{error}</span></div>}
              {phase === "done" && final ? (
                <>
                  <Result final={final} />
                  <div className="mt-12"><p className="mb-3 text-xs uppercase tracking-[.2em] text-white/40">How the agent got here</p><div className="grid gap-6 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]"><Timeline steps={steps} providers={startEv?.providers} frames={frames} claims={claims} /><div className="space-y-6"><VerificationTrace trace={trace} domain={domain} /><AgentDecisions decisions={decisions} checklist={checklist} note={agentNote} maxTurns={startEv?.max_turns} /></div></div></div>
                </>
              ) : (
                <div className="grid gap-6 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
                  <Timeline steps={steps} providers={startEv?.providers} frames={frames} claims={claims} />
                  <div className="space-y-6">{paused && <button onClick={step} className="w-full rounded-xl bg-violet-400 px-4 py-3 text-sm font-semibold text-black transition hover:bg-violet-300">Step: let the agent take its next turn</button>}<VerificationTrace trace={trace} domain={domain} /><AgentDecisions decisions={decisions} checklist={checklist} note={agentNote} maxTurns={startEv?.max_turns} /><Storyboard frames={frames} steps={steps} /></div>
                </div>
              )}
            </motion.section>
          )}
        </AnimatePresence>
      </div>
    </Shell>
  );
}
