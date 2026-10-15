import clsx from "clsx";
import type { HTMLAttributes, ReactNode } from "react";

/** A card: hairline border, soft shadow, one radius everywhere. */
export function Panel({ className, ...p }: HTMLAttributes<HTMLDivElement>) {
  return <div {...p} className={clsx("rounded-[12px] border border-border bg-surface shadow-[var(--shadow-sm)]", className)} />;
}
export function PanelTitle({ children, right, sub }: { children: ReactNode; right?: ReactNode; sub?: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-3 px-5 pb-1 pt-4">
      <div><h2 className="text-[13.5px] font-semibold tracking-[-0.01em]">{children}</h2>{sub && <p className="mt-0.5 text-[12.5px] text-muted">{sub}</p>}</div>
      {right}
    </div>
  );
}
/** Page title row: title, a line of context, actions on the right. */
export function PageHeader({ title, sub, actions }: { title: ReactNode; sub?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div><h1 className="text-[24px] font-semibold leading-8 tracking-[-0.025em]">{title}</h1>{sub && <p className="mt-0.5 text-[14px] text-muted">{sub}</p>}</div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}
