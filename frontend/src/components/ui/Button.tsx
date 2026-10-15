import clsx from "clsx";
import type { ButtonHTMLAttributes } from "react";

type Variant = "primary" | "secondary" | "ghost" | "danger";
export function Button({ variant = "secondary", size = "md", className, ...p }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md" | "lg" }) {
  return (
    <button {...p} className={clsx(
      "inline-flex select-none items-center justify-center gap-2 whitespace-nowrap rounded-[9px] font-medium tracking-[-0.005em] transition-[background-color,box-shadow,color,transform] duration-150 active:translate-y-px disabled:pointer-events-none disabled:opacity-45 cursor-pointer",
      size === "sm" && "h-8 px-3 text-[12.5px]", size === "md" && "h-9 px-3.5 text-[13.5px]", size === "lg" && "h-11 px-5 text-[14.5px]",
      variant === "primary" && "bg-accent text-[var(--accent-text)] shadow-[inset_0_1px_0_rgba(255,255,255,0.14),0_1px_2px_rgba(16,24,32,0.18)] hover:brightness-[1.08]",
      variant === "secondary" && "border border-border bg-surface text-text shadow-[var(--shadow-sm)] hover:border-[var(--border-strong)] hover:bg-surface-2",
      variant === "ghost" && "text-muted hover:bg-surface-2 hover:text-text",
      variant === "danger" && "border border-border bg-surface text-[var(--q-blunder)] hover:bg-surface-2",
      className,
    )} />
  );
}
