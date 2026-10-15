import { PIECE_SETS } from "@/board/pieces";
import { Board } from "@/board/Board";
import { Panel, PanelTitle } from "@/components/ui/Panel";
import { START_FEN } from "@/lib/game";
import { useUi } from "@/state/ui";

export function SettingsPage() {
  const { theme, toggleTheme, pieceSetId, setPieceSet, showCoords, setShowCoords } = useUi();
  const pieceSet = useUi((s) => s.pieceSet)();
  return (
    <div className="mx-auto grid max-w-[900px] grid-cols-[1fr_260px] gap-5 p-6 max-md:grid-cols-1 max-md:p-3">
      <div className="space-y-5">
        <Panel>
          <PanelTitle>Appearance</PanelTitle>
          <div className="divide-y divide-border/60 px-4 pb-2">
            <Row label="Theme" hint="Also in the top bar."><button onClick={toggleTheme} className="h-8 rounded-md border border-border bg-surface-2 px-3 text-[13px] cursor-pointer">{theme === "dark" ? "Dark" : "Light"}: switch</button></Row>
            <Row label="Board coordinates" hint="Letters and numbers on the board edge."><input type="checkbox" checked={showCoords} onChange={(e) => setShowCoords(e.target.checked)} className="h-4 w-4 accent-[var(--accent)]" /></Row>
            <Row label="Pieces" hint="More sets, including your own folder of images, come with the backend.">
              <select value={pieceSetId} onChange={(e) => setPieceSet(e.target.value)} className="h-8 rounded-md border border-border bg-surface px-2 text-[13px]">{PIECE_SETS.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select>
            </Row>
          </div>
        </Panel>
        <Panel>
          <PanelTitle>Privacy</PanelTitle>
          <p className="px-4 pb-4 text-[13.5px] text-muted">MeChess runs on your computer. Your games, analyses and training data stay in your data folder. The app makes no requests to other websites except the ones you start (importing your games).</p>
        </Panel>
      </div>
      <Panel className="self-start p-3"><Board fen={START_FEN} showCoords={showCoords} pieceSet={pieceSet} /></Panel>
    </div>
  );
}

function Row({ label, hint, children }: { label: string; hint: string; children: React.ReactNode }) {
  return <div className="flex items-center justify-between gap-4 py-3"><div><div className="text-[13.5px] font-medium">{label}</div><div className="text-[12.5px] text-muted">{hint}</div></div>{children}</div>;
}
