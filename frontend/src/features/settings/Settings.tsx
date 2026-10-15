import { Trash2, Upload } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useAccounts, useBuildCache, useCacheStats, useClearCache, useSaveAccounts, useSaveSettings, useSettings, useThemes, useWorkspace } from "@/api/hooks";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Stat } from "@/components/ui/Misc";
import { useNavigate } from "react-router-dom";
import { api } from "@/api/client";
import { Board } from "@/board/Board";
import { BoardAndPieces, SiteAppearance } from "@/components/Appearance";
import { Button } from "@/components/ui/Button";
import { Input, Label, Select } from "@/components/ui/Field";
import { PageHeader, Panel, PanelTitle } from "@/components/ui/Panel";
import { Segmented } from "@/components/ui/Segmented";
import { START_FEN } from "@/lib/game";
import { usePieceSets, useUi } from "@/state/ui";

export function SettingsPage() {
  const { showCoords, setShowCoords } = useUi();
  const sets = usePieceSets();
  const ws = useWorkspace().data;
  return (
    <div className="mx-auto grid max-w-[1040px] grid-cols-[minmax(0,1fr)_300px] gap-6 px-8 py-8 max-lg:grid-cols-1 max-md:px-4">
      <div className="min-w-0 space-y-5">
        <PageHeader title="Settings" sub="Everything is stored on this computer." />
        <Accounts />
        <Engine />
        <EngineCache />
        <Panel>
          <PanelTitle sub="Light, dark or follow the system; every colour theme has both.">Website</PanelTitle>
          <div className="px-5 pb-5"><SiteAppearance /></div>
        </Panel>
        <Panel>
          <PanelTitle sub="Chosen here or from the palette button beside any board.">Board and pieces</PanelTitle>
          <div className="px-5 pb-5">
            <BoardAndPieces />
            <label className="mt-4 flex items-center justify-between gap-4 border-t border-border/70 pt-3 text-[13.5px]"><span><b className="font-medium">Board coordinates</b><span className="block text-[12.5px] text-muted">Letters and numbers on the board edge.</span></span><input type="checkbox" checked={showCoords} onChange={(e) => setShowCoords(e.target.checked)} className="h-4 w-4 accent-[var(--accent)]" /></label>
          </div>
        </Panel>
        <CustomThemes />
        <Panel>
          <PanelTitle>Credits for the bundled piece sets</PanelTitle>
          <ul className="space-y-1 px-5 pb-4 text-[13px] text-muted">{sets.filter((s) => !s.id.startsWith("custom:")).map((s) => <li key={s.id}><b className="font-medium text-text">{s.name}</b>: {s.author}, {s.licence}</li>)}</ul>
        </Panel>
        <Panel>
          <PanelTitle>Privacy and data</PanelTitle>
          <div className="space-y-2 px-5 pb-5 text-[13.5px] text-muted">
            <p>MeChess runs on your computer. Games, analyses and training data stay in your data folder. The app makes no requests to other websites except the ones you start (importing your games).</p>
            {ws && <p>Data folder: <code className="rounded bg-sunken px-1.5 py-0.5 font-mono text-[12px] text-text">{ws.data_dir}</code></p>}
          </div>
        </Panel>
      </div>
      <Panel className="sticky top-8 self-start p-3 max-lg:hidden"><Board fen={START_FEN} showCoords={showCoords} /></Panel>
    </div>
  );
}

function Accounts() {
  const { data } = useAccounts(), save = useSaveAccounts(), qc = useQueryClient();
  const [v, setV] = useState({ lichess: "", chesscom: "", rating: "" });
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  useEffect(() => { if (data) setV({ lichess: data.lichess ?? "", chesscom: data.chesscom ?? "", rating: data.rating ? String(data.rating) : "" }); }, [data]);
  return (
    <Panel>
      <PanelTitle sub="Public user names only, no passwords. Used to import your games and to know which side is yours.">Your accounts</PanelTitle>
      <div className="grid grid-cols-2 gap-4 px-5 pb-5 max-sm:grid-cols-1">
        <Label>Lichess<Input className="mt-1.5" value={v.lichess} onChange={(e) => setV({ ...v, lichess: e.target.value })} placeholder="username" /></Label>
        <Label>Chess.com<Input className="mt-1.5" value={v.chesscom} onChange={(e) => setV({ ...v, chesscom: e.target.value })} placeholder="username" /></Label>
        <Label hint="Used for the explorer, the practice and the play page when your games carry no rating.">Your rating (optional)<Input className="mt-1.5" type="number" min={400} max={3200} inputMode="numeric" value={v.rating} onChange={(e) => setV({ ...v, rating: e.target.value })} placeholder="for example 1500" /></Label>
        <div className="col-span-2 flex items-center gap-3 max-sm:col-span-1">
          <Button variant="primary" disabled={save.isPending} onClick={() => save.mutate({ lichess: v.lichess.trim() || null, chesscom: v.chesscom.trim() || null, rating: v.rating.trim() ? Number(v.rating) : null }, { onSuccess: () => { setMsg({ ok: true, text: "Saved" }); qc.invalidateQueries({ queryKey: ["me"] }); }, onError: (e) => setMsg({ ok: false, text: (e as Error).message }) })}>Save</Button>
          {msg && <span role="status" className="text-[13px]" style={{ color: msg.ok ? "var(--q-best)" : "var(--q-blunder)" }}>{msg.text}</span>}
        </div>
      </div>
    </Panel>
  );
}

