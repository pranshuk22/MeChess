import { useMemo } from "react";
import { Board } from "@/board/Board";
import { checkSquare } from "@/lib/game";

/** The server sends the legal moves of a guided session as UCI strings; the board wants them per origin square. */
export function legalFromUci(list: string[]): Map<string, string[]> {
  const m = new Map<string, string[]>();
  for (const u of list) { const f = u.slice(0, 2); (m.get(f) ?? m.set(f, []).get(f)!).push(u.slice(2, 4)); }
  return m;
}

export interface GuidedView { fen: string; color: "white" | "black"; over: boolean; legal: string[] }

/** A board for a guided session: you move your colour, the session answers. */
export function GuidedBoard({ view, busy, onMove }: { view: GuidedView; busy: boolean; onMove: (from: string, to: string, promo?: string) => void }) {
  const legal = useMemo(() => (view.over || busy ? undefined : legalFromUci(view.legal)), [view.over, busy, view.legal]);
  return (
    <div className="mx-auto w-full overflow-hidden rounded-[6px] shadow-[0_1px_2px_rgba(16,24,32,0.12),0_12px_32px_-12px_rgba(16,24,32,0.3)]" style={{ maxWidth: "min(100%, calc((100dvh - var(--topbar) - 200px) * var(--board-scale, 1)))" }}>
      <Board fen={view.fen} orientation={view.color} legal={legal} movable={view.color === "white" ? "w" : "b"} checkSquare={checkSquare(view.fen)} onMove={onMove} />
    </div>
  );
}

export const Note = ({ tone = "info", children }: { tone?: "info" | "bad" | "good"; children: React.ReactNode }) => (
  <p role="status" className="rounded-[6px] px-3 py-2 text-[13.5px]" style={{ background: tone === "bad" ? "color-mix(in srgb, var(--q-mistake) 14%, transparent)" : tone === "good" ? "color-mix(in srgb, var(--q-best) 14%, transparent)" : "var(--sunken)" }}>{children}</p>
);
