import { ArrowRight, Check, CircleAlert, Minus } from "lucide-react";
import { Link } from "react-router-dom";
import { useGames } from "@/api/games";
import { Board } from "@/board/Board";
import { MiniEval } from "@/components/MiniEval";
import { Button } from "@/components/ui/Button";
import { Panel, PanelTitle } from "@/components/ui/Panel";
import { myAccuracy, opponent, outcome } from "@/lib/format";
import { fensFromUci } from "@/lib/game";
import { BAD } from "@/lib/types";
import { useUi } from "@/state/ui";
import { useMemo } from "react";

const CHECKS: [string, "ok" | "todo" | "off", string][] = [
  ["Stockfish engine", "ok", "found"],
  ["Games imported", "ok", "12 sample games"],
  ["Games analysed", "ok", "12 of 12"],
  ["Opening explorer", "off", "not built: optional"],
  ["Endgame tablebases", "off", "not found: optional"],
  ["Your personal model", "todo", "not trained yet"],
];

export function HomePage() {
  const { data: games = [] } = useGames();
  const pieceSet = useUi((s) => s.pieceSet)();
  const featured = games[3] ?? games[0];
  const mistakes = featured ? featured.moves.filter((m, i) => (i % 2 === 0) === (featured.user === "white") && BAD.includes(m.cls) && m.loss >= 0.1).length : 0;
  const fen = useMemo(() => (featured ? fensFromUci(featured.moves.slice(0, 22).map((m) => m.uci)).at(-1)! : ""), [featured]);
  return (
    <div className="mx-auto grid max-w-[1120px] grid-cols-[minmax(0,1fr)_340px] gap-5 p-6 max-lg:grid-cols-1 max-md:p-3">
      <div className="space-y-5">
        {featured && (
          <Panel className="grid grid-cols-[200px_1fr] gap-5 p-5 max-sm:grid-cols-1">
            <div className="max-sm:w-48"><Board fen={fen} orientation={featured.user} showCoords={false} pieceSet={pieceSet} /></div>
            <div className="flex flex-col">
              <div className="text-[12px] font-semibold uppercase tracking-wide text-muted">Next step</div>
              <h2 className="mt-1 text-[19px] font-semibold leading-tight">Learn from your last game</h2>
              <p className="mt-2 text-muted">You gave away points in {mistakes} moves against {opponent(featured).name}. Replay them one by one, find the better move, and see why it is better.</p>
              <div className="mt-auto flex gap-2 pt-4">
                <Link to={`/review/${featured.id}`}><Button variant="primary">Review the game <ArrowRight size={15} /></Button></Link>
                <Link to="/library"><Button variant="ghost">All games</Button></Link>
              </div>
            </div>
          </Panel>
        )}
        <Panel>
          <PanelTitle right={<Link to="/library" className="text-[12.5px] text-accent hover:underline">See all</Link>}>Recent games</PanelTitle>
          <div className="pb-2">
            {games.slice(0, 6).map((g) => (
              <Link key={g.id} to={`/review/${g.id}`} className="grid grid-cols-[52px_1fr_auto_100px] items-center gap-3 px-4 py-2.5 hover:bg-surface-2 max-sm:grid-cols-[52px_1fr_auto]">
                <span className="text-[12.5px] font-semibold" style={{ color: { win: "var(--q-best)", loss: "var(--q-blunder)", draw: "var(--faint)" }[outcome(g)] }}>{{ win: "Win", loss: "Loss", draw: "Draw" }[outcome(g)]}</span>
                <span className="min-w-0 truncate"><b className="font-medium">{opponent(g).name}</b> <span className="text-muted">· {g.title ?? g.opening}</span></span>
                <span className="tnum text-[12.5px] text-muted">{myAccuracy(g).toFixed(0)}%</span>
                <span className="max-sm:hidden"><MiniEval moves={g.moves} /></span>
              </Link>
            ))}
          </div>
        </Panel>
      </div>

      <div className="space-y-5">
        <Panel>
          <PanelTitle>Practice due</PanelTitle>
          <div className="px-4 pb-4">
            <p className="text-[13.5px] text-muted">Positions from your own mistakes come back here after a day, then after longer gaps once you get them right.</p>
            <Link to="/coach"><Button className="mt-3 w-full">Start 5 positions</Button></Link>
          </div>
        </Panel>
        <Panel>
          <PanelTitle>Your workspace</PanelTitle>
          <ul className="px-4 pb-3">
            {CHECKS.map(([name, state, note]) => (
              <li key={name} className="flex items-center gap-2.5 border-t border-border/60 py-2 first:border-t-0 text-[13.5px]">
                {state === "ok" ? <Check size={16} className="text-[var(--q-best)]" /> : state === "todo" ? <CircleAlert size={16} className="text-[var(--q-inaccuracy)]" /> : <Minus size={16} className="text-faint" />}
                <span className="flex-1">{name}</span><span className="text-[12.5px] text-muted">{note}</span>
              </li>
            ))}
          </ul>
        </Panel>
      </div>
    </div>
  );
}
