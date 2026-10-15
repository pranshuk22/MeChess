import * as Tabs from "@radix-ui/react-tabs";
import { GraduationCap, Plus, Play } from "lucide-react";
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { useDrillStats, type Drill } from "@/api/hooks";
import { Button } from "@/components/ui/Button";
import { EmptyState, Skeleton } from "@/components/ui/Misc";
import { PageHeader, Panel, PanelTitle } from "@/components/ui/Panel";
import { Endgames } from "./Endgames";
import { Openings } from "./Openings";
import { Practice } from "./Practice";
import { Steered } from "./Steered";
import { Weaknesses } from "./Weaknesses";

export function CoachPage() {
  return (
    <div className="mx-auto max-w-[1180px] px-8 py-8 max-md:px-4">
      <PageHeader title="Coach" sub="Practice that comes from your own games." />
      <Tabs.Root defaultValue="practice">
        <Tabs.List className="mb-5 inline-flex rounded-[9px] bg-sunken p-0.5" aria-label="Coach sections">
          {[["practice", "Practice"], ["openings", "Openings"], ["endgames", "Endgames"], ["steered", "Steered game"], ["weaknesses", "Weaknesses"]].map(([v, l]) => (
            <Tabs.Trigger key={v} value={v} className="h-8 rounded-[7px] px-4 text-[13px] font-medium text-muted data-[state=active]:bg-surface data-[state=active]:text-text data-[state=active]:shadow-[var(--shadow-sm)] cursor-pointer">{l}</Tabs.Trigger>
          ))}
        </Tabs.List>
        <Tabs.Content value="practice" className="outline-none"><PracticeHome /></Tabs.Content>
        <Tabs.Content value="openings" className="outline-none"><Openings /></Tabs.Content>
        <Tabs.Content value="endgames" className="outline-none"><Endgames /></Tabs.Content>
        <Tabs.Content value="steered" className="outline-none"><Steered /></Tabs.Content>
        <Tabs.Content value="weaknesses" className="outline-none"><Weaknesses /></Tabs.Content>
      </Tabs.Root>
    </div>
  );
}

function PracticeHome() {
  const stats = useDrillStats().data;
  const qc = useQueryClient();
  const [session, setSession] = useState<Drill[] | null>(null);
  const [result, setResult] = useState<{ found: number; total: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const start = async () => {
    setBusy(true); setMsg("");
    try { const r = await api<{ items: Drill[] }>("/api/coach/drills/next?limit=5"); if (r.items.length) { setSession(r.items); setResult(null); } else setMsg("Nothing is due right now. Positions come back on their schedule."); }
    catch (e) { setMsg((e as Error).message); } finally { setBusy(false); }
  };
  const refresh = async () => {
    setBusy(true);
    try { const r = await api<{ added: number }>("/api/coach/drills/refresh", { method: "POST" }); setMsg(r.added ? `${r.added} new positions from your games.` : "No new positions: every analysed game is already in."); qc.invalidateQueries({ queryKey: ["drills"] }); }
    catch (e) { setMsg((e as Error).message); } finally { setBusy(false); }
  };
  if (session) return <Practice items={session} onFinish={(found, total) => { setSession(null); setResult({ found, total }); qc.invalidateQueries({ queryKey: ["drills"] }); }} />;
  if (!stats) return <Skeleton className="h-48 rounded-[12px]" />;
  const max = Math.max(1, ...stats.boxes);
  return (
    <div className="grid grid-cols-[minmax(0,1fr)_340px] gap-5 max-lg:grid-cols-1">
      <Panel>
        {stats.total === 0 ? (
          <EmptyState icon={GraduationCap} title="No practice positions yet" text="They come from your own analysed games: the moments where you gave away the most. Analyse your games, then add them here."
            action={<Button variant="primary" onClick={refresh} disabled={busy}><Plus size={15} /> Add from my games</Button>} />
        ) : (
          <div className="p-6">
            {result && <p className="mb-4 rounded-[9px] bg-accent-soft px-4 py-2.5 text-[13.5px] text-accent">Done: you found {result.found} of {result.total} without a hint on the first try.</p>}
            <div className="flex items-end justify-between gap-4">
              <div><div className="tnum font-display text-[40px] font-semibold leading-none tracking-[-0.05em]">{stats.due}</div><div className="mt-1 text-[13.5px] text-muted">{stats.due === 1 ? "position" : "positions"} due of {stats.total}</div></div>
              <Button variant="primary" size="lg" onClick={start} disabled={busy || stats.due === 0}><Play size={16} /> Start practice</Button>
            </div>
            {msg && <p role="status" className="mt-4 text-[13px] text-muted">{msg}</p>}
          </div>
        )}
        {stats.total === 0 && msg && <p role="status" className="px-6 pb-5 text-center text-[13px] text-muted">{msg}</p>}
      </Panel>
      <Panel>
        <PanelTitle sub="Each position moves up a box when you find the move at once, and back to the start when you do not">Your positions by box</PanelTitle>
        <div className="space-y-2.5 px-5 pb-5 pt-1">
          {stats.boxes.map((n, b) => (
            <div key={b} className="grid grid-cols-[88px_1fr_28px] items-center gap-3 text-[12.5px]">
              <span className="text-muted">{["New / missed", "1 day", "3 days", "1 week", "2 weeks", "5 weeks"][b]}</span>
              <span className="h-2 overflow-hidden rounded-full bg-sunken"><span className="block h-full rounded-full bg-accent" style={{ width: `${(100 * n) / max}%` }} /></span>
              <span className="tnum text-right">{n}</span>
            </div>
          ))}
          <Button variant="ghost" size="sm" className="mt-2" onClick={refresh} disabled={busy}><Plus size={14} /> Add from my games</Button>
        </div>
      </Panel>
    </div>
  );
}
