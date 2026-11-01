"use client";
import { useState } from "react";
import { motion } from "framer-motion";
import { Check, Copy, Download, FileText, Link2, Lock, MessageCircle, Share2, ThumbsDown, ThumbsUp } from "lucide-react";
import { API, url } from "@/lib/api";
import { Label, Pill } from "./ui";
import { ProofPanel } from "./Proof";

export function Player({ final }: { final: any }) {
  return (
    <div className="relative mx-auto w-full max-w-[360px] rounded-[40px] border border-white/15 bg-black p-2.5 shadow-2xl shadow-sky-500/10">
      <video src={url(final.video)} poster={url(final.scenes?.[0]?.labeled ?? final.scenes?.[0]?.image)} controls playsInline preload="metadata" className="aspect-[9/16] w-full rounded-[32px] bg-black object-cover" />
    </div>
  );
}

/** Human sign-off: a new Short stays pending_review (hidden, no export) until someone approves it here. */
export function Review({ shareId, status, setStatus }: { shareId: string; status: string; setStatus: (s: string) => void }) {
  const [busy, setBusy] = useState(false), [err, setErr] = useState("");
  const decide = async (decision: "approve" | "reject") => {
    setBusy(true); setErr("");
    try {
      const r = await fetch(`${API}/api/shorts/${shareId}/review`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ decision }) });
      const j = await r.json();
      if (!r.ok) throw new Error(j.detail ?? `API ${r.status}`);
      setStatus(j.status);
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };
  const tone = status === "approved" ? "border-emerald-300/30 bg-emerald-500/10 text-emerald-100" : status === "rejected" ? "border-rose-300/30 bg-rose-500/10 text-rose-100" : "border-amber-300/30 bg-amber-400/10 text-amber-100";
  return (
    <div className={`mx-auto mt-5 w-full max-w-[360px] rounded-2xl border p-3 text-sm ${tone}`}>
      <p className="font-medium">{status === "approved" ? "Approved · published and exportable" : status === "rejected" ? "Rejected · not published" : "Pending review · not published yet"}</p>
      {status !== "approved" && <p className="mt-0.5 text-xs opacity-70">Watch it and check the proof. Publishing and downloads unlock after approval.</p>}
      <div className="mt-2.5 grid grid-cols-2 gap-2">
        <button disabled={busy || status === "approved"} onClick={() => decide("approve")} className="inline-flex items-center justify-center gap-1.5 rounded-xl bg-emerald-400 px-3 py-2 text-sm font-semibold text-black transition hover:bg-emerald-300 disabled:opacity-40"><ThumbsUp size={15} /> Approve</button>
        <button disabled={busy || status === "rejected"} onClick={() => decide("reject")} className="inline-flex items-center justify-center gap-1.5 rounded-xl border border-rose-300/40 px-3 py-2 text-sm font-semibold text-rose-100 transition hover:bg-rose-500/20 disabled:opacity-40"><ThumbsDown size={15} /> Reject</button>
      </div>
      {err && <p className="mt-2 text-xs text-rose-200">{err}</p>}
    </div>
  );
}

