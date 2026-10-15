import clsx from "clsx";
import { BookOpen, Check, Star, ThumbsUp, X } from "lucide-react";
import type { CSSProperties } from "react";
import { CLASS_VAR, type MoveClass } from "@/lib/types";

const GLYPH: Partial<Record<MoveClass, string>> = { brilliant: "!!", great: "!", inaccuracy: "?!", mistake: "?", blunder: "??" };

/** The round badge for a move class (symbol and colour together, so it never relies on colour alone). */
export function ClassIcon({ cls, size = 18, className, style }: { cls: MoveClass; size?: number; className?: string; style?: CSSProperties }) {
  const glyph = GLYPH[cls];
  const icon = size * 0.62;
  return (
    <span className={clsx("inline-grid shrink-0 place-items-center rounded-full font-extrabold leading-none text-white", className)} aria-hidden
      style={{ width: size, height: size, background: CLASS_VAR[cls], fontSize: size * (glyph && glyph.length > 1 ? 0.5 : 0.62), ...style }}>
      {glyph ?? (cls === "best" ? <Star size={icon} strokeWidth={3} fill="currentColor" /> : cls === "excellent" ? <Check size={icon} strokeWidth={3.5} /> : cls === "good" ? <ThumbsUp size={icon} strokeWidth={2.8} />
        : cls === "book" ? <BookOpen size={icon} strokeWidth={2.8} /> : <X size={icon} strokeWidth={3.5} />)}
    </span>
  );
}
