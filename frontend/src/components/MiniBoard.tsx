import type { Arrow } from "@/board/Arrows";
import { Board } from "@/board/Board";

/** A small read-only board for showing a position inside a card. */
export function MiniBoard({ fen, orientation, arrows = [], size = 280 }: { fen: string; orientation: "white" | "black"; arrows?: Arrow[]; size?: number }) {
  return <div className="w-full overflow-hidden rounded-[6px] shadow-[0_1px_2px_rgba(16,24,32,0.12),0_8px_24px_-12px_rgba(16,24,32,0.3)]" style={{ maxWidth: size }}><Board fen={fen} orientation={orientation} movable={null} arrows={arrows} /></div>;
}
