import clsx from "clsx";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { Tip } from "./Tip";

export function IconButton({ label, children, className, active, ...p }: ButtonHTMLAttributes<HTMLButtonElement> & { label: string; children: ReactNode; active?: boolean }) {
  return (
    <Tip label={label}>
      <button {...p} aria-label={label} aria-pressed={active} className={clsx(
        "inline-flex h-9 w-9 items-center justify-center rounded-md text-muted transition-colors hover:bg-surface-2 hover:text-text disabled:opacity-40 disabled:pointer-events-none cursor-pointer",
        active && "bg-accent-soft text-accent", className)}>{children}</button>
    </Tip>
  );
}
