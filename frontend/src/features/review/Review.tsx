import { TabList, TabTrigger, Tabs } from "@/components/ui/Tabs";
import * as Menu from "@radix-ui/react-dropdown-menu";
import { ChevronFirst, ChevronLast, ChevronLeft, ChevronRight, Download, FlipVertical2, GitBranch, Pause, Play, RotateCcw, SkipForward, Sparkles, Target, Undo2, Volume2, VolumeX } from "lucide-react";
import { memo, useCallback, useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useAnalyse, useGame } from "@/api/hooks";
import type { Arrow } from "@/board/Arrows";
import { Board } from "@/board/Board";
import { AppearanceButton } from "@/components/Appearance";
import { ClassIcon } from "@/components/ClassIcon";
import { Button } from "@/components/ui/Button";
import { IconButton } from "@/components/ui/IconButton";
import { EmptyState, Skeleton } from "@/components/ui/Misc";
import { Panel } from "@/components/ui/Panel";
import { Segmented } from "@/components/ui/Segmented";
import { formatDate } from "@/lib/format";
import { applyUci, capturedAfter, checkSquare, fensFromUci, legalMap, movesFromPgn, uciToSan } from "@/lib/game";
import { keyMoments, stepMoment, type Moment } from "@/lib/moments";
import { play as playSound, soundForSan } from "@/lib/sound";
import { useUi } from "@/state/ui";
import { scoreToCp, useLiveAnalysis, type Live } from "@/api/live";
import { EngineTab } from "./EngineTab";
import { CoachCard } from "./CoachCard";
import { PlayerStrip, type Strip } from "@/components/PlayerStrip";
import { TimeChart } from "./TimeChart";
import { ExplorerTab } from "./ExplorerTab";
import { BAD, type AnalysedMove, type GameDetail, type MoveClass } from "@/lib/types";
import { EvalBar } from "./EvalBar";
import { EvalGraph } from "./EvalGraph";
import { MoveList } from "./MoveList";
import { Summary } from "./Summary";
import { useRetry } from "./useRetry";

const NO_BADGE: MoveClass[] = ["book", "good", "excellent"];
const TAB_BODY = "min-h-0 flex-1 overflow-auto outline-none";

export function ReviewPage() {
  const { id } = useParams();
  const nav = useNavigate();
  const { data: game, isLoading, isError } = useGame(id);
  if (!id) return <div className="p-10"><Panel><EmptyState icon={Target} title="Pick a game to review" text="Open a game from your library." action={<Button variant="primary" onClick={() => nav("/library")}>Go to the library</Button>} /></Panel></div>;
  if (isLoading) return <div className="mx-auto grid max-w-[1240px] grid-cols-[minmax(0,1fr)_380px] gap-5 p-6"><Skeleton className="aspect-square w-full rounded-[8px]" /><Skeleton className="h-[480px] rounded-[8px]" /></div>;
  if (isError || !game) return <div className="p-10"><Panel><EmptyState icon={Target} title="That game is not in your library" action={<Button onClick={() => nav("/library")}>Back to the library</Button>} /></Panel></div>;
  return <ReviewGame key={game.id} game={game} />;
}

/** The moves to show: the analysed moves, or (for a game without analysis) the plain moves of its PGN, so it can still be stepped through. */
function useMoves(game: GameDetail): AnalysedMove[] {
  return useMemo(() => game.moves.length ? game.moves : movesFromPgn(game.pgn ?? "").map((m) => ({ san: m.san, uci: m.uci, cls: "good" as MoveClass, loss: 0, best: m.uci, winBefore: 0.5, winAfter: 0.5, cp: 0 })), [game]);
}

