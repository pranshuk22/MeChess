import clsx from "clsx";
import type { ButtonHTMLAttributes } from "react";

type Variant = "primary" | "secondary" | "ghost";
export function Button({ variant = "secondary", size = "md", className, ...p }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md" }) {
  return (
    <button {...p} className={clsx(
      "inline-flex items-center justify-center gap-2 rounded-md font-medium whitespace-nowrap transition-colors disabled:opacity-45 disabled:pointer-events-none cursor-pointer",
      size === "md" ? "h-9 px-3.5 text-[13.5px]" : "h-7 px-2.5 text-[12.5px]",
      variant === "primary" && "bg-accent text-[var(--accent-text)] hover:brightness-110",
      variant === "secondary" && "bg-surface-2 text-text border border-border hover:bg-[var(--border)]",
      variant === "ghost" && "text-muted hover:bg-surface-2 hover:text-text",
      className,
    )} />
  );
}
