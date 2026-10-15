import { formatEval, winPercent } from "@/lib/types";

export function EvalBar({ cp, orientation }: { cp: number; orientation: "white" | "black" }) {
  const white = winPercent(cp);
  const flipped = orientation === "black";
  return (
    <div className="flex flex-col items-center gap-1.5 self-stretch">
      <div className="evalbar flex-1" role="img" aria-label={`Evaluation ${formatEval(cp)}`}>
        <div style={{ height: `${white}%`, ...(flipped ? { top: 0, bottom: "auto" } : {}) }} />
      </div>
      <span className="tnum text-[11px] font-semibold text-muted">{formatEval(cp)}</span>
    </div>
  );
}
