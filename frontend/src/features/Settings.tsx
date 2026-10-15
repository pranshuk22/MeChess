import { BoardAndPieces, SiteAppearance } from "@/components/Appearance";
import { Board } from "@/board/Board";
import { pieceSets } from "@/board/pieces";
import { Panel, PanelTitle } from "@/components/ui/Panel";
import { START_FEN } from "@/lib/game";
import { useUi } from "@/state/ui";

export function SettingsPage() {
  const { showCoords, setShowCoords } = useUi();
  return (
    <div className="mx-auto grid max-w-[980px] grid-cols-[1fr_300px] gap-5 p-6 max-md:grid-cols-1 max-md:p-3">
      <div className="space-y-5">
        <Panel>
          <PanelTitle>Website</PanelTitle>
          <div className="px-4 pb-4"><SiteAppearance /></div>
        </Panel>
        <Panel>
          <PanelTitle>Board and pieces</PanelTitle>
          <div className="px-4 pb-4">
            <BoardAndPieces />
            <label className="mt-4 flex items-center justify-between gap-4 border-t border-border/60 pt-3 text-[13.5px]"><span><b className="font-medium">Board coordinates</b><span className="block text-[12.5px] text-muted">Letters and numbers on the board edge.</span></span><input type="checkbox" checked={showCoords} onChange={(e) => setShowCoords(e.target.checked)} className="h-4 w-4 accent-[var(--accent)]" /></label>
          </div>
        </Panel>
        <Panel>
          <PanelTitle>Piece set credits</PanelTitle>
          <ul className="space-y-1 px-4 pb-4 text-[13px] text-muted">{pieceSets().map((s) => <li key={s.id}><b className="font-medium text-text">{s.name}</b>: {s.author}, {s.licence}</li>)}</ul>
        </Panel>
        <Panel>
          <PanelTitle>Privacy</PanelTitle>
          <p className="px-4 pb-4 text-[13.5px] text-muted">MeChess runs on your computer. Your games, analyses and training data stay in your data folder. The app makes no requests to other websites except the ones you start (importing your games).</p>
        </Panel>
      </div>
      <Panel className="self-start p-3 max-md:hidden"><Board fen={START_FEN} showCoords={showCoords} /></Panel>
    </div>
  );
}
