import clsx from "clsx";
import type { HTMLAttributes, ReactNode } from "react";

export function Panel({ className, ...p }: HTMLAttributes<HTMLDivElement>) {
  return <div {...p} className={clsx("rounded-lg border border-border bg-surface", className)} />;
}
export function PanelTitle({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return <div className="flex items-center justify-between px-4 pt-3.5 pb-2"><h2 className="text-[12px] font-semibold uppercase tracking-wide text-muted">{children}</h2>{right}</div>;
}
