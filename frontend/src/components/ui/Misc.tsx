import clsx from "clsx";
import type { LucideIcon } from "lucide-react";
import type { HTMLAttributes, ReactNode } from "react";

export function Badge({ tone = "neutral", className, ...p }: HTMLAttributes<HTMLSpanElement> & { tone?: "neutral" | "accent" | "good" | "warn" | "bad" }) {
  const tones = { neutral: "bg-sunken text-muted", accent: "bg-accent-soft text-accent", good: "bg-[color-mix(in_srgb,var(--q-best)_14%,transparent)] text-[var(--q-best)]", warn: "bg-[color-mix(in_srgb,var(--q-inaccuracy)_16%,transparent)] text-[color-mix(in_srgb,var(--q-inaccuracy)_25%,var(--text))]", bad: "bg-[color-mix(in_srgb,var(--q-blunder)_14%,transparent)] text-[var(--q-blunder)]" };
  return <span {...p} className={clsx("inline-flex h-5 items-center rounded-[5px] px-1.5 text-[11.5px] font-medium", tones[tone], className)} />;
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx("animate-pulse rounded-md bg-sunken", className)} aria-hidden />;
}

export function Progress({ value, className }: { value: number; className?: string }) {
  return (
    <div className={clsx("h-1.5 overflow-hidden rounded-full bg-sunken", className)} role="progressbar" aria-valuenow={Math.round(value * 100)} aria-valuemin={0} aria-valuemax={100}>
      <div className="h-full rounded-full bg-accent transition-[width] duration-300" style={{ width: `${Math.max(2, value * 100)}%` }} />
    </div>
  );
}

export function EmptyState({ icon: Icon, title, text, action }: { icon: LucideIcon; title: string; text?: ReactNode; action?: ReactNode }) {
  return (
    <div className="grid place-items-center px-6 py-14 text-center">
      <div className="mb-3 grid h-10 w-10 place-items-center rounded-[8px] border border-border bg-surface-2 text-muted"><Icon size={19} strokeWidth={1.7} /></div>
      <h3 className="text-[14.5px] font-semibold tracking-[-0.01em]">{title}</h3>
      {text && <p className="mt-1.5 max-w-sm text-[13.5px] text-muted">{text}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function Stat({ label, value, sub, children }: { label: string; value: ReactNode; sub?: ReactNode; children?: ReactNode }) {
  return (
    <div className="min-w-0 rounded-[8px] border border-border bg-surface px-4 py-3.5 shadow-[var(--shadow-sm)]">
      <div className="text-[12px] font-medium text-muted">{label}</div>
      <div className="mt-1.5 flex flex-wrap items-end justify-between gap-x-3 gap-y-2">
        <div><div className="tnum text-[24px] font-semibold leading-8 tracking-[-0.03em]">{value}</div>{sub && <div className="mt-0.5 text-[12px] text-muted">{sub}</div>}</div>
        {children}
      </div>
    </div>
  );
}