const DEPTH: [string, string][] = [["20000", "Quick"], ["100000", "Standard"], ["500000", "Deep"]];

function Engine() {
  const { data } = useSettings(), save = useSaveSettings(), ws = useWorkspace().data;
  const [s, setS] = useState({ engine_path: "", nodes: 100000, multipv: 5, threads: 1, hash_mb: 64 });
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  useEffect(() => { if (data) setS({ engine_path: data.engine_path ?? "", nodes: data.nodes, multipv: data.multipv, threads: data.threads, hash_mb: data.hash_mb }); }, [data]);
  const engine = ws?.checks.find((c) => c.id === "engine");
  const preset = DEPTH.some(([n]) => Number(n) === s.nodes) ? String(s.nodes) : "custom";
  return (
    <Panel>
      <PanelTitle sub="Stockfish judges every move. More search per move is slower and more accurate.">Engine</PanelTitle>
      <div className="space-y-4 px-5 pb-5">
        {engine && <p className="text-[13px]" style={{ color: engine.state === "ok" ? "var(--q-best)" : "var(--q-inaccuracy)" }}>{engine.state === "ok" ? `Found: ${engine.detail}` : engine.detail}</p>}
        <Label hint="Leave empty to use Stockfish from your PATH.">Path to Stockfish<Input className="mt-1.5" value={s.engine_path} onChange={(e) => setS({ ...s, engine_path: e.target.value })} placeholder="/usr/local/bin/stockfish" /></Label>
        <div>
          <div className="mb-1.5 text-[12.5px] font-medium">Analysis depth</div>
          <Segmented label="Analysis depth" value={preset} onChange={(v) => v !== "custom" && setS({ ...s, nodes: Number(v) })} options={[...DEPTH, ...(preset === "custom" ? [["custom", `${s.nodes.toLocaleString()} nodes`] as [string, string]] : [])]} />
          <p className="mt-1.5 text-[12px] text-muted">{s.nodes.toLocaleString()} search nodes per position. Quick is for many games, Standard is the same as the coach uses.</p>
        </div>
        <div className="grid grid-cols-3 gap-4 max-sm:grid-cols-1">
          <Label>Lines per position<Select className="mt-1.5" value={s.multipv} onChange={(e) => setS({ ...s, multipv: Number(e.target.value) })}>{[1, 2, 3, 5].map((n) => <option key={n} value={n}>{n}</option>)}</Select></Label>
          <Label>Threads<Select className="mt-1.5" value={s.threads} onChange={(e) => setS({ ...s, threads: Number(e.target.value) })}>{[1, 2, 4, 8].map((n) => <option key={n} value={n}>{n}</option>)}</Select></Label>
          <Label>Memory<Select className="mt-1.5" value={s.hash_mb} onChange={(e) => setS({ ...s, hash_mb: Number(e.target.value) })}>{[64, 128, 256, 512, 1024].map((n) => <option key={n} value={n}>{n} MB</option>)}</Select></Label>
        </div>
        <div className="flex items-center gap-3">
          <Button variant="primary" disabled={save.isPending} onClick={() => save.mutate({ ...s, engine_path: s.engine_path.trim() || null }, { onSuccess: () => setMsg({ ok: true, text: "Saved" }), onError: (e) => setMsg({ ok: false, text: (e as Error).message }) })}>Save</Button>
          {msg && <span role="status" className="text-[13px]" style={{ color: msg.ok ? "var(--q-best)" : "var(--q-blunder)" }}>{msg.text}</span>}
        </div>
      </div>
    </Panel>
  );
}

const PIECES = ["K", "Q", "R", "B", "N", "P"].flatMap((p) => ["w", "b"].map((c) => c + p));

