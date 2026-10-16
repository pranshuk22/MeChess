import { useMe } from "@/api/hooks";
import { FlipVertical2, Flag, Loader2, RotateCcw, Swords, Undo2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { Board } from "@/board/Board";
import { AppearanceButton } from "@/components/Appearance";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Field";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { IconButton } from "@/components/ui/IconButton";
import { Badge } from "@/components/ui/Misc";
import { PageHeader, Panel, PanelTitle } from "@/components/ui/Panel";
import { Segmented } from "@/components/ui/Segmented";
import { PlayerStrip } from "@/components/PlayerStrip";
import { applyUci, capturedAfter, checkSquare, legalMap, START_FEN, uciToSan } from "@/lib/game";
import { play as playSound, soundForSan } from "@/lib/sound";

interface PlayState { timeControl: { base: number; inc: number } | null; clock: { white: number; black: number } | null; running: "white" | "black" | null; thinkMs: number; pace: boolean; id: string; fen: string; colour: "white" | "black"; turn: "white" | "black"; moves: { uci: string; san: string }[]; status: "playing" | "over"; result: string | null; reason: string | null; gameId: string | null; opponent: string; inCheck: boolean }
interface Options { stockfish: { available: boolean; levels: { id: number; label: string }[] }; mechess: { available: boolean; min: number; max: number } }

const post = <T,>(path: string, json?: unknown) => api<T>(path, { method: "POST", json });

function outcomeText(s: PlayState) {
  if (!s.result) return "";
  if (s.result === "1/2-1/2") return `Draw by ${s.reason}`;
  const won = (s.result === "1-0") === (s.colour === "white");
  return won ? `You won by ${s.reason}` : `You lost by ${s.reason}`;
}

export function PlayPage() {
  const [game, setGame] = useState<PlayState | null>(null);
  return game ? <GameView game={game} setGame={setGame} onNew={() => setGame(null)} /> : <Setup onStart={setGame} />;
}

function Setup({ onStart }: { onStart: (s: PlayState) => void }) {
  const opts = useQuery({ queryKey: ["play-options"], queryFn: () => api<Options>("/api/play/options") }).data;
  const [kind, setKind] = useState<"stockfish" | "mechess">("stockfish");
  const me = useMe().data;
  const [chosen, setChosen] = useState<{ level?: number; elo?: number }>({});
  const level = chosen.level ?? me?.stockfishLevel ?? 4;                                      // matched to your rating until you pick
  const eloMin = opts?.mechess.min ?? 800, eloMax = opts?.mechess.max ?? 2600;
  const elo = chosen.elo ?? (me?.rating ? Math.min(eloMax, Math.max(eloMin, Math.round(me.rating / 100) * 100)) : 1500);
  const setLevel = (l: number) => setChosen((c) => ({ ...c, level: l })), setElo = (e: number) => setChosen((c) => ({ ...c, elo: e }));
  const [colour, setColour] = useState("white");
  const [tc, setTc] = useState("none");                                                       // "none" or "base+inc" in seconds, or "custom"
  const [custom, setCustom] = useState({ min: "10", inc: "0" });
  const [pace, setPace] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const avail = kind === "stockfish" ? opts?.stockfish.available : opts?.mechess.available;
  const start = async () => {
    setBusy(true); setError("");
    const [base, inc] = tc === "none" ? [null, 0] : tc === "custom" ? [Math.round(Number(custom.min) * 60), Math.round(Number(custom.inc))] : tc.split("+").map(Number);
    try { onStart(await post<PlayState>("/api/play/start", { colour, opponent: kind, level: kind === "stockfish" ? level : elo, base, inc, pace })); }
    catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  return (
    <div className="mx-auto max-w-[760px] px-8 py-8 max-md:px-4">
      <PageHeader title="Play" sub="A game against the computer on this computer. Finished games go to your library for review." />
      <Panel>
        <PanelTitle sub="Choose who to play and how strong">New game</PanelTitle>
        <div className="space-y-5 px-5 pb-5">
          <div><div className="mb-1.5 text-[12.5px] font-medium">Opponent</div>
            <Segmented label="Opponent" value={kind} onChange={setKind} options={[["stockfish", "Stockfish"], ["mechess", "MeChess (plays like a person)"]]} /></div>
          {kind === "stockfish" ? (
            <div><div className="mb-1.5 text-[12.5px] font-medium">Level</div>
              <div className="grid grid-cols-4 gap-2 max-sm:grid-cols-2" role="group" aria-label="Level">
                {opts?.stockfish.levels.map((l) => (
                  <button key={l.id} onClick={() => setLevel(l.id)} aria-pressed={level === l.id}
                    className={`rounded-[8px] border px-3 py-2.5 text-left text-[13px] transition-colors cursor-pointer ${level === l.id ? "border-accent bg-accent-soft" : "border-border hover:bg-surface-2"}`}>
                    <span className="tnum font-display block text-[11px] text-muted">LEVEL {l.id}</span><span className="font-medium">{l.label}</span>
                  </button>
                ))}
              </div>
              <p className="mt-2 text-[12px] text-muted">Stockfish with its strength turned down. Level 1 blunders often; level 8 plays at full strength.{me?.rating ? ` Level ${me.stockfishLevel} is suggested for your rating (${me.rating}${me.mainSpeed ? ` in ${me.mainSpeed}` : ""}); the levels are a first guess, not a rating scale.` : ""}</p>
            </div>
          ) : (
            <div><div className="mb-1.5 flex items-baseline justify-between text-[12.5px] font-medium"><span>Playing strength</span><span className="tnum font-display text-[15px]">about {elo}</span></div>
              <input type="range" min={opts?.mechess.min ?? 800} max={opts?.mechess.max ?? 2600} step={100} value={elo} onChange={(e) => setElo(Number(e.target.value))} aria-label="Playing strength" className="w-full accent-[var(--accent)]" />
              <p className="mt-2 text-[12px] text-muted">MeChess picks sound candidate moves and chooses among them the way a player of this strength does, so it also makes human-like mistakes. The number is a rough guide.{me?.rating ? ` It starts at your own rating (${me.rating}${me.mainSpeed ? ` in ${me.mainSpeed}` : ""}).` : ""}</p>
            </div>
          )}
          <div><div className="mb-1.5 text-[12.5px] font-medium">You play</div>
            <Segmented label="Colour" value={colour} onChange={setColour} options={[["white", "White"], ["black", "Black"], ["random", "Random"]]} /></div>
          <div><div className="mb-1.5 text-[12.5px] font-medium">Time</div>
            <Segmented label="Time control" value={tc} onChange={setTc} options={[["none", "No clock"], ["60+0", "1 min"], ["180+2", "3 + 2"], ["300+3", "5 + 3"], ["600+0", "10 min"], ["900+10", "15 + 10"], ["custom", "Custom"]]} />
            {tc === "custom" && <div className="mt-2 flex items-center gap-2 text-[13px]"><Input aria-label="Minutes per side" type="number" min={1} max={180} className="!w-20" value={custom.min} onChange={(e) => setCustom({ ...custom, min: e.target.value })} /> minutes, plus <Input aria-label="Increment in seconds" type="number" min={0} max={180} className="!w-20" value={custom.inc} onChange={(e) => setCustom({ ...custom, inc: e.target.value })} /> seconds a move</div>}
            <label className="mt-3 flex cursor-pointer items-start gap-2 text-[13px]"><input type="checkbox" checked={pace} onChange={(e) => setPace(e.target.checked)} className="mt-1 accent-[var(--accent)]" /><span><b className="font-medium">The computer takes its time like a person</b><span className="block text-[12px] text-muted">It answers at once, but the page makes it wait: longer in a tense position, a moment for a recapture or an opening move, and in a timed game its clock runs while it thinks.</span></span></label></div>
          {opts && !avail && <p role="alert" className="rounded-[6px] bg-[color-mix(in_srgb,var(--q-inaccuracy)_14%,transparent)] px-3 py-2 text-[13px]">{kind === "stockfish" ? "Stockfish was not found. Install it or set its path in Settings." : "The MeChess engine is not built. Run `make -C engine` in the project folder."}</p>}
          {error && <p role="alert" className="rounded-[6px] bg-[color-mix(in_srgb,var(--q-blunder)_10%,transparent)] px-3 py-2 text-[13px] text-[var(--q-blunder)]">{error}</p>}
          <Button variant="primary" size="lg" disabled={busy || !avail} onClick={start}><Swords size={16} /> {busy ? "Starting…" : "Start the game"}</Button>
        </div>
      </Panel>
    </div>
  );
}

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

function GameView({ game: first, setGame: _unused, onNew }: { game: PlayState; setGame: (s: PlayState) => void; onNew: () => void }) {
  const nav = useNavigate();
  void _unused;
  const [game, setShown] = useState<PlayState>(() => (first.colour === "black" && first.thinkMs > 0 && first.moves.length === 1 ? { ...first, moves: [], fen: START_FEN, turn: "white", running: null } : first));       // as Black the computer's first move appears after it has "thought"
  const [thinkUntil, setThinkUntil] = useState<number | null>(null);                      // performance.now() when the computer's reply will appear
  const [pendingFen, setPendingFen] = useState<string | null>(null);
  const [flipped, setFlipped] = useState(first.colour === "black");
  const [error, setError] = useState("");
  const [confirmResign, setConfirmResign] = useState(false);
  const [now, setNow] = useState(() => performance.now());
  const shownAt = useRef(performance.now());                                              // when the shown state appeared (the running clock counts from here)
  const alive = useRef(true);
  const flagSent = useRef(false);
  useEffect(() => () => { alive.current = false; }, []);

  const reveal = (s: PlayState) => { shownAt.current = performance.now(); setShown(s); setThinkUntil(null); setPendingFen(null); const m = s.moves.at(-1); if (m) playSound(soundForSan(m.san)); if (s.status === "over") playSound(s.result === "1/2-1/2" ? "draw" : (s.result === "1-0") === (s.colour === "white") ? "win" : "lose"); };
  useEffect(() => {                                                                          // the opening reply as Black
    if (first.colour === "black" && first.thinkMs > 0 && first.moves.length === 1) {
      setThinkUntil(performance.now() + first.thinkMs);
      void sleep(first.thinkMs).then(() => alive.current && reveal(first));
    }
  }, []);                                                                                    // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (game.status === "over") return; const t = setInterval(() => setNow(performance.now()), 200); return () => clearInterval(t); }, [game.status]);

  const thinking = thinkUntil !== null;
  const mine = game.turn === game.colour && game.status === "playing" && !pendingFen && !thinking;
  const fen = pendingFen ?? game.fen;
  const legal = useMemo(() => (mine ? legalMap(game.fen) : undefined), [mine, game.fen]);
  const last = game.moves.at(-1);
  const lastMove: [string, string] | null = last ? [last.uci.slice(0, 2), last.uci.slice(2, 4)] : null;
  const opp: "white" | "black" = game.colour === "white" ? "black" : "white";

  /** Seconds on a clock as it should be shown now: the running clock counts down from when the state appeared; the computer's clock keeps running while it is "thinking". */
  const clockOf = (c: "white" | "black"): number | null => {
    if (!game.clock) return null;
    let v = game.clock[c];
    if (thinking && c === opp) v += Math.max(0, thinkUntil! - now) / 1000;
    else if (!thinking && game.running === c && game.status === "playing") v -= Math.max(0, now - shownAt.current) / 1000;
    return Math.max(0, v);
  };
  const mineLeft = clockOf(game.colour);
  useEffect(() => {                                                                          // your clock reached zero: the server checks its own and ends the game
    if (mineLeft !== null && mineLeft <= 0 && game.status === "playing" && !flagSent.current && !thinking) {
      flagSent.current = true;
      void post<PlayState>(`/api/play/${game.id}/flag`).then((s) => alive.current && reveal(s)).catch((e) => setError((e as Error).message));
    }
  }, [mineLeft]);                                                                            // eslint-disable-line react-hooks/exhaustive-deps

  const play = async (from: string, to: string, promo?: string) => {
    const uci = from + to + (promo ?? "");
    const after = applyUci(game.fen, uci);
    if (!after) return;
    setPendingFen(after); setError("");
    playSound(soundForSan(uciToSan(game.fen, uci)));
    const t0 = performance.now();
    try {
      const s = await post<PlayState>(`/api/play/${game.id}/move`, { uci });
      const wait = s.status === "playing" && s.moves.length >= game.moves.length + 2 ? Math.max(0, s.thinkMs - (performance.now() - t0)) : 0;
      if (wait > 0) {                                                                       // the move stays on the board, the computer "thinks", then its reply appears
        setThinkUntil(performance.now() + wait);
        await sleep(wait);
      }
      if (alive.current) reveal(s);
    } catch (e) { setError((e as Error).message); setPendingFen(null); setThinkUntil(null); }
  };
  const act = async (what: "takeback" | "resign") => { setError(""); try { reveal(await post<PlayState>(`/api/play/${game.id}/${what}`)); } catch (e) { setError((e as Error).message); } };
  const rows = Array.from({ length: Math.ceil(game.moves.length / 2) }, (_, i) => [game.moves[2 * i], game.moves[2 * i + 1]]);
  const over = game.status === "over";
  const caps = useMemo(() => capturedAfter(game.moves.map((m) => m.uci)), [game.moves]);
  const cur = caps[caps.length - 1];
  const strip = (c: "white" | "black") => ({ name: c === game.colour ? "You" : game.opponent, elo: null, colour: c, taken: cur[c], lead: Math.max(0, (c === "white" ? 1 : -1) * cur.diff), clock: clockOf(c) });
  const topC = flipped === (game.colour === "white") ? opp : game.colour, botC = topC === "white" ? "black" : "white";

  return (
    <div className="mx-auto grid max-w-[1180px] grid-cols-[minmax(0,1fr)_340px] gap-6 p-6 lg:h-[calc(100dvh-var(--topbar))] max-lg:grid-cols-1 max-md:p-3">
      <section aria-label="Board" className="flex min-h-0 min-w-0 flex-col justify-self-center" style={{ width: "min(100%, calc((100dvh - var(--topbar) - 130px) * var(--board-scale, 1)))" }}>
        <PlayerStrip {...strip(topC)} />
        <div className="my-2 overflow-hidden rounded-[6px] shadow-[0_1px_2px_rgba(16,24,32,0.12),0_12px_32px_-12px_rgba(16,24,32,0.3)]">
          <Board fen={fen} orientation={flipped ? "black" : "white"} legal={legal} movable={mine ? (game.colour === "white" ? "w" : "b") : null} lastMove={lastMove} checkSquare={checkSquare(fen)} onMove={play} />
        </div>
        <PlayerStrip {...strip(botC)} />
        <div className="mt-2 flex h-9 items-center justify-center gap-1">
          <IconButton label="Flip board" onClick={() => setFlipped(!flipped)}><FlipVertical2 size={18} /></IconButton>
          <AppearanceButton />
        </div>
      </section>

      <aside className="flex min-h-0 flex-col gap-4 lg:h-full">
        {over && (
          <Panel className="p-5">
            <Badge tone={game.result === "1/2-1/2" ? "neutral" : (game.result === "1-0") === (game.colour === "white") ? "good" : "bad"}>Game over</Badge>
            <h2 className="mt-3 text-[19px] font-semibold leading-6">{outcomeText(game)}</h2>
            <div className="mt-4 flex flex-wrap gap-2">
              {game.gameId && <Button variant="primary" onClick={() => nav(`/review/${encodeURIComponent(game.gameId!)}`)}>Review the game</Button>}
              <Button onClick={onNew}><RotateCcw size={15} /> New game</Button>
            </div>
          </Panel>
        )}
        <Panel className="flex min-h-[220px] flex-1 flex-col overflow-hidden">
          <PanelTitle sub={`You play ${game.colour} against ${game.opponent}${game.timeControl ? ` · ${game.timeControl.base / 60} min${game.timeControl.inc ? ` + ${game.timeControl.inc} s` : ""}` : ""}`} right={!over && (thinking || !!pendingFen || (game.turn !== game.colour)) ? <span className="flex items-center gap-1.5 text-[12px] text-muted" role="status"><Loader2 size={13} className="animate-spin" /> thinking</span> : undefined}>Moves</PanelTitle>
          <ol className="min-h-0 flex-1 overflow-auto px-3 pb-3 text-[13.5px]" aria-label="Moves">
            {rows.length === 0 && <li className="px-2 py-3 text-muted">{thinking || game.turn !== game.colour ? "The computer is thinking…" : "Your move."}</li>}
            {rows.map(([w, b], i) => (
              <li key={i} className="grid grid-cols-[32px_1fr_1fr] gap-1 rounded px-1 py-1"><span className="tnum text-right text-[12px] text-faint">{i + 1}.</span><b className="px-1.5 font-medium">{w.san}</b><b className="px-1.5 font-medium">{b?.san ?? ""}</b></li>
            ))}
          </ol>
        </Panel>
        {!over && (
          <div className="flex gap-2">
            <Button className="flex-1" onClick={() => act("takeback")} disabled={game.moves.length === 0 || !!pendingFen || thinking}><Undo2 size={15} /> Take back</Button>
            <Button className="flex-1" variant="danger" onClick={() => setConfirmResign(true)}><Flag size={15} /> Resign</Button>
          </div>
        )}
        {error && <p role="alert" className="rounded-[6px] bg-[color-mix(in_srgb,var(--q-blunder)_10%,transparent)] px-3 py-2 text-[13px] text-[var(--q-blunder)]">{error}</p>}
      </aside>
      <ConfirmDialog open={confirmResign} onOpenChange={setConfirmResign} title="Resign this game?" text="The game is lost and saved to your library." confirm="Resign" onConfirm={() => act("resign")} />
    </div>
  );
}
