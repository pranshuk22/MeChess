import { Compass } from "lucide-react";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "@/api/client";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Misc";
import { Panel, PanelTitle } from "@/components/ui/Panel";
import { Segmented } from "@/components/ui/Segmented";
import { GuidedBoard, Note, type GuidedView } from "./guided";

interface Foci { foci: { id: string; title: string; tip: string; suggested: string | null }[] }
interface View extends GuidedView { result: string | null; plies: number }
interface Done { focus: Record<string, unknown>; focus_lines: string[]; result: string; gameId: string; drillsAdded: number }

/** A steered game: the opponent plays sound moves but leans toward the situations you want to practise; afterwards you see how you did in exactly those. */
export function Steered() {
  const foci = useQuery({ queryKey: ["foci"], queryFn: () => api<Foci>("/api/coach/steer/foci") }).data?.foci ?? [];
  const [chosen, setChosen] = useState<Record<string, boolean>>({});
  const [colour, setColour] = useState("white");
  const [s, setS] = useState<{ session: string; view: View; tips: string[] } | null>(null);
  const [done, setDone] = useState<Done | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const guard = async (fn: () => Promise<void>) => { setBusy(true); setError(""); try { await fn(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); } };
  const picked = Object.entries(chosen).filter(([, v]) => v).map(([k]) => k);
  const start = () => guard(async () => { setDone(null); setS(await api("/api/coach/steer/start", { method: "POST", json: { colour, foci: Object.fromEntries(picked.map((k) => [k, 1])) } })); });
  const onMove = (from: string, to: string, promo?: string) => guard(async () => { const r = await api<{ view: View }>(`/api/coach/steer/${s!.session}/move`, { method: "POST", json: { uci: from + to + (promo ?? "") } }); setS({ ...s!, view: r.view }); });
  const finish = () => guard(async () => { setDone(await api<Done>(`/api/coach/steer/${s!.session}/finish`, { method: "POST" })); });

  if (s && !done) {
    return (
      <div className="grid grid-cols-[minmax(0,1fr)_360px] gap-6 max-lg:grid-cols-1">
        <GuidedBoard view={s.view} busy={busy} onMove={onMove} />
        <div className="space-y-3">
          <Panel className="p-5">
            <h2 className="text-[17px] font-semibold">{s.view.over ? "Game over" : "Play your game"}</h2>
            <ul className="mt-2 space-y-1 text-[13px] text-muted">{s.tips.map((t) => <li key={t}>• {t}</li>)}</ul>
            <div className="mt-4 flex gap-2"><Button variant="primary" onClick={finish} disabled={busy || s.view.plies === 0}>{busy ? "Analysing…" : "Finish and see how it went"}</Button><Button variant="ghost" onClick={() => setS(null)}>Cancel</Button></div>
          </Panel>
          {error && <p role="alert" className="text-[13px] text-[var(--q-blunder)]">{error}</p>}
        </div>
      </div>
    );
  }
  if (s && done) {
    return (
      <Panel className="p-6">
        <h2 className="text-[18px] font-semibold">How it went</h2>
        <ul className="mt-3 space-y-2">{done.focus_lines.map((l, i) => <li key={i}><Note>{l}</Note></li>)}</ul>
        <p className="mt-3 text-[13px] text-muted">{done.drillsAdded ? `${done.drillsAdded} of your mistakes were added to your practice positions.` : "No new practice positions from this game."}</p>
        <div className="mt-4 flex gap-2"><Link to={`/review/${encodeURIComponent(done.gameId)}`}><Button variant="primary">Review the game</Button></Link><Button onClick={() => { setS(null); setDone(null); }}>New game</Button></div>
      </Panel>
    );
  }
  return (
    <Panel>
      <PanelTitle sub="Choose what to practise. The opponent keeps playing good moves, but leans toward those situations.">Steered game</PanelTitle>
      <div className="space-y-4 px-5 pb-5">
        <div className="grid grid-cols-2 gap-3 max-sm:grid-cols-1" role="group" aria-label="Focus">
          {foci.map((f) => (
            <label key={f.id} className={`cursor-pointer rounded-[8px] border p-3.5 transition-colors ${chosen[f.id] ? "border-accent bg-accent-soft" : "border-border hover:bg-surface-2"}`}>
              <span className="flex items-center gap-2"><input type="checkbox" checked={!!chosen[f.id]} onChange={(e) => setChosen({ ...chosen, [f.id]: e.target.checked })} className="accent-[var(--accent)]" /><b className="font-medium">{f.title}</b>{f.suggested && <Badge tone="accent">suggested for you</Badge>}</span>
              <span className="mt-1 block pl-6 text-[12.5px] text-muted">{f.tip}</span>
              {f.suggested && <span className="mt-1 block pl-6 text-[12px] text-faint">{f.suggested}</span>}
            </label>
          ))}
        </div>
        <div><div className="mb-1.5 text-[12.5px] font-medium">You play</div><Segmented label="Colour" value={colour} onChange={setColour} options={[["white", "White"], ["black", "Black"]]} /></div>
        {error && <p role="alert" className="text-[13px] text-[var(--q-blunder)]">{error}</p>}
        <Button variant="primary" size="lg" disabled={!picked.length || busy} onClick={start}><Compass size={16} /> Start the game</Button>
      </div>
    </Panel>
  );
}