export function Actions({ final, shareId, status = "approved" }: { final: any; shareId?: string; status?: string }) {
  const [copied, setCopied] = useState<string | null>(null);
  const flash = (k: string) => { setCopied(k); setTimeout(() => setCopied(null), 1600); };
  const link = typeof window !== "undefined" && shareId ? `${window.location.origin}/s/${shareId}` : "";
  const text = `${final.title} · every claim sourced, every label verified`;
  if (status !== "approved") return (
    <div className="mx-auto mt-3 w-full max-w-[360px]"><p className="inline-flex w-full items-center justify-center gap-2 rounded-xl border border-white/10 px-4 py-3 text-sm text-white/45"><Lock size={15} /> MP4, full pack and share link unlock after approval</p></div>
  );
  return (
    <div className="mx-auto mt-5 w-full max-w-[360px] space-y-3">
      <div className="grid grid-cols-2 gap-3">
        <a href={url(final.video)} download className="inline-flex items-center justify-center gap-2 rounded-xl bg-white px-4 py-3 text-sm font-medium text-black transition hover:bg-sky-100"><Download size={16} /> MP4</a>
        {final.zip && <a href={shareId ? `${API}/api/shorts/${shareId}/export` : url(final.zip)} download className="glass inline-flex items-center justify-center gap-2 rounded-xl px-4 py-3 text-sm font-medium transition hover:border-white/25"><Download size={16} /> Full pack</a>}
      </div>
      {shareId && (
        <div className="grid grid-cols-2 gap-3">
          <button onClick={() => { navigator.clipboard.writeText(link); flash("link"); }} className="glass inline-flex items-center justify-center gap-2 rounded-xl px-4 py-3 text-sm font-medium transition hover:border-white/25">{copied === "link" ? <Check size={16} className="text-emerald-300" /> : <Link2 size={16} />}{copied === "link" ? "Copied" : "Copy share link"}</button>
          <a href={`https://wa.me/?text=${encodeURIComponent(`${text} ${link}`)}`} target="_blank" rel="noreferrer" className="inline-flex items-center justify-center gap-2 rounded-xl bg-emerald-500/90 px-4 py-3 text-sm font-medium text-black transition hover:bg-emerald-400"><MessageCircle size={16} /> WhatsApp</a>
        </div>
      )}
      <p className="text-center text-xs text-white/40">{final.duration?.toFixed(0)} s · 1080×1920 · captions burned in · SRT included</p>
    </div>
  );
}

export function PostCopy({ final }: { final: any }) {
  const [copied, setCopied] = useState(false);
  const post = `${final.caption ?? ""}\n\n${(final.hashtags ?? []).join(" ")}`;
  if (!final.caption) return null;
  return (
    <div className="glass rounded-3xl p-5">
      <div className="mb-3 flex items-center justify-between"><Label>Post copy</Label>
        <button onClick={() => { navigator.clipboard.writeText(post); setCopied(true); setTimeout(() => setCopied(false), 1500); }} className="inline-flex items-center gap-1.5 text-xs text-white/60 transition hover:text-white">{copied ? <Check size={13} className="text-emerald-300" /> : <Copy size={13} />}{copied ? "Copied" : "Copy"}</button></div>
      <p className="text-[15px] leading-relaxed">{final.caption}</p>
      <div className="mt-2.5 flex flex-wrap gap-1.5">{(final.hashtags ?? []).map((h: string) => <Pill key={h}>{h}</Pill>)}</div>
    </div>
  );
}

export function Result({ final }: { final: any }) {
  const shareId = final.id;
  const [status, setStatus] = useState<string>(final.status ?? "pending_review");
  return (
    <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} className="grid gap-8 lg:grid-cols-[380px_minmax(0,1fr)] lg:gap-10">
      <div className="lg:sticky lg:top-4 lg:self-start"><Player final={final} />{shareId && <Review shareId={shareId} status={status} setStatus={setStatus} />}<Actions final={final} shareId={shareId} status={status} />
        {shareId && status === "approved" && <a href={`/s/${shareId}`} className="mx-auto mt-3 flex w-full max-w-[360px] items-center justify-center gap-2 text-xs text-white/50 transition hover:text-white"><Share2 size={13} />Open public share page</a>}
      </div>
      <div className="min-w-0 space-y-6">
        <ProofPanel final={final} />
        <PostCopy final={final} />
        <div className="glass rounded-3xl p-5">
          <div className="mb-3 flex items-center gap-2"><FileText size={14} className="text-white/40" /><Label>Narration</Label></div>
          <ol className="space-y-2.5">{final.scenes.map((s: any, i: number) => (
            <li key={i} className="flex gap-3 text-[15px] leading-relaxed"><span className="mt-0.5 font-mono text-xs text-white/30">{String(i + 1).padStart(2, "0")}</span>
              <span className="text-white/75">{s.narration}<span className="ml-2 text-xs text-white/30">{s.audio_seconds?.toFixed(1)}s</span></span></li>))}</ol>
        </div>
      </div>
    </motion.div>
  );
}
