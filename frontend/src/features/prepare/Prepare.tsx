import { Crosshair, Plus, Trash2, X } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { useAccounts } from "@/api/hooks";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Input, Label, Select } from "@/components/ui/Field";
import { Badge, EmptyState, Progress, Skeleton } from "@/components/ui/Misc";
import { PageHeader, Panel, PanelTitle } from "@/components/ui/Panel";
import { formatDate } from "@/lib/format";
import { ReportView } from "./Report";
import type { PrepDetail, PrepRow } from "./types";

const DEPTHS = [
  { id: "quick", title: "Quick", text: "Their openings only: every game's first 12 moves. A few minutes." },
  { id: "standard", title: "Standard", text: "Openings, plus their 40 latest games analysed move by move for the middlegame and the endgame. Some tens of minutes." },
  { id: "deep", title: "Deep", text: "Openings, plus their 120 latest games in full, and a bigger search for the plan. An hour or more." },
] as const;
const SPEEDS = ["bullet", "blitz", "rapid", "classical"] as const;
const SITES = { lichess: "Lichess", chesscom: "Chess.com" } as const;

export function PreparePage() {
  const { id } = useParams();
  return id ? <PrepView id={id} /> : <PrepHome />;
}

function PrepHome() {
  const nav = useNavigate(), qc = useQueryClient();
  const accounts = useAccounts().data;
  const list = useQuery({ queryKey: ["preps"], queryFn: () => api<PrepRow[]>("/api/prep"), refetchInterval: (q) => (q.state.data?.some((p) => p.status === "running") ? 2500 : false) });
  const [handles, setHandles] = useState([{ site: "lichess", name: "" }]);
  const [depth, setDepth] = useState<string>("standard");
  const [speeds, setSpeeds] = useState<string[]>(["blitz", "rapid", "classical"]);
  const [maxGames, setMaxGames] = useState("300");
  const [rated, setRated] = useState(true);
  const [pgn, setPgn] = useState("");
  const [usePgn, setUsePgn] = useState(false);
  const [error, setError] = useState("");
  const [del, setDel] = useState<PrepRow | null>(null);
  const start = useMutation({
    mutationFn: () => api<{ id: string }>("/api/prep", { method: "POST", json: { handles: handles.filter((h) => h.name.trim()).map((h) => ({ site: h.site, name: h.name.trim() })), depth, speeds, max_games: Number(maxGames), rated_only: rated, pgn: usePgn ? pgn : null } }),
    onSuccess: (r) => { qc.invalidateQueries({ queryKey: ["preps"] }); nav(`/prepare/${r.id}`); },
    onError: (e) => setError((e as Error).message),
  });
  const remove = useMutation({ mutationFn: (id: string) => api(`/api/prep/${id}`, { method: "DELETE" }), onSuccess: () => qc.invalidateQueries({ queryKey: ["preps"] }) });
  const mine = [accounts?.lichess, accounts?.chesscom].filter(Boolean) as string[];
  const ok = handles.some((h) => h.name.trim().length >= 2) && speeds.length > 0 && (!usePgn || pgn.trim().length > 0);

  return (
    <div className="mx-auto max-w-[980px] px-8 py-8 max-md:px-4">
      <PageHeader title="Prepare against an opponent" sub="Find where they are weak, and which openings to play against them. Everything is worked out on this computer from their public games." />
      <Panel className="p-6 max-md:p-4">
        <form onSubmit={(e) => { e.preventDefault(); setError(""); start.mutate(); }} className="space-y-6">
          <div>
            <Label hint="Their public user name. If they play on more than one account, add each.">Opponent</Label>
            <div className="space-y-2">
              {handles.map((h, i) => (
                <div key={i} className="flex gap-2">
                  <Select aria-label="Site" className="!w-[130px] shrink-0" value={h.site} onChange={(e) => setHandles(handles.map((x, k) => (k === i ? { ...x, site: e.target.value } : x)))}>{Object.entries(SITES).map(([v, l]) => <option key={v} value={v}>{l}</option>)}</Select>
                  <Input aria-label="Opponent's user name" placeholder="their user name" value={h.name} onChange={(e) => setHandles(handles.map((x, k) => (k === i ? { ...x, name: e.target.value } : x)))} autoComplete="off" />
                  {handles.length > 1 && <Button type="button" variant="ghost" aria-label="Remove this account" onClick={() => setHandles(handles.filter((_, k) => k !== i))}><X size={15} /></Button>}
                </div>
              ))}
            </div>
            {handles.length < 4 && <Button type="button" variant="ghost" size="sm" className="mt-2" onClick={() => setHandles([...handles, { site: "lichess", name: "" }])}><Plus size={14} /> Another account</Button>}
            {!!mine.length && <p className="mt-2 text-[12px] text-muted">Your own games ({mine.join(", ")}) are used to see what you play and how you score.</p>}
          </div>

          <div>
            <Label>How thorough</Label>
            <div className="grid grid-cols-3 gap-3 max-md:grid-cols-1" role="radiogroup" aria-label="How thorough">
              {DEPTHS.map((d) => (
                <button key={d.id} type="button" role="radio" aria-checked={depth === d.id} onClick={() => setDepth(d.id)}
                  className={"cursor-pointer rounded-[8px] border p-3.5 text-left transition-colors " + (depth === d.id ? "border-accent bg-accent-soft" : "border-border bg-surface hover:border-[var(--border-strong)]")}>
                  <div className="text-[14px] font-semibold">{d.title}</div>
                  <div className="mt-1 text-[12.5px] text-muted">{d.text}</div>
                </button>
              ))}
            </div>
          </div>

          <div className="grid grid-cols-[1fr_auto] items-start gap-6 max-md:grid-cols-1">
            <div>
              <Label>Speeds to look at</Label>
              <div className="flex flex-wrap gap-2">
                {SPEEDS.map((s) => (
                  <label key={s} className={"inline-flex cursor-pointer items-center gap-2 rounded-[6px] border px-3 py-1.5 text-[13px] capitalize " + (speeds.includes(s) ? "border-accent bg-accent-soft" : "border-border")}>
                    <input type="checkbox" className="accent-[var(--accent)]" checked={speeds.includes(s)} onChange={(e) => setSpeeds(e.target.checked ? [...speeds, s] : speeds.filter((x) => x !== s))} />{s}
                  </label>
                ))}
              </div>
              <label className="mt-3 flex items-center gap-2 text-[13px]"><input type="checkbox" className="accent-[var(--accent)]" checked={rated} onChange={(e) => setRated(e.target.checked)} /> Rated games only</label>
            </div>
            <div className="w-[160px] max-md:w-full">
              <Label hint="The newest ones">Games to read</Label>
              <Select aria-label="Games to read" value={maxGames} onChange={(e) => setMaxGames(e.target.value)}>{["100", "200", "300", "600", "1000"].map((n) => <option key={n}>{n}</option>)}</Select>
            </div>
          </div>

          <div>
            <button type="button" className="cursor-pointer text-[13px] font-medium text-accent hover:underline" onClick={() => setUsePgn(!usePgn)}>{usePgn ? "Read their games from the sites instead" : "Or paste a PGN of their games"}</button>
            {usePgn && <div className="mt-2"><textarea aria-label="PGN of the opponent's games" value={pgn} onChange={(e) => setPgn(e.target.value)} rows={5} placeholder="Paste games here; the user name above says which player is the opponent." className="w-full rounded-[6px] border border-border bg-surface p-3 font-mono text-[12.5px] outline-none focus:border-accent" /></div>}
          </div>

          {error && <p role="alert" className="text-[13px] text-[var(--q-blunder)]">{error}</p>}
          <div className="flex items-center gap-3"><Button type="submit" variant="primary" size="lg" disabled={!ok || start.isPending}><Crosshair size={16} /> {start.isPending ? "Starting…" : "Prepare"}</Button>
            <span className="text-[12.5px] text-muted">Only public games are read, one request at a time, no passwords.</span></div>
        </form>
      </Panel>

      <div className="mt-8">
        <h2 className="mb-3 text-[15px] font-semibold">Your preparations</h2>
        {list.isLoading ? <Skeleton className="h-20" /> : !list.data?.length ? <Panel><EmptyState icon={Crosshair} title="Nothing prepared yet" text="Enter an opponent's name above. The report stays here, and can be refreshed with their newest games before you play them again." /></Panel> : (
          <div className="grid gap-3">
            {list.data.map((p) => (
              <Panel key={p.id} className="flex items-center gap-4 p-4 max-md:flex-wrap">
                <Link to={`/prepare/${p.id}`} className="min-w-0 flex-1">
                  <div className="truncate text-[14.5px] font-semibold">{p.handles.map((h) => h.name).join(", ")}</div>
                  <div className="mt-0.5 text-[12.5px] text-muted">{p.games ? `${p.games.toLocaleString()} games` : "…"}{p.rating ? ` · rated ${p.rating}` : ""}{p.updatedAt ? ` · ${formatDate(p.updatedAt.slice(0, 10))}` : ""}</div>
                </Link>
                <Badge tone={p.status === "done" ? "good" : p.status === "failed" ? "bad" : "accent"}>{p.status === "done" ? "Ready" : p.status === "failed" ? "Failed" : "Working…"}</Badge>
                <Button variant="ghost" size="sm" aria-label={`Delete the preparation against ${p.handles.map((h) => h.name).join(", ")}`} onClick={() => setDel(p)}><Trash2 size={15} /></Button>
              </Panel>
            ))}
          </div>
        )}
      </div>
      <ConfirmDialog open={!!del} onOpenChange={(o) => !o && setDel(null)} title="Delete this preparation?" text="The report and the opponent's games kept for it are removed from this computer. Your own games are not touched." confirm="Delete" onConfirm={() => del && remove.mutate(del.id)} />
    </div>
  );
}

