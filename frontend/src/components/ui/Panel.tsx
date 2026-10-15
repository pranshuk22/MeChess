import clsx from "clsx";
import type { HTMLAttributes, ReactNode } from "react";

/** A card: one hairline border, one radius, no heavy shadow. */
export function Panel({ className, ...p }: HTMLAttributes<HTMLDivElement>) {
  return <div {...p} className={clsx("rounded-[8px] border border-border bg-surface shadow-[var(--shadow-sm)]", className)} />;
}
/** The card's header row: title and a line of context on the left, actions on the right, a hairline underneath. */
export function PanelTitle({ children, right, sub }: { children: ReactNode; right?: ReactNode; sub?: ReactNode }) {
  return (
    <div className="mb-3 flex items-start justify-between gap-3 border-b border-border px-5 py-3.5">
      <div className="min-w-0"><h2 className="text-[14px] font-semibold leading-5 tracking-[-0.01em]">{children}</h2>{sub && <p className="mt-0.5 text-[12.5px] leading-[18px] text-muted">{sub}</p>}</div>
      {right}
    </div>
  );
}
/** Page title row: a title, a line of context, actions on the right. */
export function PageHeader({ title, sub, actions }: { title: ReactNode; sub?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div><h1 className="text-[22px] font-semibold leading-7 tracking-[-0.022em]">{title}</h1>{sub && <p className="mt-1 max-w-[70ch] text-[13.5px] text-muted">{sub}</p>}</div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}
