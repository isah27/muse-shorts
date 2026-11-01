"use client";
import Link from "next/link";
import { Brain } from "lucide-react";

export function Pill({ children, tone = "sky" }: { children: React.ReactNode; tone?: "amber" | "emerald" | "rose" | "sky" | "violet" | "slate" }) {
  const c = {
    amber: "border-amber-300/30 bg-amber-400/10 text-amber-200", emerald: "border-emerald-300/30 bg-emerald-400/10 text-emerald-200",
    rose: "border-rose-300/30 bg-rose-400/10 text-rose-200", sky: "border-sky-300/30 bg-sky-400/10 text-sky-200",
    violet: "border-violet-300/30 bg-violet-400/10 text-violet-200", slate: "border-white/10 bg-white/5 text-white/60",
  }[tone];
  return <span className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 py-0.5 text-[11px] font-medium ${c}`}>{children}</span>;
}

export function Nav({ cfg, onHome }: { cfg?: any; onHome?: () => void }) {
  const Logo = (
    <span className="flex items-center gap-2.5">
      <span className="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-sky-400 via-violet-500 to-pink-500 shadow-lg shadow-violet-500/30"><Brain size={18} className="text-white" /></span>
      <span className="font-display text-lg font-semibold tracking-tight">Muse Shorts</span>
    </span>
  );
  return (
    <nav className="relative z-20 mx-auto flex max-w-7xl items-center justify-between px-5 py-5 sm:px-8">
      {onHome ? <button onClick={onHome} aria-label="Home">{Logo}</button> : <Link href="/" aria-label="Home">{Logo}</Link>}
      <div className="flex items-center gap-2 text-xs">
        {cfg?.offline ? <Pill tone="rose">API offline</Pill> : cfg?.mock ? <Pill tone="amber">Demo mode · mock models</Pill> : cfg ? <Pill tone="emerald">Live · Meta models</Pill> : null}
        <span className="hidden text-white/40 md:inline">Muse Image · SAM 3.1 · open-weights critic</span>
      </div>
    </nav>
  );
}

export function Shell({ children }: { children: React.ReactNode }) {
  return (<main className="relative min-h-screen overflow-x-hidden"><div className="aurora" /><div className="grain" />{children}</main>);
}

export const Label = ({ children }: { children: React.ReactNode }) => <p className="text-[11px] font-medium uppercase tracking-[.22em] text-white/40">{children}</p>;