function PrepView({ id }: { id: string }) {
  const qc = useQueryClient(), nav = useNavigate();
  const q = useQuery({ queryKey: ["prep", id], queryFn: () => api<PrepDetail>(`/api/prep/${id}`), refetchInterval: (q) => (q.state.data?.status === "running" ? 1500 : false) });
  const cancel = useMutation({ mutationFn: (job: string) => api(`/api/jobs/${job}/cancel`, { method: "POST" }), onSuccess: () => qc.invalidateQueries({ queryKey: ["prep", id] }) });
  const refresh = useMutation({ mutationFn: () => api(`/api/prep/${id}/refresh`, { method: "POST" }), onSuccess: () => qc.invalidateQueries({ queryKey: ["prep", id] }) });
  const [del, setDel] = useState(false);
  const remove = useMutation({ mutationFn: () => api(`/api/prep/${id}`, { method: "DELETE" }), onSuccess: () => { qc.invalidateQueries({ queryKey: ["preps"] }); nav("/prepare"); } });
  const p = q.data;
  if (q.isError) return <div className="mx-auto max-w-[760px] px-8 py-8"><Panel><EmptyState icon={Crosshair} title="That preparation does not exist" action={<Link to="/prepare"><Button>Back</Button></Link>} /></Panel></div>;
  if (!p) return <div className="mx-auto max-w-[1180px] px-8 py-8"><Skeleton className="h-40" /></div>;
  const names = p.handles.map((h) => h.name).join(", ");
  return (
    <div className="mx-auto max-w-[1180px] px-8 py-8 max-md:px-4">
      <PageHeader title={<>Preparing against <span className="font-display">{names}</span></>} sub={p.report ? `${p.report.opponent.games.toLocaleString()} games${p.rating ? ` · rated ${p.rating}` : ""}` : undefined}
        actions={<>
          <Link to="/prepare"><Button variant="ghost" size="sm">All preparations</Button></Link>
          {p.status !== "running" && <Button size="sm" onClick={() => refresh.mutate()} disabled={refresh.isPending}>Refresh with new games</Button>}
          <Button size="sm" variant="danger" onClick={() => setDel(true)}><Trash2 size={14} /> Delete</Button>
        </>} />
      {p.status === "running" && (
        <Panel className="p-6" aria-live="polite">
          <PanelTitle sub={p.job?.message ?? "starting"}>Working on it</PanelTitle>
          <div className="px-5 pb-4"><Progress value={p.job?.progress ?? 0} className="mt-2" />
            <p className="mt-3 text-[12.5px] text-muted">{p.downloaded.toLocaleString()} games downloaded, {p.analysed.toLocaleString()} analysed. You can leave this page: the work continues, and the Activity page shows it.</p>
            {p.job && <Button className="mt-3" size="sm" variant="ghost" onClick={() => cancel.mutate(p.job!.id)}>Cancel</Button>}</div>
        </Panel>
      )}
      {p.status === "failed" && <Panel className="p-6"><EmptyState icon={Crosshair} title={p.error === "cancelled" ? "Cancelled" : "That did not work"} text={p.error ?? undefined} action={<Button variant="primary" onClick={() => refresh.mutate()}>Try again</Button>} /></Panel>}
      {p.status === "done" && p.report && <ReportView prepId={id} report={p.report} />}
      <ConfirmDialog open={del} onOpenChange={setDel} title="Delete this preparation?" text="The report and the opponent's games kept for it are removed from this computer." confirm="Delete" onConfirm={() => remove.mutate()} />
    </div>
  );
}
