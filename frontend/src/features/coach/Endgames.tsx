import { Lightbulb, Shapes } from "lucide-react";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/Misc";
import { Panel, PanelTitle } from "@/components/ui/Panel";
import { GuidedBoard, Note, type GuidedView } from "./guided";

interface View extends GuidedView { errors: number; goal: string; tip: string; line: string[]; report: { success: boolean; message: string } | null }
interface Theme { id: string; title: string; available: boolean }

/** Endgame practice judged by tablebases: every move you play is checked against perfect play. */
export function Endgames() {
  const themes = useQuery({ queryKey: ["endgames"], queryFn: () => api<{ themes: Theme[] }>("/api/coach/endgames") }).data?.themes;
  const status = useQuery({ queryKey: ["coach-status"], queryFn: () => api<{ explorer: boolean; tablebase: boolean }>("/api/coach/status") }).data;
  const [s, setS] = useState<{ session: string; view: View } | null>(null);
  const [theme, setTheme] = useState("");
  const [note, setNote] = useState<{ tone: "info" | "bad" | "good"; text: string } | null>(null);
  const [hints, setHints] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const guard = async (fn: () => Promise<void>) => { setBusy(true); setError(""); try { await fn(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); } };
  const start = (id: string) => guard(async () => { setTheme(id); setS(await api(`/api/coach/endgames/start`, { method: "POST", json: { theme: id } })); setNote(null); setHints([]); });
  const onMove = (from: string, to: string, promo?: string) => guard(async () => {
    const r = await api<{ verdict?: string; message?: string; view: View }>(`/api/coach/endgames/${s!.session}/move`, { method: "POST", json: { uci: from + to + (promo ?? "") } });
    setS({ ...s!, view: r.view });
    setNote(r.verdict === "throws it away" ? { tone: "bad", text: r.message! } : null);
  });
  const hint = () => guard(async () => { const level = Math.min(3, hints.length + 1); const r = await api<{ hint: string }>(`/api/coach/endgames/${s!.session}/hint`, { method: "POST", json: { level } }); setHints([...hints, r.hint]); });

  if (status && !status.tablebase) return <Panel><EmptyState icon={Shapes} title="No endgame tablebases found" text="Endgame practice checks every move against Syzygy tablebases. Download the 3 to 5 piece files (about 1 GB) into a folder named syzygy in your data folder." /></Panel>;
  if (s) {
    const v = s.view;
    return (
      <div className="grid grid-cols-[minmax(0,1fr)_360px] gap-6 max-lg:grid-cols-1">
        <GuidedBoard view={v} busy={busy} onMove={onMove} />
        <div className="space-y-3">
          <Panel className="p-5">
            <h2 className="text-[17px] font-semibold">{v.goal}</h2>
            <p className="mt-1 text-[13.5px] text-muted">{v.tip}</p>
            <p className="mt-2 text-[12.5px] text-muted">Moves that gave the position away: <b className="text-text">{v.errors}</b></p>
            {note && <div className="mt-3"><Note tone={note.tone}>{note.text}</Note></div>}
            {hints.map((h, i) => <p key={i} className="mt-3 flex gap-2 rounded-[9px] bg-sunken px-3 py-2 text-[13px]"><Lightbulb size={15} className="mt-0.5 shrink-0 text-[var(--q-inaccuracy)]" />{h}</p>)}
            {v.report && <div className="mt-3"><Note tone={v.report.success ? "good" : "bad"}>{v.report.message}</Note></div>}
            <div className="mt-4 flex flex-wrap gap-2">{!v.over && <Button size="sm" onClick={hint} disabled={hints.length >= 3 || busy}><Lightbulb size={14} /> Hint</Button>}<Button size="sm" onClick={() => start(theme)}>New position</Button><Button size="sm" variant="ghost" onClick={() => setS(null)}>Back</Button></div>
          </Panel>
          {error && <p role="alert" className="text-[13px] text-[var(--q-blunder)]">{error}</p>}
        </div>
      </div>
    );
  }
  return (
    <Panel>
      <PanelTitle sub="Pick a theme: you get a random position and the tablebase tells you whether each move keeps the result.">Endgame practice</PanelTitle>
      <div className="grid grid-cols-3 gap-3 px-5 pb-5 max-md:grid-cols-1">
        {themes?.map((t) => (
          <button key={t.id} disabled={!t.available || busy} onClick={() => start(t.id)} className="rounded-[10px] border border-border p-4 text-left transition-colors hover:bg-surface-2 disabled:opacity-50 cursor-pointer">
            <div className="font-medium">{t.title}</div><div className="mt-1 text-[12.5px] text-muted">{t.available ? "Start" : "Tablebase files for this theme are missing"}</div>
          </button>
        ))}
      </div>
      {error && <p role="alert" className="px-5 pb-4 text-[13px] text-[var(--q-blunder)]">{error}</p>}
    </Panel>
  );
}