function CustomThemes() {
  const themes = useThemes(), qc = useQueryClient();
  const [name, setName] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const setFiles = useRef<HTMLInputElement>(null), boardFile = useRef<HTMLInputElement>(null);
  const refresh = () => qc.invalidateQueries({ queryKey: ["themes"] });
  const put = (path: string, f: File) => fetch(path, { method: "PUT", body: f }).then(async (r) => { if (!r.ok) throw new Error((await r.json().catch(() => ({ detail: r.statusText }))).detail); });

  async function addSet(files: FileList | null) {
    if (!files?.length) return;
    const setName = name.trim() || "My pieces";
    const names = Array.from(files).map((f) => f.name.replace(/\.[^.]+$/, ""));
    const missing = PIECES.filter((p) => !names.includes(p));
    if (missing.length) { setMsg({ ok: false, text: `Choose all 12 files, named wK, wQ, wR, wB, wN, wP and bK, bQ, bR, bB, bN, bP (missing: ${missing.join(", ")}).` }); return; }
    try { for (const f of Array.from(files)) await put(`/api/themes/pieces/${encodeURIComponent(setName)}/${encodeURIComponent(f.name)}`, f); setMsg({ ok: true, text: `Added the piece set "${setName}".` }); refresh(); }
    catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
  }
  async function addBoard(files: FileList | null) {
    const f = files?.[0];
    if (!f) return;
    try { await put(`/api/themes/boards/${encodeURIComponent(f.name)}`, f); setMsg({ ok: true, text: `Added the board "${f.name}".` }); refresh(); }
    catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
  }
  const remove = async (path: string) => { try { await api(path, { method: "DELETE" }); refresh(); } catch (e) { setMsg({ ok: false, text: (e as Error).message }); } };

  return (
    <Panel>
      <PanelTitle sub="Use images you have the right to use. They stay in your data folder and are never uploaded anywhere.">Your own pieces and boards</PanelTitle>
      <div className="space-y-5 px-5 pb-5">
        <div>
          <div className="mb-1.5 text-[12.5px] font-medium">Piece set</div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="w-48"><Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Name of the set" aria-label="Name of the piece set" /></div>
            <Button onClick={() => setFiles.current?.click()}><Upload size={15} /> Choose the 12 images</Button>
            <input ref={setFiles} type="file" multiple accept=".svg,.png,.webp" className="hidden" onChange={(e) => { addSet(e.target.files); e.target.value = ""; }} />
          </div>
          <p className="mt-1.5 text-[12px] text-muted">SVG or PNG files named wK, wQ, wR, wB, wN, wP and bK, bQ, bR, bB, bN, bP. SVG files with scripts or links are refused.</p>
          {themes.data?.pieces.map((p) => (
            <div key={p.id} className="mt-2 flex items-center justify-between rounded-[6px] bg-sunken px-3 py-2 text-[13px]"><span className="flex items-center gap-2"><img alt="" width={24} height={24} src={p.files.wN} />{p.name}</span><button onClick={() => remove(`/api/themes/pieces/${encodeURIComponent(p.id)}`)} aria-label={`Delete ${p.name}`} className="rounded p-1 text-muted hover:text-[var(--q-blunder)] cursor-pointer"><Trash2 size={15} /></button></div>
          ))}
        </div>
        <div>
          <div className="mb-1.5 text-[12.5px] font-medium">Board image</div>
          <Button onClick={() => boardFile.current?.click()}><Upload size={15} /> Choose an image</Button>
          <input ref={boardFile} type="file" accept=".svg,.png,.jpg,.jpeg,.webp" className="hidden" onChange={(e) => { addBoard(e.target.files); e.target.value = ""; }} />
          <p className="mt-1.5 text-[12px] text-muted">A square picture of a whole 8 by 8 board (up to 3 MB). It shows up under Board.</p>
          {themes.data?.boards.map((b) => (
            <div key={b.id} className="mt-2 flex items-center justify-between rounded-[6px] bg-sunken px-3 py-2 text-[13px]"><span className="flex items-center gap-2"><img alt="" width={24} height={24} className="rounded" src={b.url} />{b.name}</span><button onClick={() => remove(b.url)} aria-label={`Delete ${b.name}`} className="rounded p-1 text-muted hover:text-[var(--q-blunder)] cursor-pointer"><Trash2 size={15} /></button></div>
          ))}
        </div>
        {msg && <p role="status" className="text-[13px]" style={{ color: msg.ok ? "var(--q-best)" : "var(--q-blunder)" }}>{msg.text}</p>}
      </div>
    </Panel>
  );
}

const kb = (n: number) => (n >= 1_000_000 ? `${(n / 1_000_000).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1000))} KB`);

