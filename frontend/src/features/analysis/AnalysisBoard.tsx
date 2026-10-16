import * as Menu from "@radix-ui/react-dropdown-menu";
import { Chess } from "chess.js";
import { ChevronFirst, ChevronLast, ChevronLeft, ChevronRight, Download, FlipVertical2, RotateCcw } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useLiveAnalysis, scoreToCp } from "@/api/live";
import type { Arrow } from "@/board/Arrows";
import { Board } from "@/board/Board";
import { AppearanceButton } from "@/components/Appearance";
import { PlayerStrip } from "@/components/PlayerStrip";
import { Button } from "@/components/ui/Button";
import { IconButton } from "@/components/ui/IconButton";
import { PageHeader, Panel, PanelTitle } from "@/components/ui/Panel";
import { TabList, TabTrigger, Tabs } from "@/components/ui/Tabs";
import { applyUci, capturedAfter, checkSquare, legalMap, movesFromPgn, START_FEN, uciToSan } from "@/lib/game";
import { play as playSound, soundForSan } from "@/lib/sound";
import { EngineTab } from "@/features/review/EngineTab";
import { EvalBar } from "@/features/review/EvalBar";
import { ExplorerTab } from "@/features/review/ExplorerTab";

/** Any position: set it up from a FEN or a PGN (or start from the beginning), move the pieces for both sides, step back and try another line, ask the engine and the explorer. */
export function AnalysisPage() {
  const [sp] = useSearchParams();
  const startFromUrl = sp.get("fen") && validFen(sp.get("fen")!) ? sp.get("fen")! : START_FEN;
  const [startFen, setStartFen] = useState(startFromUrl);
  const [moves, setMoves] = useState<string[]>([]);
  const [ply, setPly] = useState(0);
  const [flipped, setFlipped] = useState(false);
  const [text, setText] = useState("");
  const [error, setError] = useState("");
  const [engineOn, setEngineOn] = useState(true);
  const [multipv, setMultipv] = useState(3);

  const fens = useMemo(() => { const out = [startFen]; for (const u of moves) { const n = applyUci(out.at(-1)!, u); if (!n) break; out.push(n); } return out; }, [startFen, moves]);
  const fen = fens[Math.min(ply, fens.length - 1)];
  const sans = useMemo(() => fens.slice(0, -1).map((f, i) => uciToSan(f, moves[i])), [fens, moves]);
  const live = useLiveAnalysis(engineOn, fen, multipv);
  const turn = fen.split(" ")[1] === "w" ? "white" : "black";
  const caps = useMemo(() => (startFen === START_FEN ? capturedAfter(moves) : null), [startFen, moves]);
  const cap = caps?.[Math.min(ply, caps.length - 1)];
  const legal = useMemo(() => legalMap(fen), [fen]);
  const best = live.lines[0];
  const arrows: Arrow[] = engineOn && best ? [{ from: best.uci[0].slice(0, 2), to: best.uci[0].slice(2, 4), kind: "best" }] : [];
  const cp = engineOn && best ? scoreToCp(best.kind, best.score) * (turn === "white" ? 1 : -1) : 0;      // the engine's score is for the side to move: show White's view

  const playUci = useCallback((uci: string) => {
    const next = applyUci(fen, uci);
    if (!next) return;
    playSound(soundForSan(uciToSan(fen, uci)));
    setMoves((m) => [...m.slice(0, ply), uci]);
    setPly((p) => p + 1);
  }, [fen, ply]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey || (e.target as HTMLElement).closest("input, textarea, select, [role=dialog]")) return;
      if (e.key === "ArrowLeft") setPly((p) => Math.max(0, p - 1));
      else if (e.key === "ArrowRight") setPly((p) => Math.min(moves.length, p + 1));
      else if (e.key === "Home") setPly(0);
      else if (e.key === "End") setPly(moves.length);
      else if (e.key === "f") setFlipped((v) => !v);
      else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [moves.length]);

  const load = () => {
    const t = text.trim();
    setError("");
    if (!t) return;
    if (validFen(t)) { setStartFen(t); setMoves([]); setPly(0); return; }
    const parsed = movesFromPgn(t);
    if (parsed.length === 0) { setError("That is neither a position (FEN) nor a game (PGN) I can read."); return; }
    const hdr = /\[FEN "([^"]+)"\]/.exec(t);
    setStartFen(hdr && validFen(hdr[1]) ? hdr[1] : START_FEN); setMoves(parsed.map((m) => m.uci)); setPly(parsed.length);
  };
  const copy = (v: string) => { void navigator.clipboard?.writeText(v); };
  const pgnText = () => { const c = new Chess(startFen === START_FEN ? undefined : startFen); for (const u of moves) { try { c.move({ from: u.slice(0, 2), to: u.slice(2, 4), promotion: u[4] }); } catch { break; } } return c.pgn(); };
  const rows = Array.from({ length: Math.ceil((sans.length + (startFen.split(" ")[1] === "b" ? 1 : 0)) / 2) }, (_, i) => i);
  const blackFirst = startFen.split(" ")[1] === "b";

  return (
    <div className="mx-auto grid max-w-[1240px] grid-cols-[minmax(0,1fr)_388px] gap-6 p-6 lg:h-[calc(100dvh-var(--topbar))] max-lg:grid-cols-1 max-md:p-3">
      <section aria-label="Board" className="flex min-h-0 min-w-0 flex-col justify-self-center" style={{ width: "min(100%, calc((100dvh - var(--topbar) - 130px) * var(--board-scale, 1)))" }}>
        <PlayerStrip name={flipped ? "White" : "Black"} elo={null} colour={flipped ? "white" : "black"} taken={cap ? cap[flipped ? "white" : "black"] : []} lead={cap ? Math.max(0, (flipped ? 1 : -1) * cap.diff) : 0} />
        <div className="my-2 flex gap-2.5">
          <EvalBar cp={cp} orientation={flipped ? "black" : "white"} muted={!engineOn || !best} />
          <div className="min-w-0 flex-1 overflow-hidden rounded-[6px] shadow-[0_1px_2px_rgba(16,24,32,0.12),0_12px_32px_-12px_rgba(16,24,32,0.3)]">
            <Board fen={fen} orientation={flipped ? "black" : "white"} legal={legal} movable="both" lastMove={ply > 0 && moves[ply - 1] ? [moves[ply - 1].slice(0, 2), moves[ply - 1].slice(2, 4)] : null} checkSquare={checkSquare(fen)} arrows={arrows} onMove={(f, t, p) => playUci(f + t + (p ?? ""))} />
          </div>
        </div>
        <PlayerStrip name={flipped ? "Black" : "White"} elo={null} colour={flipped ? "black" : "white"} taken={cap ? cap[flipped ? "black" : "white"] : []} lead={cap ? Math.max(0, (flipped ? -1 : 1) * cap.diff) : 0} />
        <div className="mt-2 flex h-9 items-center justify-center gap-1">
          <IconButton label="First move (Home)" onClick={() => setPly(0)} disabled={ply === 0}><ChevronFirst size={18} /></IconButton>
          <IconButton label="Previous (←)" onClick={() => setPly(ply - 1)} disabled={ply === 0}><ChevronLeft size={18} /></IconButton>
          <IconButton label="Next (→)" onClick={() => setPly(ply + 1)} disabled={ply >= moves.length}><ChevronRight size={18} /></IconButton>
          <IconButton label="Last move (End)" onClick={() => setPly(moves.length)} disabled={ply >= moves.length}><ChevronLast size={18} /></IconButton>
          <span className="mx-2 h-5 w-px bg-border" />
          <IconButton label="Flip board (F)" onClick={() => setFlipped(!flipped)}><FlipVertical2 size={18} /></IconButton>
          <Menu.Root>
            <Menu.Trigger asChild><IconButton label="Copy or download"><Download size={18} /></IconButton></Menu.Trigger>
            <Menu.Portal><Menu.Content align="end" sideOffset={6} className="z-50 min-w-[190px] rounded-[8px] border border-border bg-surface p-1 text-[13px] shadow-[var(--shadow)]">
              {[["Copy FEN of this position", () => copy(fen)], ["Copy PGN", () => copy(pgnText())]].map(([l, f]) => <Menu.Item key={l as string} onSelect={f as () => void} className="cursor-pointer rounded-[5px] px-2.5 py-1.5 outline-none data-[highlighted]:bg-surface-2">{l as string}</Menu.Item>)}
            </Menu.Content></Menu.Portal>
          </Menu.Root>
          <AppearanceButton />
        </div>
      </section>

      <aside className="flex min-h-0 flex-col gap-3 lg:h-full">
        <PageHeader title="Analysis board" sub="Any position, any line." />
        <Panel className="p-4">
          <label className="block text-[12.5px] font-medium" htmlFor="ab-input">Set up a position or a game</label>
          <textarea id="ab-input" value={text} onChange={(e) => setText(e.target.value)} rows={3} placeholder="Paste a FEN or a PGN" className="mt-1.5 w-full resize-none rounded-[6px] border border-[var(--border-strong)] bg-surface p-2.5 font-mono text-[12px] outline-none focus:border-accent" />
          <div className="mt-2 flex flex-wrap gap-2"><Button size="sm" variant="primary" onClick={load} disabled={!text.trim()}>Load</Button><Button size="sm" onClick={() => { setStartFen(START_FEN); setMoves([]); setPly(0); setText(""); setError(""); }}><RotateCcw size={13} /> Start position</Button></div>
          {error && <p role="alert" className="mt-2 text-[12.5px] text-[var(--q-blunder)]">{error}</p>}
        </Panel>
        <Panel className="flex min-h-[200px] flex-1 flex-col overflow-hidden">
          <Tabs.Root defaultValue="engine" className="flex min-h-0 flex-1 flex-col">
            <TabList className="px-2" aria-label="Analysis sections">{[["engine", "Engine"], ["moves", "Moves"], ["explorer", "Explorer"]].map(([v, l]) => <TabTrigger key={v} value={v} className="!px-2.5 !text-[12.5px]">{l}</TabTrigger>)}</TabList>
            <Tabs.Content value="engine" className="min-h-0 flex-1 overflow-auto outline-none"><EngineTab enabled={engineOn} onToggle={setEngineOn} live={live} multipv={multipv} onMultipv={setMultipv} onPlay={playUci} /></Tabs.Content>
            <Tabs.Content value="moves" className="min-h-0 flex-1 overflow-auto p-2 outline-none">
              {sans.length === 0 ? <p className="p-3 text-[13px] text-muted">Move a piece on the board, or load a game. Stepping back and playing a different move starts a new line.</p> : (
                <ol className="grid grid-cols-[32px_1fr_1fr] gap-y-px text-[13.5px]" aria-label="Moves">
                  {rows.map((r) => {
                    const w = blackFirst ? null : 2 * r, b = blackFirst ? 2 * r - 1 : 2 * r + 1;
                    const cell = (i: number | null) => i !== null && i >= 0 && sans[i] ? <button onClick={() => setPly(i + 1)} aria-current={ply === i + 1 ? "step" : undefined} className={"rounded px-2 py-1 text-left font-medium cursor-pointer " + (ply === i + 1 ? "bg-accent text-[var(--accent-text)]" : "hover:bg-surface-2")}>{sans[i]}</button> : <span />;
                    return <li key={r} className="contents"><span className="tnum px-1 py-1 text-right text-[12px] text-faint">{r + 1}.</span>{cell(w)}{cell(b)}</li>;
                  })}
                </ol>
              )}
            </Tabs.Content>
            <Tabs.Content value="explorer" className="min-h-0 flex-1 overflow-auto outline-none"><ExplorerTab fen={fen} active onPlay={playUci} /></Tabs.Content>
          </Tabs.Root>
        </Panel>
        <Panel className="p-4"><PanelTitle sub="Copy it to share or to keep">Position</PanelTitle><p className="break-all px-5 pb-4 font-mono text-[11.5px] text-muted">{fen}</p></Panel>
      </aside>
    </div>
  );
}

function validFen(f: string) { try { new Chess(f); return true; } catch { return false; } }
