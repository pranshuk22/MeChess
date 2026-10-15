import clsx from "clsx";
import type { InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from "react";

const base = "h-9 w-full rounded-[9px] border border-border bg-surface px-3 text-[13.5px] text-text shadow-[var(--shadow-sm)] outline-none transition-[border-color,box-shadow] placeholder:text-faint hover:border-[var(--border-strong)] focus:border-accent focus:shadow-[0_0_0_3px_color-mix(in_srgb,var(--accent)_18%,transparent)]";

export function Input({ className, icon, ...p }: InputHTMLAttributes<HTMLInputElement> & { icon?: ReactNode }) {
  return icon ? (
    <span className="relative block"><span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-faint">{icon}</span><input {...p} className={clsx(base, "pl-9", className)} /></span>
  ) : <input {...p} className={clsx(base, className)} />;
}
export function Select({ className, ...p }: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...p} className={clsx(base, "cursor-pointer pr-8", className)} />;
}
export function Label({ children, hint, className }: { children: ReactNode; hint?: ReactNode; className?: string }) {
  return <label className={clsx("block", className)}><span className="mb-1.5 block text-[12.5px] font-medium">{children}</span>{hint && <span className="-mt-1 mb-1.5 block text-[12px] text-muted">{hint}</span>}</label>;
}