function ReviewGame({ game: loaded }: { game: GameDetail }) {
  const nav = useNavigate();
  const moves = useMoves(loaded);
  const game = useMemo<GameDetail>(() => ({ ...loaded, moves }), [loaded, moves]);
  const analysed = loaded.analysed;
  const userIsWhite = game.user !== "black";
  const [qs] = useSearchParams();
  const [ply, setPly] = useState(() => { const n = Number(qs.get("ply")); return Number.isInteger(n) && n > 0 ? Math.min(n, moves.length) : 0; });
  const [flipped, setFlipped] = useState(!userIsWhite);
  const [showBest, setShowBest] = useState(true);
  const [retryOn, setRetryOn] = useState(false);
  const [variation, setVariation] = useState<string[]>([]);                              // moves the player tried from the position at `ply` (a side line, not part of the game)
  const [engineOn, setEngineOn] = useState(() => { try { return localStorage.getItem("mechess.engine") === "1"; } catch { return false; } });
  const [multipv, setMultipv] = useState(3);
  const [playing, setPlaying] = useState(false);                                          // autoplay: one move a second
  const interacted = useRef(false);                                                       // sounds only after the player has done something (browsers block them before)
  const sound = useUi((u) => u.sound), setSound = useUi((u) => u.setSound);
  const fens = useMemo(() => fensFromUci(moves.map((m) => m.uci)), [moves]);
  const checks = useMemo(() => fens.map(checkSquare), [fens]);                      // once per game, not on every render
  const n = moves.length;
  const fen = fens[ply];
  const varFens = useMemo(() => { const out: string[] = []; let f = fen; for (const u of variation) { const nf = applyUci(f, u); if (!nf) break; out.push(nf); f = nf; } return out; }, [fen, variation]);
  const inVariation = variation.length > 0 && varFens.length === variation.length;
  const fenNow = inVariation ? varFens[varFens.length - 1] : fen;
  const lastVar = inVariation ? variation[variation.length - 1] : null;
  const last = !inVariation && ply > 0 ? moves[ply - 1] : null;
  const lastMove: [string, string] | null = lastVar ? [lastVar.slice(0, 2), lastVar.slice(2, 4)] : last ? [last.uci.slice(0, 2), last.uci.slice(2, 4)] : null;
  const next = inVariation ? undefined : moves[ply];
  const cp = ply === 0 ? 20 : moves[ply - 1].cp;
  const live = useLiveAnalysis(engineOn && !retryOn, fenNow, multipv);
  const toggleEngine = (v: boolean) => { setEngineOn(v); try { localStorage.setItem("mechess.engine", v ? "1" : "0"); } catch { /* not remembered */ } };

  const mistakes = useMemo(() => analysed ? moves.map((m, i) => ({ m, i })).filter(({ m, i }) => (i % 2 === 0) === userIsWhite && m.loss >= 0.1 && (m.cls === "mistake" || m.cls === "blunder" || m.cls === "miss")).sort((a, b) => b.m.loss - a.m.loss) : [], [moves, userIsWhite, analysed]);
  const retry = useRetry(game, mistakes, retryOn, () => setRetryOn(false));
  const moments = useMemo(() => (analysed ? keyMoments(moves, userIsWhite, loaded.bookEnd ?? 0) : []), [moves, userIsWhite, analysed, loaded.bookEnd]);
  const caps = useMemo(() => capturedAfter(moves.map((m) => m.uci)), [moves]);
  const jump = useCallback((dir: 1 | -1) => { const m = stepMoment(moments, ply, dir); if (m) { setRetryOn(false); setVariation([]); setPly(m.ply); } }, [moments, ply]);

  useEffect(() => {                                                                      // autoplay
    if (!playing) return;
    if (ply >= n || variation.length || retryOn) { setPlaying(false); return; }
    const t = setTimeout(() => setPly((p) => Math.min(n, p + 1)), 1000);
    return () => clearTimeout(t);
  }, [playing, ply, n, variation.length, retryOn]);
  useEffect(() => {                                                                      // the sound of the move just shown
    if (!interacted.current) return;
    const san = inVariation ? uciToSan(varFens.length > 1 ? varFens[varFens.length - 2] : fen, variation[variation.length - 1]) : last?.san;
    if (san) playSound(soundForSan(san));
  }, [ply, variation.length]);                                                           // eslint-disable-line react-hooks/exhaustive-deps

  const playUci = useCallback((uci: string) => {
    if (!inVariation && moves[ply]?.uci === uci) { setPly((p) => p + 1); return; }              // the game's own next move: just go forward
    if (applyUci(fenNow, uci)) setVariation((v) => [...(inVariation ? v : []), uci]);
  }, [inVariation, moves, ply, fenNow]);
  const legal = useMemo(() => (retry ? undefined : legalMap(fenNow)), [retry, fenNow]);

  const arrows = useMemo<Arrow[]>(() => {
    if (inVariation || retry) return engineOn && live.lines[0] && !retry ? [{ from: live.lines[0].uci[0].slice(0, 2), to: live.lines[0].uci[0].slice(2, 4), kind: "best" }] : [];
    if (!analysed || !showBest || !next) return [];
    const out: Arrow[] = [{ from: next.best.slice(0, 2), to: next.best.slice(2, 4), kind: "best" }];
    if (next.uci !== next.best && BAD.includes(next.cls)) out.push({ from: next.uci.slice(0, 2), to: next.uci.slice(2, 4), kind: "played" });
    return out;
  }, [analysed, showBest, next, retry, inVariation, engineOn, live.lines]);

  useEffect(() => {
    if (retryOn) return;
    const onKey = (e: KeyboardEvent) => {
      interacted.current = true;
      if (e.metaKey || e.ctrlKey || e.altKey) return;                                  // Cmd/Ctrl+F (find), Alt+Left (back) and the like belong to the browser
      const target = e.target as HTMLElement;
      if (target.closest("input, textarea, select, [role=dialog], [role=switch]") || target.matches(".board[data-kbmode='1']")) return;     // a board reached with the keyboard uses the arrows itself
      if (e.key === "ArrowLeft") { if (variation.length) setVariation((v) => v.slice(0, -1)); else setPly((p) => Math.max(0, p - 1)); }
      else if (e.key === "ArrowRight") { if (!variation.length) setPly((p) => Math.min(n, p + 1)); }
      else if (e.key === "Home") { setVariation([]); setPly(0); }
      else if (e.key === "End") { setVariation([]); setPly(n); }
      else if (e.key === "Escape") setVariation([]);
      else if (e.key === "f") setFlipped((f) => !f);
      else if (e.key === "b") setShowBest((b) => !b);
      else if (e.key === "n") jump(1);
      else if (e.key === "p") jump(-1);
      else if (e.key === "e") toggleEngine(!engineOn);
      else if (e.key === " ") setPlaying((v) => !v);
      else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [n, retryOn, variation.length, jump, engineOn]);

  const orientation = flipped ? "black" : "white";
  const lastOf = (colour: "white" | "black") => { for (let p = Math.min(ply, n); p >= 1; p--) if ((p % 2 === 1) === (colour === "white")) return p; return 0; };
  const clockOf = (colour: "white" | "black"): number | null => { const c = loaded.clocks ?? []; if (!c.length) return null; const p = lastOf(colour); return p ? c[p - 1] ?? null : loaded.base ?? null; };
  const mk = (colour: "white" | "black"): Strip => ({ name: colour === "white" ? game.white : game.black, elo: colour === "white" ? game.whiteElo : game.blackElo, colour, acc: game.accuracy?.[colour] ?? null,
    perf: loaded.perf?.[colour]?.rating ?? null, taken: caps[Math.min(ply, caps.length - 1)][colour], lead: Math.max(0, (colour === "white" ? 1 : -1) * caps[Math.min(ply, caps.length - 1)].diff), clock: clockOf(colour),
    title: loaded.perf?.[colour] ? `Estimated performance: ${loaded.perf[colour]!.rating} (80% range ${loaded.perf[colour]!.low} to ${loaded.perf[colour]!.high}), from ${loaded.perf[colour]!.moves} moves` : undefined });
  const top = mk(flipped ? "white" : "black"), bottom = mk(flipped ? "black" : "white");
  const goto = useCallback((p: number) => { setRetryOn(false); setVariation([]); setPly(p); }, []);
  const tryLine = useCallback((fromPly: number, ucis: string[]) => { setRetryOn(false); setPly(fromPly); setVariation(ucis); }, []);
  const dPly = useDeferredValue(ply);                                                  // the side panels follow one beat later: the board moves first
  const boardFen = retry ? retry.fen : fenNow;
  const badge = analysed && !retry && last && !NO_BADGE.includes(last.cls) ? { sq: last.uci.slice(2, 4), cls: last.cls } : null;
  const liveTop = engineOn && !retry && live.lines[0] ? scoreToCp(live.lines[0].kind, live.lines[0].score) : null;
  const step = ((loaded.openingSteps ?? []) as unknown as [number, string, string][]).filter((s2) => s2[0] <= ply).at(-1);
  const leftTheory = (loaded.bookEnd ?? 0) > 0 && ply > (loaded.bookEnd ?? 0);
  const copy = (text: string) => { void navigator.clipboard?.writeText(text); };
  const download = () => { const url = URL.createObjectURL(new Blob([loaded.pgn ?? ""], { type: "application/x-chess-pgn" })); const a = document.createElement("a"); a.href = url; a.download = `${game.white}-vs-${game.black}.pgn`.replace(/[^\w.-]+/g, "_"); a.click(); URL.revokeObjectURL(url); };

  return (
    <div className="mx-auto grid max-w-[1240px] grid-cols-[minmax(0,1fr)_388px] gap-6 p-6 lg:h-[calc(100dvh-var(--topbar))] max-lg:grid-cols-1 max-md:p-3" onPointerDown={() => { interacted.current = true; }}>
      <section aria-label="Board" className="flex min-h-0 min-w-0 flex-col justify-self-center" style={{ width: "min(100%, calc((100dvh - var(--topbar) - 150px) * var(--board-scale, 1)))" }}>
        <PlayerStrip {...top} />
        {inVariation && (
          <div className="mt-2 flex items-center justify-between gap-3 rounded-[6px] bg-accent-soft px-3 py-1.5 text-[12.5px] text-accent" role="status">
            <span className="flex items-center gap-2 font-medium"><GitBranch size={14} /> Trying a side line: {variation.length} move{variation.length === 1 ? "" : "s"}</span>
            <button onClick={() => setVariation([])} className="inline-flex items-center gap-1 font-semibold hover:underline cursor-pointer"><Undo2 size={13} /> Back to the game (Esc)</button>
          </div>
        )}
        <div className="my-2 flex gap-2.5">
          <EvalBar cp={liveTop ?? (retry || !analysed || inVariation ? 0 : cp)} orientation={orientation} muted={liveTop === null && (!analysed || inVariation)} />
          <div className="min-w-0 flex-1 overflow-hidden rounded-[6px] shadow-[0_1px_2px_rgba(16,24,32,0.12),0_12px_32px_-12px_rgba(16,24,32,0.3)]">
            <Board fen={boardFen} orientation={orientation} lastMove={retry ? retry.lastMove : lastMove} checkSquare={retry || inVariation ? checkSquare(boardFen) : checks[ply]} arrows={retry ? retry.arrows : arrows}
              marks={retry?.marks} legal={retry ? retry.legal : legal} movable={retry ? (userIsWhite ? "w" : "b") : "both"} badge={badge} onMove={retry ? retry.onMove : (f, t, p) => playUci(f + t + (p ?? ""))} />
          </div>
        </div>
        <PlayerStrip {...bottom} />
        <p className="mt-1 min-h-5 truncate px-0.5 text-[12.5px] text-muted" aria-live="polite">{step ? <><b className="font-semibold text-text">{step[2]}</b> <span className="text-faint">{step[1]}</span>{leftTheory && <> · left theory after move {Math.ceil((loaded.bookEnd ?? 0) / 2)}</>}</> : ply === 0 ? "Starting position" : ""}</p>
        <div className="mt-1 flex h-9 items-center justify-center gap-1">
          {!retry && <>
            <IconButton label="First move (Home)" onClick={() => { setVariation([]); setPly(0); }} disabled={ply === 0 && !variation.length}><ChevronFirst size={18} /></IconButton>
            <IconButton label="Previous (←)" onClick={() => (variation.length ? setVariation((v) => v.slice(0, -1)) : setPly(ply - 1))} disabled={ply === 0 && !variation.length}><ChevronLeft size={18} /></IconButton>
            <IconButton label={playing ? "Pause (Space)" : "Play the game (Space)"} onClick={() => setPlaying(!playing)} disabled={ply === n || variation.length > 0} active={playing}>{playing ? <Pause size={17} /> : <Play size={17} />}</IconButton>
            <IconButton label="Next (→)" onClick={() => setPly(ply + 1)} disabled={ply === n || variation.length > 0}><ChevronRight size={18} /></IconButton>
            <IconButton label="Last move (End)" onClick={() => { setVariation([]); setPly(n); }} disabled={ply === n && !variation.length}><ChevronLast size={18} /></IconButton>
            <span className="mx-2 h-5 w-px bg-border" />
          </>}
          <IconButton label="Flip board (F)" onClick={() => setFlipped(!flipped)}><FlipVertical2 size={18} /></IconButton>
          {!retry && analysed && <IconButton label="Show engine's best move (B)" onClick={() => setShowBest(!showBest)} active={showBest}><Target size={18} /></IconButton>}
          <IconButton label={sound ? "Sounds on: click to mute" : "Sounds off: click to turn on"} onClick={() => setSound(!sound)}>{sound ? <Volume2 size={18} /> : <VolumeX size={18} />}</IconButton>
          <Menu.Root>
            <Menu.Trigger asChild><IconButton label="Copy or download"><Download size={18} /></IconButton></Menu.Trigger>
            <Menu.Portal>
              <Menu.Content align="end" sideOffset={6} className="z-50 min-w-[190px] rounded-[8px] border border-border bg-surface p-1 text-[13px] shadow-[var(--shadow)]">
                {[["Analyse this position on the analysis board", () => nav(`/analysis?fen=${encodeURIComponent(fenNow)}`)], ["Copy FEN of this position", () => copy(fenNow)], ["Copy PGN of the game", () => copy(loaded.pgn ?? "")], ["Download PGN", download]].map(([l, f]) => (
                  <Menu.Item key={l as string} onSelect={f as () => void} className="cursor-pointer rounded-[5px] px-2.5 py-1.5 outline-none data-[highlighted]:bg-surface-2">{l as string}</Menu.Item>
                ))}
              </Menu.Content>
            </Menu.Portal>
          </Menu.Root>
          <AppearanceButton />
        </div>
      </section>

      <Sidebar game={game} loaded={loaded} analysed={analysed} ply={dPly} realPly={ply} fens={fens} userIsWhite={userIsWhite} mistakes={mistakes} moments={moments} jump={jump} retryOn={retryOn} onRetry={() => setRetryOn(true)} goto={goto}
        retryPanel={retry ? retry.panel : null} tryLine={tryLine} fenNow={fenNow} engine={{ on: engineOn, setOn: toggleEngine, live, multipv, setMultipv }} onPlay={playUci} />
    </div>
  );
}

type SideProps = { tryLine: (fromPly: number, ucis: string[]) => void; fenNow: string; engine: { on: boolean; setOn: (v: boolean) => void; live: Live; multipv: number; setMultipv: (n: number) => void }; onPlay: (uci: string) => void; game: GameDetail; loaded: GameDetail; analysed: boolean; ply: number; realPly: number; fens: string[]; userIsWhite: boolean; mistakes: { m: AnalysedMove; i: number }[]; moments: Moment[]; jump: (dir: 1 | -1) => void; retryOn: boolean; onRetry: () => void; goto: (p: number) => void; retryPanel: React.ReactNode };

const Sidebar = memo(function Sidebar({ game, loaded, analysed, ply, fens, userIsWhite, mistakes, moments, jump, retryOn, onRetry, goto, retryPanel, fenNow, engine, onPlay, tryLine }: SideProps) {
  const [showEvals, setShowEvals] = useState(false);
  const [who, setWho] = useState<"all" | "mine" | "opp">("all");
  const analyse = useAnalyse();
  const fen = fens[ply];
  const moves = game.moves;
  const last = ply > 0 ? moves[ply - 1] : null;
  const next = moves[ply];
  const me = userIsWhite ? "white" : "black";
  const you = game.accuracy ? game.accuracy[me] : null;
  const perf = loaded.perf?.[me];
  const shown = moments.filter((m) => who === "all" || (who === "mine") === m.mine);
  const clocks = loaded.clocks ?? [];
  return (
    <aside className="flex min-h-0 flex-col gap-3 lg:h-full">
      <Panel className="p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="truncate text-[15.5px] font-semibold leading-6">{game.title ?? `${game.white} – ${game.black}`}</h1>
            <p className="truncate text-[12.5px] text-muted">{game.opening || "Opening unknown"}{game.speed ? ` · ${game.speed}` : ""}{game.date ? ` · ${formatDate(game.date)}` : ""}</p>
          </div>
          {you !== null && <div className="flex shrink-0 items-start gap-4 text-right">
            {perf && <div title={`80% range ${perf.low} to ${perf.high}, from ${perf.moves} moves`}><div className="tnum text-[20px] font-semibold leading-none tracking-[-0.03em]">{perf.rating}</div><div className="mt-1 text-[11px] text-muted">performance</div></div>}
            <div><div className="tnum text-[20px] font-semibold leading-none tracking-[-0.03em]">{you.toFixed(0)}<span className="text-[12px] text-muted">%</span></div><div className="mt-1 text-[11px] text-muted">accuracy</div></div>
          </div>}
        </div>
        {analysed ? <div className="mt-3"><EvalGraph moves={moves} ply={ply} onSelect={goto} userIsWhite={userIsWhite} /></div> : (
          <div className="mt-3 rounded-[8px] bg-sunken p-4">
            <p className="text-[13.5px] text-muted">This game has not been analysed yet. You can step through the moves now; analysis adds move classes, accuracy and the best moves.</p>
            <Button variant="primary" className="mt-3" disabled={analyse.isPending || analyse.isSuccess} onClick={() => analyse.mutate({ ids: [game.id] })}><Sparkles size={15} /> {analyse.isSuccess ? "Analysing…" : "Analyse this game"}</Button>
            {analyse.isError && <p role="alert" className="mt-2 text-[12.5px] text-[var(--q-blunder)]">{(analyse.error as Error).message}</p>}
          </div>
        )}
        {clocks.length > 0 && <div className="mt-2"><TimeChart clocks={clocks} base={loaded.base ?? null} inc={loaded.inc ?? null} ply={ply} onSelect={goto} /><p className="mt-1 text-[11px] text-faint">Time per move: White above, Black below; orange is under a tenth of the clock.</p></div>}
      </Panel>

      <Panel className="min-h-[96px] p-4 text-[13.5px]">
        {retryPanel ?? (analysed ? <CoachCard fenBefore={ply > 0 ? fens[ply - 1] : fen} move={last} cpBefore={ply > 1 ? moves[ply - 2].cp : 20} next={next ? uciToSan(fen, next.best) : null} onTry={(ucis) => tryLine(ply - 1, ucis)}
          actions={<>
            <Button size="sm" variant="primary" disabled={moments.length === 0} onClick={() => jump(1)} title="Next key moment (N)"><SkipForward size={14} /> Next key moment</Button>
            <Button size="sm" disabled={mistakes.length === 0 || retryOn} onClick={onRetry}><RotateCcw size={14} /> Retry your mistakes{mistakes.length ? ` (${mistakes.length})` : ""}</Button>
          </>} />
          : <p className="text-muted">{last ? <><b className="text-text">{last.san}</b> was played. Analyse the game to see how good it was.</> : "Step through the game with the arrow keys."}</p>)}
      </Panel>

      <Panel className="flex min-h-[200px] flex-1 flex-col overflow-hidden">
        <Tabs.Root defaultValue="moves" className="flex min-h-0 flex-1 flex-col">
          <TabList className="px-2" aria-label="Review sections">
            {[["moves", "Moves"], ["summary", "Summary"], ["moments", "Key moments"], ["engine", "Engine"], ["explorer", "Explorer"]].filter(([v]) => analysed || ["moves", "engine", "explorer"].includes(v)).map(([v, l]) => (
              <TabTrigger key={v} value={v} className="!px-2 !text-[12.5px]">{l}</TabTrigger>
            ))}
          </TabList>
          <Tabs.Content value="moves" className={TAB_BODY + " p-2"}>
            {analysed && <label className="mb-1 flex cursor-pointer items-center justify-end gap-2 px-2 text-[12px] text-muted"><input type="checkbox" checked={showEvals} onChange={(e) => setShowEvals(e.target.checked)} className="accent-[var(--accent)]" /> Show evaluations</label>}
            <MoveList moves={moves} ply={ply} onSelect={goto} plain={!analysed} evals={showEvals} />
          </Tabs.Content>
          {analysed && <Tabs.Content value="summary" className={TAB_BODY}><Summary game={game} perf={loaded.perf} resultPerf={loaded.resultPerf} /></Tabs.Content>}
          {analysed && <Tabs.Content value="moments" className={TAB_BODY + " p-2"}>
            <div className="mb-1 flex justify-end px-1"><Segmented size="sm" label="Whose moments" value={who} onChange={setWho} options={[["all", "All"], ["mine", "Mine"], ["opp", "Opponent's"]]} /></div>
            {shown.length === 0 ? <p className="p-3 text-muted">Nothing to show here.</p> : shown.map((m) => (
              <button key={m.ply} onClick={() => goto(m.ply)} className="flex w-full items-center justify-between gap-3 rounded-[6px] px-3 py-2 text-left transition-colors hover:bg-surface-2 cursor-pointer">
                <span className="flex min-w-0 items-center gap-2"><ClassIcon cls={m.move.cls} size={16} /><span className="tnum text-faint">{Math.ceil(m.ply / 2)}{m.ply % 2 === 1 ? "." : "..."}</span> <b className="font-medium">{m.move.san}</b><span className="truncate text-[12.5px] text-muted">{m.label}</span></span>
                {m.kind === "mine-bad" && <span className="tnum shrink-0 text-[12.5px] text-muted">−{(m.move.loss * 100).toFixed(0)}%</span>}
              </button>
            ))}
          </Tabs.Content>}
          <Tabs.Content value="engine" className={TAB_BODY}><EngineTab enabled={engine.on} onToggle={engine.setOn} live={engine.live} multipv={engine.multipv} onMultipv={engine.setMultipv} onPlay={onPlay} /></Tabs.Content>
          <Tabs.Content value="explorer" className={TAB_BODY}><ExplorerTab fen={fenNow} active onPlay={onPlay} /></Tabs.Content>
        </Tabs.Root>
      </Panel>
    </aside>
  );
});
