import clsx from "clsx";
import { ChevronDown } from "lucide-react";
import type { InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from "react";

/** One control height (32px), one border, one focus ring for every text field and select. */
const base = "h-8 w-full rounded-[6px] border border-[var(--border-strong)] bg-surface px-2.5 text-[13px] text-text outline-none transition-[border-color,box-shadow] placeholder:text-faint hover:border-[color-mix(in_srgb,var(--border-strong)_60%,var(--text))] focus:border-accent focus:shadow-[0_0_0_3px_color-mix(in_srgb,var(--accent)_20%,transparent)] disabled:opacity-50";

export function Input({ className, icon, ...p }: InputHTMLAttributes<HTMLInputElement> & { icon?: ReactNode }) {
  return icon ? (
    <span className="relative block"><span className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-faint">{icon}</span><input {...p} className={clsx(base, "pl-8", className)} /></span>
  ) : <input {...p} className={clsx(base, className)} />;
}

/** A select with its own chevron, centred on the control's height and the same distance from the edge in every browser (the native arrow is hidden). `className` applies to the wrapper (width, margins). */
export function Select({ className, children, ...p }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <span className={clsx("relative block", className)}>
      <select {...p} className={clsx(base, "cursor-pointer appearance-none pr-8")}>{children}</select>
      <ChevronDown size={15} strokeWidth={2} aria-hidden className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-muted" />
    </span>
  );
}
export function Label({ children, hint, className }: { children: ReactNode; hint?: ReactNode; className?: string }) {
  return <label className={clsx("block", className)}><span className="mb-1.5 block text-[12.5px] font-medium text-text">{children}</span>{hint && <span className="-mt-1 mb-1.5 block text-[12px] font-normal text-muted">{hint}</span>}</label>;
}
