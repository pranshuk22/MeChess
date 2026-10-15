import clsx from "clsx";
import type { ButtonHTMLAttributes } from "react";

type Variant = "primary" | "secondary" | "ghost" | "danger";
/** Heights 28 / 32 / 40; flat fills, one border colour, no gradients. */
export function Button({ variant = "secondary", size = "md", className, ...p }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md" | "lg" }) {
  return (
    <button {...p} className={clsx(
      "inline-flex select-none items-center justify-center gap-1.5 whitespace-nowrap rounded-[6px] font-medium transition-[background-color,border-color,color,box-shadow] duration-150 disabled:pointer-events-none disabled:opacity-45 cursor-pointer",
      size === "sm" && "h-7 px-2.5 text-[12.5px]", size === "md" && "h-8 px-3 text-[13px]", size === "lg" && "h-10 px-4 text-[14px]",
      variant === "primary" && "bg-accent text-[var(--accent-text)] shadow-[var(--shadow-sm)] hover:bg-[color-mix(in_srgb,var(--accent)_88%,black)]",
      variant === "secondary" && "border border-[var(--border-strong)] bg-surface text-text shadow-[var(--shadow-sm)] hover:bg-surface-2",
      variant === "ghost" && "text-muted hover:bg-surface-2 hover:text-text",
      variant === "danger" && "border border-[var(--border-strong)] bg-surface text-[color-mix(in_srgb,var(--q-blunder)_75%,var(--text))] shadow-[var(--shadow-sm)] hover:bg-surface-2",
      className,
    )} />
  );
}
