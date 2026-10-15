import { formatEval, winPercent } from "@/lib/types";

/** White's share of the bar grows with the evaluation; the value is printed beside it. Dark track, white fill, outlined: it reads on any page colour. */
export function EvalBar({ cp, orientation }: { cp: number; orientation: "white" | "black" }) {
  const white = winPercent(cp);
  const flipped = orientation === "black";
  return (
    <div className="flex w-[18px] flex-col items-center gap-1.5 self-stretch">
      <div className="evalbar w-full flex-1" role="img" aria-label={`Evaluation ${formatEval(cp)}`}>
        <div style={{ transform: `scaleY(${white / 100})`, transformOrigin: flipped ? "top" : "bottom", ...(flipped ? { top: 0, bottom: "auto" } : {}) }} />
      </div>
      <span className="tnum -mx-2 text-[11px] font-semibold text-text">{formatEval(cp)}</span>
    </div>
  );
}
