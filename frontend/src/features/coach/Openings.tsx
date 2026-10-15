import { BookOpen, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { Button } from "@/components/ui/Button";
import { Input, Label, Select } from "@/components/ui/Field";
import { EmptyState } from "@/components/ui/Misc";
import { Panel, PanelTitle } from "@/components/ui/Panel";
import { Segmented } from "@/components/ui/Segmented";
import { GuidedBoard, Note, type GuidedView } from "./guided";

interface Rep { id: string; name: string; colour: string; moves: number }
interface View extends GuidedView { line: string[]; mistakes: number; report: { reason: string; message: string } | null }
interface Session { session: string; moves: number; view: View }
interface Coverage { covered: number; gaps: { line: string; share: number }[] }

/** Opening practice: save a repertoire (a PGN with variations), then play it against the replies players of your rating really make. */
export function Openings() {
  const qc = useQueryClient();
  const status = useQuery({ queryKey: ["coach-status"], queryFn: () => api<{ explorer: boolean; tablebase: boolean }>("/api/coach/status") }).data;
  const reps = useQuery({ queryKey: ["repertoires"], queryFn: () => api<Rep[]>("/api/coach/repertoires") }).data ?? [];
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ name: "", colour: "white", pgn: "" });
  const [rating, setRating] = useState("1500");
  const [session, setSession] = useState<Session | null>(null);
  const [message, setMessage] = useState<{ tone: "info" | "bad" | "good"; text: string } | null>(null);
  const [cov, setCov] = useState<{ id: string; c: Coverage } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const guard = async (fn: () => Promise<void>) => { setBusy(true); setError(""); try { await fn(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); } };
  const save = () => guard(async () => { await api("/api/coach/repertoires", { method: "POST", json: form }); setAdding(false); setForm({ name: "", colour: "white", pgn: "" }); qc.invalidateQueries({ queryKey: ["repertoires"] }); });
  const start = (id: string) => guard(async () => { setSession(await api<Session>(`/api/coach/repertoires/${id}/start?rating=${rating}`, { method: "POST" })); setMessage(null); });
  const coverage = (id: string) => guard(async () => setCov({ id, c: await api<Coverage>(`/api/coach/repertoires/${id}/coverage?rating=${rating}`) }));
  const remove = (id: string) => guard(async () => { await api(`/api/coach/repertoires/${id}`, { method: "DELETE" }); qc.invalidateQueries({ queryKey: ["repertoires"] }); });
  const onMove = (from: string, to: string, promo?: string) => guard(async () => {
    const r = await api<{ verdict?: string; message?: string; view: View }>(`/api/coach/openings/${session!.session}/move`, { method: "POST", json: { uci: from + to + (promo ?? "") } });
    setSession({ ...session!, view: r.view });
    setMessage(r.verdict === "ok" ? null : { tone: "bad", text: r.message ?? "Not in your repertoire." });
  });

  if (status && !status.explorer) return <Panel><EmptyState icon={BookOpen} title="The opening explorer is not built yet" text="Opening practice plays your repertoire against the replies players of your rating really make, which comes from the explorer database (docs/opening-explorer.md)." /></Panel>;

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
            {message && <div className="mt-3"><Note tone={message.tone}>{message.text}</Note></div>}
            {v.report && <div className="mt-3"><Note tone={v.report.reason === "unanswered" ? "bad" : "good"}>{v.report.message}</Note></div>}
            <div className="mt-4 flex gap-2"><Button onClick={() => start(reps.find((r) => r.colour === v.color)?.id ?? reps[0].id)}>Again</Button><Button variant="ghost" onClick={() => setSession(null)}>Back</Button></div>
          </Panel>
          {error && <p role="alert" className="text-[13px] text-[var(--q-blunder)]">{error}</p>}
        </div>
      </div>
    );
  }
  return (
    <div className="grid grid-cols-[minmax(0,1fr)_340px] gap-5 max-lg:grid-cols-1">
      <Panel>
        <PanelTitle sub="A PGN with variations for one colour. Practise it against the replies players of your rating make." right={<Button size="sm" onClick={() => setAdding(true)}><Plus size={14} /> Add</Button>}>Your repertoires</PanelTitle>
        <div className="px-5 pb-5">
          {reps.length === 0 && !adding && <EmptyState icon={BookOpen} title="No repertoire yet" text="Paste the lines you play, as a PGN with variations (an opening study from Lichess works well)." action={<Button variant="primary" onClick={() => setAdding(true)}><Plus size={15} /> Add a repertoire</Button>} />}
          {adding && (
            <div className="mb-4 space-y-3 rounded-[10px] bg-sunken p-4">
              <div className="grid grid-cols-2 gap-3 max-sm:grid-cols-1"><Label>Name<Input className="mt-1.5" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Ruy Lopez" /></Label>
                <div><div className="mb-1.5 text-[12.5px] font-medium">You play</div><Segmented label="Colour" value={form.colour} onChange={(c) => setForm({ ...form, colour: c })} options={[["white", "White"], ["black", "Black"]]} /></div></div>
              <textarea aria-label="Repertoire PGN" value={form.pgn} onChange={(e) => setForm({ ...form, pgn: e.target.value })} rows={5} placeholder="1. e4 e5 2. Nf3 Nc6 3. Bb5 (3. Bc4 Bc5) 3... a6 *" className="w-full resize-none rounded-[9px] border border-border bg-surface p-3 font-mono text-[12px] outline-none focus:border-accent" />
              <div className="flex gap-2"><Button variant="primary" onClick={save} disabled={busy || !form.name.trim() || !form.pgn.trim()}>Save</Button><Button variant="ghost" onClick={() => setAdding(false)}>Cancel</Button></div>
            </div>
          )}
          {error && <p role="alert" className="mb-3 text-[13px] text-[var(--q-blunder)]">{error}</p>}
          <ul className="space-y-2">
            {reps.map((r) => (
              <li key={r.id} className="rounded-[10px] border border-border px-4 py-3">
                <div className="flex items-center justify-between gap-3">
                  <div><b className="font-medium">{r.name}</b> <span className="text-[12.5px] text-muted capitalize">· {r.colour}</span></div>
                  <div className="flex items-center gap-1.5"><Button size="sm" variant="primary" onClick={() => start(r.id)} disabled={busy}>Practise</Button><Button size="sm" onClick={() => coverage(r.id)} disabled={busy}>Coverage</Button>
                    <button onClick={() => remove(r.id)} aria-label={`Delete ${r.name}`} className="rounded p-1.5 text-muted hover:text-[var(--q-blunder)] cursor-pointer"><Trash2 size={15} /></button></div>
                </div>
                {cov?.id === r.id && (
                  <div className="mt-3 text-[13px]"><p>Your repertoire covers about <b>{Math.round(cov.c.covered * 100)}%</b> of the games that follow it.</p>
                    {cov.c.gaps.length > 0 && <><p className="mt-2 text-muted">Most common replies with no answer yet:</p><ul className="mt-1 space-y-0.5">{cov.c.gaps.map((g, i) => <li key={i} className="flex justify-between"><span>{g.line}</span><span className="tnum text-muted">{(g.share * 100).toFixed(1)}%</span></li>)}</ul></>}</div>
                )}
              </li>
            ))}
          </ul>
        </div>
      </Panel>
      <Panel>
        <PanelTitle sub="Replies come from games at this rating">Opponent's rating</PanelTitle>
        <div className="px-5 pb-5"><Select value={rating} onChange={(e) => setRating(e.target.value)} aria-label="Rating">{[1000, 1200, 1400, 1600, 1800, 2000, 2200].map((r) => <option key={r} value={r}>around {r}</option>)}</Select></div>
      </Panel>
    </div>
  );
}