function EngineCache() {
  const stats = useCacheStats().data, settings = useSettings().data, save = useSaveSettings(), build = useBuildCache(), clear = useClearCache(), nav = useNavigate();
  const [confirm, setConfirm] = useState(false);
  const [theory, setTheory] = useState(false);
  const [strength, setStrength] = useState("settings");                          // how hard each position is searched when the cache is built
  const [count, setCount] = useState("300");
  const nodes = strength === "settings" ? settings?.nodes ?? 100_000 : Number(strength);
  const minutes = Math.max(1, Math.round((Number(count) * nodes) / 1_000_000 / 60));    // about a million nodes a second on one thread
  const max = Math.max(1, ...(stats?.byMove.map((m) => m.positions) ?? [1]));
  return (
    <Panel>
      <PanelTitle sub="The engine's verdicts on opening positions (the first ten moves) are kept, so the openings you play are not searched again. Everything is stored in your database.">Opening cache</PanelTitle>
      <div className="space-y-5 px-5 pb-5">
        <div className="grid grid-cols-3 gap-3 max-sm:grid-cols-1">
          <Stat label="Positions" value={(stats?.positions ?? 0).toLocaleString()} />
          <Stat label="Used" value={(stats?.hits ?? 0).toLocaleString()} sub="times" />
          <Stat label="Size" value={kb(stats?.bytes ?? 0)} />
        </div>
        {!!stats?.positions && <p className="-mt-2 text-[12.5px] text-muted">Deepest search stored: <b className="tnum text-text">{stats.deepest.toLocaleString()}</b> nodes; <b className="tnum text-text">{stats.deep.toLocaleString()}</b> positions searched to a million nodes or more. A deeper search replaces a shallower one, never the other way round.</p>}
        {!!stats?.positions && (
          <div>
            <div className="mb-1.5 text-[12px] font-medium text-muted">Positions by move number</div>
            <div className="flex h-14 items-end gap-1.5" role="img" aria-label="Cached positions by move number">
              {stats.byMove.map((m) => <div key={m.move} className="flex-1 rounded-t-[3px] bg-accent/70" style={{ height: `${Math.max(3, (m.positions / max) * 100)}%` }} title={`move ${m.move}: ${m.positions} positions`} />)}
            </div>
            <div className="mt-1 flex justify-between text-[11px] text-faint"><span>start</span><span>move {stats.maxMoves}</span></div>
          </div>
        )}
        <label className="flex items-center justify-between gap-4 text-[13.5px]"><span><b className="font-medium">Use the cache</b><span className="block text-[12.5px] text-muted">Look openings up here when analysing games and when you step through a game.</span></span>
          <input type="checkbox" checked={settings?.use_cache ?? true} onChange={(e) => save.mutate({ use_cache: e.target.checked })} className="h-4 w-4 accent-[var(--accent)]" /></label>
        <div className="space-y-3 border-t border-border/70 pt-4">
          <div className="flex flex-wrap items-end gap-4">
            <div><div className="mb-1.5 text-[12.5px] font-medium">How deep to search</div>
              <Segmented label="Search depth for the cache" value={strength} onChange={setStrength} options={[["settings", `Analysis setting (${(settings?.nodes ?? 100_000).toLocaleString()})`], ["1000000", "Deep (1 million)"], ["5000000", "Very deep (5 million)"]]} /></div>
            <div className="w-36"><div className="mb-1.5 text-[12.5px] font-medium">Positions</div>
              <Select aria-label="How many positions" value={count} onChange={(e) => setCount(e.target.value)}>{["100", "300", "1000", "3000"].map((n) => <option key={n}>{n}</option>)}</Select></div>
          </div>
          <p className="text-[12.5px] text-muted">The most common positions of your own games first, up to the number chosen; positions already searched this deep are skipped. About {minutes < 60 ? `${minutes} minute${minutes === 1 ? "" : "s"}` : `${(minutes / 60).toFixed(1)} hours`} on one thread: it runs in the background and can be cancelled in Activity.</p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <Button disabled={build.isPending} onClick={() => build.mutate({ min_count: 2, limit: Number(count), include_theory: theory, nodes: strength === "settings" ? undefined : Number(strength) }, { onSuccess: () => nav("/activity") })}>Build for my openings</Button>
          <label className="flex items-center gap-2 text-[12.5px] text-muted"><input type="checkbox" checked={theory} onChange={(e) => setTheory(e.target.checked)} className="accent-[var(--accent)]" /> also the main opening lines</label>
          <Button variant="danger" className="ml-auto" disabled={!stats?.positions || clear.isPending} onClick={() => setConfirm(true)}><Trash2 size={15} /> Delete all</Button>
        </div>
        {build.isError && <p role="alert" className="text-[13px] text-[var(--q-blunder)]">{(build.error as Error).message}</p>}
      </div>
      <ConfirmDialog open={confirm} onOpenChange={setConfirm} title="Delete the opening cache?" text="The stored engine evaluations are removed. Nothing else changes; they are searched again when needed." confirm="Delete" onConfirm={() => clear.mutate(undefined)} />
    </Panel>
  );
}
