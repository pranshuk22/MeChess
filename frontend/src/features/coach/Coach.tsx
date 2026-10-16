import { TabList, TabTrigger, Tabs } from "@/components/ui/Tabs";
import { Plus, Play } from "lucide-react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { useDrillStats, useGamesPage, type Drill } from "@/api/hooks";
import { Button } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/Misc";
import { PageHeader, Panel, PanelTitle } from "@/components/ui/Panel";
import { Endgames } from "./Endgames";
import { Openings } from "./Openings";
import { Practice } from "./Practice";
import { Steered } from "./Steered";
import { Weaknesses } from "./Weaknesses";

export function CoachPage() {
  const [sp] = useSearchParams();
  const tab = ["practice", "openings", "endgames", "steered", "weaknesses"].includes(sp.get("tab") ?? "") ? sp.get("tab")! : "practice";
  return (
    <div className="mx-auto max-w-[1180px] px-8 py-8 max-md:px-4">
      <PageHeader title="Coach" sub="Practice that comes from your own games." />
      <Tabs.Root defaultValue={tab}>
        <TabList className="mb-5" aria-label="Coach sections">
          {[["practice", "Practice"], ["openings", "Openings"], ["endgames", "Endgames"], ["steered", "Steered game"], ["weaknesses", "Weaknesses"]].map(([v, l]) => (
            <TabTrigger key={v} value={v}>{l}</TabTrigger>
          ))}
        </TabList>
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
  const last = useGamesPage({ analysed: true }, 1).data?.items[0];
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
  if (!stats) return <Skeleton className="h-48 rounded-[8px]" />;
  const max = Math.max(1, ...stats.boxes);
  return (
    <div className={stats.total > 0 ? "grid grid-cols-[minmax(0,1fr)_340px] gap-5 max-lg:grid-cols-1" : ""}>
      <Panel>
        {stats.total === 0 ? (
          <div className="p-6">
            <h2 className="text-[17px] font-semibold">Where to start</h2>
            <p className="mt-1 text-[13.5px] text-muted">Practice positions come from the moments in your own games where you gave away the most. Until there are some, here is what you can do now.</p>
            <div className="mt-4 grid grid-cols-3 gap-3 max-md:grid-cols-1">
              <div className="rounded-[8px] border border-border p-4"><b className="text-[14px]">Turn your mistakes into practice</b><p className="mt-1 text-[12.5px] text-muted">Adds the biggest mistake of each analysed game, to come back on a schedule.</p><Button className="mt-3" size="sm" variant="primary" onClick={refresh} disabled={busy}><Plus size={14} /> Add from my games</Button></div>
              <div className="rounded-[8px] border border-border p-4"><b className="text-[14px]">{last ? "Retry your last game" : "Review a game"}</b><p className="mt-1 text-[12.5px] text-muted">{last ? "Step through it with the coach card and retry each mistake on the board." : "Open a game from your library to see where points were lost."}</p><Link to={last ? `/review/${encodeURIComponent(last.id)}` : "/library"}><Button className="mt-3" size="sm">{last ? "Open it" : "Library"}</Button></Link></div>
              <div className="rounded-[8px] border border-border p-4"><b className="text-[14px]">Practise an opening</b><p className="mt-1 text-[12.5px] text-muted">The repertoire you already play, or a ready-made one from the opening library.</p><Link to="/coach?tab=openings"><Button className="mt-3" size="sm">Openings</Button></Link></div>
            </div>
            {msg && <p role="status" className="mt-4 text-[13px] text-muted">{msg}</p>}
          </div>
        ) : (
          <div className="p-6">
            {result && <p className="mb-4 rounded-[6px] bg-accent-soft px-4 py-2.5 text-[13.5px] text-accent">Done: you found {result.found} of {result.total} without a hint on the first try.</p>}
            <div className="flex items-end justify-between gap-4">
              <div><div className="tnum font-display text-[40px] font-semibold leading-none tracking-[-0.05em]">{stats.due}</div><div className="mt-1 text-[13.5px] text-muted">{stats.due === 1 ? "position" : "positions"} due of {stats.total}</div></div>
              <Button variant="primary" size="lg" onClick={start} disabled={busy || stats.due === 0}><Play size={16} /> Start practice</Button>
            </div>
            {msg && <p role="status" className="mt-4 text-[13px] text-muted">{msg}</p>}
          </div>
        )}
        {false && <p role="status" className="px-6 pb-5 text-center text-[13px] text-muted">{msg}</p>}
      </Panel>
      {stats.total > 0 && <Panel>
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
      </Panel>}
    </div>
  );
}
