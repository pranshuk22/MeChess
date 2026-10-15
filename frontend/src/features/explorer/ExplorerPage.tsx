import { useMe } from "@/api/hooks";
import { BookOpen, FlipVertical2, RotateCcw, Undo2 } from "lucide-react";
import { useMemo, useState } from "react";
import { useExplorer } from "@/api/hooks";
import { Board } from "@/board/Board";
import { AppearanceButton } from "@/components/Appearance";
import { Select } from "@/components/ui/Field";
import { IconButton } from "@/components/ui/IconButton";
import { EmptyState } from "@/components/ui/Misc";
import { PageHeader, Panel } from "@/components/ui/Panel";
import { ExplorerTab } from "@/features/review/ExplorerTab";
import { applyUci, checkSquare, legalMap, START_FEN, uciToSan } from "@/lib/game";

/** The opening explorer on its own: set up any line on the board and see what players of a rating play there. */
export function ExplorerPage() {
  const [moves, setMoves] = useState<string[]>([]);
  const [flipped, setFlipped] = useState(false);
  const me = useMe().data;
  const [picked, setPicked] = useState<number | null>(null);
  const rating = picked ?? me?.band ?? 1500;                          // your own rating band until you choose another
  const fens = useMemo(() => { const out = [START_FEN]; for (const u of moves) { const n = applyUci(out.at(-1)!, u); if (!n) break; out.push(n); } return out; }, [moves]);
  const fen = fens.at(-1)!;
  const q = useExplorer(fen, true, rating);
  const play = (uci: string) => { if (applyUci(fen, uci)) setMoves((m) => [...m, uci]); };
  const legal = useMemo(() => legalMap(fen), [fen]);
  const last = moves.at(-1);
  const sanLine = fens.slice(0, -1).map((f, i) => uciToSan(f, moves[i]));
  return (
    <div className="mx-auto max-w-[1180px] px-8 py-8 max-md:px-4">
      <PageHeader title="Opening explorer" sub={q.data?.opening ? `${q.data.opening.name} (${q.data.opening.eco})` : "What players of your rating play in any position."}
        actions={<div className="w-40"><Select value={rating} onChange={(e) => setPicked(Number(e.target.value))} aria-label="Rating">{[1000, 1200, 1400, 1500, 1600, 1800, 2000, 2200, 2400].map((r) => <option key={r} value={r}>around {r}{r === me?.band ? " (you)" : ""}</option>)}</Select></div>} />
      {q.data === null ? <Panel><EmptyState icon={BookOpen} title="The opening explorer is not built yet" text="It needs the explorer database built from the Lichess games (see docs/opening-explorer.md); the workspace checklist on the home page shows its state." /></Panel> : (
        <div className="grid grid-cols-[minmax(0,1fr)_380px] gap-6 max-lg:grid-cols-1">
          <div className="mx-auto w-full" style={{ maxWidth: "min(100%, calc(100dvh - var(--topbar) - 240px))" }}>
            <div className="overflow-hidden rounded-[6px] shadow-[0_1px_2px_rgba(16,24,32,0.12),0_12px_32px_-12px_rgba(16,24,32,0.3)]">
              <Board fen={fen} orientation={flipped ? "black" : "white"} legal={legal} movable="both" lastMove={last ? [last.slice(0, 2), last.slice(2, 4)] : null} checkSquare={checkSquare(fen)} onMove={(f, t, p) => play(f + t + (p ?? ""))} />
            </div>
            <div className="mt-2 flex h-9 items-center justify-center gap-1">
              <IconButton label="Take back" onClick={() => setMoves((m) => m.slice(0, -1))} disabled={!moves.length}><Undo2 size={18} /></IconButton>
              <IconButton label="Start position" onClick={() => setMoves([])} disabled={!moves.length}><RotateCcw size={18} /></IconButton>
              <IconButton label="Flip board" onClick={() => setFlipped(!flipped)}><FlipVertical2 size={18} /></IconButton>
              <AppearanceButton />
            </div>
            <p className="mt-2 min-h-5 text-center text-[13px] text-muted">{sanLine.map((m, i) => (i % 2 === 0 ? `${i / 2 + 1}. ${m}` : m)).join(" ")}</p>
          </div>
          <Panel className="overflow-hidden"><ExplorerTab fen={fen} active onPlay={play} /></Panel>
        </div>
      )}
    </div>
  );
}
