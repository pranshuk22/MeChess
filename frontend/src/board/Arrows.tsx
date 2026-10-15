import { memo } from "react";
import { sqToView, type Orientation } from "./geometry";

export type ArrowKind = "best" | "played" | "user";
export interface Arrow { from: string; to: string; kind: ArrowKind }

const COLOUR: Record<ArrowKind, string> = { best: "var(--arrow-best)", played: "var(--arrow-played)", user: "var(--arrow-user)" };

/** Arrow polygon in square units (the SVG viewBox is 8 x 8): a thick shaft and a head, tip pulled back a little so it does not cover the piece. */
function polygon(x1: number, y1: number, x2: number, y2: number): string {
  const dx = x2 - x1, dy = y2 - y1, len = Math.hypot(dx, dy);
  if (len < 0.01) return "";
  const ux = dx / len, uy = dy / len, px = -uy, py = ux;
  const shaft = 0.16, head = 0.36, headLen = 0.42, tip = len - 0.12, base = tip - headLen;
  const pts: [number, number][] = [
    [x1 + px * shaft, y1 + py * shaft], [x1 + ux * base + px * shaft, y1 + uy * base + py * shaft], [x1 + ux * base + px * head, y1 + uy * base + py * head],
    [x1 + ux * tip, y1 + uy * tip],
    [x1 + ux * base - px * head, y1 + uy * base - py * head], [x1 + ux * base - px * shaft, y1 + uy * base - py * shaft], [x1 - px * shaft, y1 - py * shaft],
  ];
  return pts.map((p) => p.join(",")).join(" ");
}

export const Arrows = memo(function Arrows({ arrows, orientation }: { arrows: Arrow[]; orientation: Orientation }) {
  return (
    <svg className="layer" viewBox="0 0 8 8" aria-hidden>
      {arrows.map((a) => {
        const [c1, r1] = sqToView(a.from, orientation), [c2, r2] = sqToView(a.to, orientation);
        return <polygon key={a.kind + a.from + a.to} points={polygon(c1 + 0.5, r1 + 0.5, c2 + 0.5, r2 + 0.5)} fill={COLOUR[a.kind]} opacity={a.kind === "user" ? 0.8 : 0.85} />;
      })}
    </svg>
  );
});
