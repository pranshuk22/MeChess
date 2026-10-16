import { useMe } from "@/api/hooks";
import { Details } from "@/components/ui/Details";
import { BookOpen, Plus, Search, Trash2 } from "lucide-react";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { Button } from "@/components/ui/Button";
import { Input, Label, Select } from "@/components/ui/Field";
import { EmptyState } from "@/components/ui/Misc";
import { Panel, PanelTitle } from "@/components/ui/Panel";
import { Segmented } from "@/components/ui/Segmented";
import { FeedbackCard, type Feedback } from "./Feedback";
import { GuidedBoard, Note, type GuidedView } from "./guided";

interface Rep { id: string; name: string; colour: string; moves: number }
interface View extends GuidedView { line: string[]; mistakes: number; report: { reason: string; message: string } | null }
interface Session { session: string; moves: number; view: View }
interface Mine { games: number; positions: number; moves: number }
interface LibItem { name: string; side: "white" | "black"; lines: number; eco: string; featured: boolean; yours: { games: number; score: number } | null }
interface Coverage { covered: number; gaps: { line: string; share: number }[] }

/** Opening practice: save a repertoire (a PGN with variations), then play it against the replies players of your rating really make. */
export function Openings() {
  const qc = useQueryClient();
  const status = useQuery({ queryKey: ["coach-status"], queryFn: () => api<{ explorer: boolean; tablebase: boolean }>("/api/coach/status") }).data;
  const reps = useQuery({ queryKey: ["repertoires"], queryFn: () => api<Rep[]>("/api/coach/repertoires") }).data ?? [];
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ name: "", colour: "white", pgn: "" });
  const me = useMe().data;
  const [pickedRating, setRating] = useState<string | null>(null);
  const rating = pickedRating ?? String(me?.band ?? 1500);                   // the replies of players at your own level until you choose
  const [session, setSession] = useState<Session | null>(null);
  const [message, setMessage] = useState<{ tone: "info" | "bad" | "good"; text: string; fb?: Feedback } | null>(null);
  const [cov, setCov] = useState<{ id: string; c: Coverage } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [last, setLast] = useState<{ rep?: string; lib?: LibItem; colour?: string } | null>(null);

  const guard = async (fn: () => Promise<void>) => { setBusy(true); setError(""); try { await fn(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); } };
  const save = () => guard(async () => { await api("/api/coach/repertoires", { method: "POST", json: form }); setAdding(false); setForm({ name: "", colour: "white", pgn: "" }); qc.invalidateQueries({ queryKey: ["repertoires"] }); });
  const start = (id: string) => guard(async () => { setSession(await api<Session>(`/api/coach/repertoires/${id}/start?rating=${rating}`, { method: "POST" })); setMessage(null); setLast({ rep: id }); });
  const coverage = (id: string) => guard(async () => setCov({ id, c: await api<Coverage>(`/api/coach/repertoires/${id}/coverage?rating=${rating}`) }));
  const remove = (id: string) => guard(async () => { await api(`/api/coach/repertoires/${id}`, { method: "DELETE" }); qc.invalidateQueries({ queryKey: ["repertoires"] }); });
  const onMove = (from: string, to: string, promo?: string) => guard(async () => {
    const r = await api<{ verdict?: string; message?: string; feedback?: Feedback; view: View }>(`/api/coach/openings/${session!.session}/move`, { method: "POST", json: { uci: from + to + (promo ?? "") } });
    setSession({ ...session!, view: r.view });
    setMessage(r.verdict === "ok" ? null : { tone: r.feedback?.solved ? "info" : "bad", text: r.message ?? "Not in your repertoire.", fb: r.feedback });
  });

  const mine = useQuery({ queryKey: ["mine-rep"], queryFn: () => api<Record<"white" | "black", Mine>>("/api/coach/mine") }).data;
  const [side, setSide] = useState<"" | "white" | "black">("");
  const [term, setTerm] = useState("");
  const [asColour, setAsColour] = useState<"auto" | "white" | "black">("auto");
  const lib = useQuery({ queryKey: ["library", side, term], queryFn: () => api<LibItem[]>(`/api/coach/library?${new URLSearchParams({ q: term, side, featured: String(!term && !side && false) })}`), placeholderData: (p) => p }).data ?? [];
  const startLib = (it: LibItem, c?: string) => guard(async () => { setSession(await api<Session>("/api/coach/library/start", { method: "POST", json: { name: it.name, colour: c ?? (asColour === "auto" ? it.side : asColour), rating: Number(rating) } })); setMessage(null); setLast({ lib: it, colour: c ?? (asColour === "auto" ? it.side : asColour) }); });
  const saveLib = (it: LibItem) => guard(async () => { await api("/api/coach/library/save", { method: "POST", json: { name: it.name, colour: asColour === "auto" ? it.side : asColour, rating: Number(rating) } }); qc.invalidateQueries({ queryKey: ["repertoires"] }); });
  const makeMine = async (colour: string) => api<{ id: string }>("/api/coach/repertoires/mine", { method: "POST", json: { colour } }).then((r) => { qc.invalidateQueries({ queryKey: ["repertoires"] }); return r.id; });
  const practiseMine = (colour: string) => guard(async () => { const id = await makeMine(colour); await start(id); });
  const coverMine = (colour: string) => guard(async () => { const id = await makeMine(colour); setCov({ id, c: await api<Coverage>(`/api/coach/repertoires/${id}/coverage?rating=${rating}`) }); });


  if (status && !status.explorer) return <Panel><EmptyState icon={BookOpen} title="Opening practice needs the opening explorer" text="You practise your openings against the replies players of your rating really make, which come from the opening explorer data. It is a one-time setup prepared outside the app." action={<Details><p>The data is a single file named <code className="font-mono text-text">explorer.db</code> built from the public Lichess game archives (see docs/opening-explorer.md in the project folder). Put it in your data folder and restart the app.</p></Details>} /></Panel>;

  if (session) {
    const v = session.view;
    return (
      <div className="grid grid-cols-[minmax(0,1fr)_360px] gap-6 max-lg:grid-cols-1">
        <GuidedBoard view={v} busy={busy} onMove={onMove} />
        <div className="space-y-3">
          <Panel className="p-5">
            <h2 className="text-[17px] font-semibold">{v.over ? "Line finished" : "Play your repertoire"}</h2>
            <p className="mt-1 text-[13px] text-muted">Mistakes so far: <b className="text-text">{v.mistakes}</b></p>
            <ol className="mt-3 flex flex-wrap gap-x-2 gap-y-1 text-[13.5px]" aria-label="Line">{v.line.map((m, i) => <li key={i} className={i % 2 === (v.color === "white" ? 0 : 1) ? "font-semibold" : "text-muted"}>{m}</li>)}</ol>
            {message && <div className="mt-3 space-y-2"><Note tone={message.tone}>{message.text}</Note>{message.fb && <FeedbackCard fb={message.fb} compact />}</div>}
            {v.report && <div className="mt-3"><Note tone={v.report.reason === "unanswered" ? "bad" : "good"}>{v.report.message}</Note></div>}
            <div className="mt-4 flex gap-2"><Button onClick={() => (last?.lib ? startLib(last.lib, last.colour) : start(last?.rep ?? reps.find((r) => r.colour === v.color)?.id ?? reps[0].id))}>Again</Button><Button variant="ghost" onClick={() => setSession(null)}>Back</Button></div>
          </Panel>
          {error && <p role="alert" className="text-[13px] text-[var(--q-blunder)]">{error}</p>}
        </div>
      </div>
    );
  }
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <p className="max-w-[70ch] text-[13.5px] text-muted">Practise an opening against the replies players of a chosen rating really make. Start from what you already play, pick one from the opening library, or add your own lines.</p>
        <div className="w-44"><Label>Opponents rated<Select value={rating} onChange={(e) => setRating(e.target.value)} aria-label="Rating" className="mt-1.5">{[1000, 1200, 1400, 1500, 1600, 1800, 2000, 2200].map((r) => <option key={r} value={r}>around {r}{r === me?.band ? " (you)" : ""}</option>)}</Select></Label></div>
      </div>
      {error && <p role="alert" className="text-[13px] text-[var(--q-blunder)]">{error}</p>}

      <Panel>
        <PanelTitle sub="Built from your own games: the moves you played at least twice, with how you scored. The repertoire you actually know.">Your repertoire, from your games</PanelTitle>
        <div className="grid grid-cols-2 gap-4 px-5 pb-5 max-md:grid-cols-1">
          {(["white", "black"] as const).map((c) => {
            const m = mine?.[c];
            const ok = !!m && m.moves > 0;
            return (
              <div key={c} className="rounded-[8px] border border-border p-4">
                <div className="flex items-center justify-between"><b className="text-[14px] capitalize">As {c}</b><span className="tnum text-[12px] text-muted">{m ? `${m.games.toLocaleString()} games` : "…"}</span></div>
                <p className="mt-1 text-[13px] text-muted">{ok ? <>You know <b className="text-text">{m!.moves}</b> moves in <b className="text-text">{m!.positions}</b> positions.</> : "Not enough games yet: a move has to be played in at least two of them."}</p>
                <div className="mt-3 flex flex-wrap gap-2"><Button size="sm" variant="primary" disabled={!ok || busy} onClick={() => practiseMine(c)}>Practise it</Button><Button size="sm" disabled={!ok || busy} onClick={() => coverMine(c)}>Find the gaps</Button></div>
                {cov?.id === `mine-${c}` && <CoverageView c={cov.c} />}
              </div>
            );
          })}
        </div>
      </Panel>

      <Panel>
        <PanelTitle sub={`${lib.length} openings from the opening database. Main lines are kept; at each of your moves the explorer says which are played most.`}>Opening library</PanelTitle>
        <div className="space-y-4 px-5 pb-5">
          <div className="flex flex-wrap items-center gap-3">
            <div className="w-64"><Input aria-label="Search the library" icon={<Search size={14} />} placeholder="Search openings" value={term} onChange={(e) => setTerm(e.target.value)} /></div>
            <Segmented label="Side" value={side} onChange={setSide} options={[["", "All"], ["white", "With White"], ["black", "With Black"]]} />
            <Segmented label="Practise as" value={asColour} onChange={setAsColour} options={[["auto", "Practise as the usual side"], ["white", "White"], ["black", "Black"]]} />
          </div>
          <ul className="grid grid-cols-3 gap-3 max-xl:grid-cols-2 max-md:grid-cols-1" aria-label="Openings">
            {lib.slice(0, 60).map((it) => (
              <li key={it.name} className="flex flex-col rounded-[8px] border border-border p-3.5">
                <div className="flex items-start justify-between gap-2"><b className="text-[13.5px] font-semibold leading-5">{it.name}</b><span className="tnum shrink-0 text-[11.5px] text-faint">{it.eco}</span></div>
                <p className="mt-0.5 text-[12px] text-muted"><span className="capitalize">{it.side}</span> · {it.lines} named lines{it.yours ? <> · <b className="text-text">you: {it.yours.games} games, {Math.round(it.yours.score * 100)}%</b></> : ""}</p>
                <div className="mt-3 flex gap-2"><Button size="sm" variant="primary" disabled={busy} onClick={() => startLib(it)}>Practise</Button><Button size="sm" disabled={busy} onClick={() => saveLib(it)}>Save</Button></div>
              </li>
            ))}
          </ul>
          {lib.length === 0 && <p className="text-[13px] text-muted">No opening matches.</p>}
        </div>
      </Panel>

      <Panel>
        <PanelTitle sub="Repertoires you saved from the library, your own made from your games, and lines you add yourself as a PGN with variations." right={<Button size="sm" onClick={() => setAdding(true)}><Plus size={14} /> Add my own</Button>}>Saved repertoires</PanelTitle>
        <div className="px-5 pb-5">
          {reps.length === 0 && !adding && <p className="text-[13px] text-muted">Nothing saved yet.</p>}
          {adding && (
            <div className="mb-4 space-y-3 rounded-[8px] bg-sunken p-4">
              <div className="grid grid-cols-2 gap-3 max-sm:grid-cols-1"><Label>Name<Input className="mt-1.5" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Ruy Lopez" /></Label>
                <div><div className="mb-1.5 text-[12.5px] font-medium">You play</div><Segmented label="Colour" value={form.colour} onChange={(c) => setForm({ ...form, colour: c })} options={[["white", "White"], ["black", "Black"]]} /></div></div>
              <textarea aria-label="Repertoire PGN" value={form.pgn} onChange={(e) => setForm({ ...form, pgn: e.target.value })} rows={5} placeholder="1. e4 e5 2. Nf3 Nc6 3. Bb5 (3. Bc4 Bc5) 3... a6 *" className="w-full resize-none rounded-[6px] border border-border bg-surface p-3 font-mono text-[12px] outline-none focus:border-accent" />
              <div className="flex gap-2"><Button variant="primary" onClick={save} disabled={busy || !form.name.trim() || !form.pgn.trim()}>Save</Button><Button variant="ghost" onClick={() => setAdding(false)}>Cancel</Button></div>
            </div>
          )}
          <ul className="space-y-2">
            {reps.map((r) => (
              <li key={r.id} className="rounded-[8px] border border-border px-4 py-3">
                <div className="flex items-center justify-between gap-3">
                  <div><b className="font-medium">{r.name}</b> <span className="text-[12.5px] text-muted capitalize">· {r.colour}</span></div>
                  <div className="flex items-center gap-1.5"><Button size="sm" variant="primary" onClick={() => start(r.id)} disabled={busy}>Practise</Button><Button size="sm" onClick={() => coverage(r.id)} disabled={busy}>Coverage</Button>
                    <button onClick={() => remove(r.id)} aria-label={`Delete ${r.name}`} className="rounded p-1.5 text-muted hover:text-[var(--q-blunder)] cursor-pointer"><Trash2 size={15} /></button></div>
                </div>
                {cov?.id === r.id && <CoverageView c={cov.c} />}
              </li>
            ))}
          </ul>
        </div>
      </Panel>
    </div>
  );
}

function CoverageView({ c }: { c: Coverage }) {
  return (
    <div className="mt-3 text-[13px]"><p>Your repertoire covers about <b>{Math.round(c.covered * 100)}%</b> of the games that follow it.</p>
      {c.gaps.length > 0 && <><p className="mt-2 text-muted">Most common replies with no answer yet:</p><ul className="mt-1 space-y-0.5">{c.gaps.map((g, i) => <li key={i} className="flex justify-between"><span>{g.line}</span><span className="tnum text-muted">{(g.share * 100).toFixed(1)}%</span></li>)}</ul></>}</div>
  );
}
