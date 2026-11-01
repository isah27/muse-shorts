"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { ArrowRight, BadgeCheck } from "lucide-react";
import { API, proofSummary } from "@/lib/api";
import { Nav, Pill, Shell } from "@/components/ui";
import { Actions, Player, PostCopy } from "@/components/Result";
import { ProofPanel } from "@/components/Proof";

export default function SharePage() {
  const { id } = useParams<{ id: string }>();
  const [d, setD] = useState<any>(null);
  const [err, setErr] = useState<false | "missing" | "pending">(false);
  useEffect(() => { fetch(`${API}/api/shorts/${id}`).then(r => { if (r.status === 403) throw "pending"; if (!r.ok) throw "missing"; return r.json(); }).then(setD).catch(e => setErr(e === "pending" ? "pending" : "missing")); }, [id]);
  const s = d ? proofSummary(d) : null;
  return (
    <Shell>
      <Nav />
      <div className="relative z-10 mx-auto max-w-5xl px-4 pb-24 sm:px-8">
        {err && <div className="mx-auto mt-20 max-w-md text-center"><h1 className="font-display text-3xl font-semibold">{err === "pending" ? "Not published yet" : "Short not found"}</h1><p className="mt-2 text-white/50">{err === "pending" ? "This Short is waiting for a human to review and approve it." : "This link may be wrong, or the Short was removed."}</p><Link href="/" className="mt-6 inline-flex items-center gap-2 rounded-xl bg-white px-4 py-3 text-sm font-semibold text-black">Make your own <ArrowRight size={15} /></Link></div>}
        {!d && !err && <div className="mx-auto mt-6 h-[640px] max-w-[360px] rounded-[40px] shimmer" />}
        {d && s && (
          <div className="grid gap-10 pt-2 md:grid-cols-[360px_minmax(0,1fr)]">
            <div className="md:sticky md:top-4 md:self-start"><Player final={d} /><Actions final={d} shareId={d.id} /></div>
            <div className="min-w-0 space-y-6">
              <div>
                <div className="flex flex-wrap gap-2"><Pill tone="emerald"><BadgeCheck size={12} />{s.claims} claims sourced</Pill>{s.labelsTotal > 0 && <Pill tone="sky">{s.labelsKept}/{s.labelsTotal} labels verified</Pill>}<Pill tone="slate">{Math.round(s.seconds)} s</Pill></div>
                <h1 className="font-display mt-3 text-3xl font-semibold leading-tight sm:text-5xl">{d.title}</h1>
                <p className="mt-3 max-w-xl text-white/55">Made by an AI agent that writes only what its sources support and leaves off any label it cannot verify. Audit it below.</p>
              </div>
              <ProofPanel final={d} compact />
              <PostCopy final={d} />
              <Link href="/" className="group flex items-center justify-between rounded-2xl border border-white/10 bg-gradient-to-r from-sky-500/10 via-violet-500/10 to-pink-500/10 p-5 transition hover:border-white/25"><span><span className="font-display block text-lg font-semibold">Make your own Short</span><span className="text-sm text-white/50">Type a topic. Watch the agent check its own work.</span></span><ArrowRight className="transition group-hover:translate-x-1" /></Link>
            </div>
          </div>
        )}
      </div>
    </Shell>
  );
}
