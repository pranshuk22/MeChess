import * as Dialog from "@radix-ui/react-dialog";
import * as Tabs from "@radix-ui/react-tabs";
import { FileUp, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAccounts, useImportPgn, useImportUser } from "@/api/hooks";
import { Button } from "@/components/ui/Button";
import { Input, Label, Select } from "@/components/ui/Field";
import { useDialogs } from "@/state/dialogs";

const COUNTS = [["50", "Latest 50"], ["200", "Latest 200"], ["1000", "Latest 1,000"], ["5000", "Latest 5,000"]];

/** One dialog for every way in: Lichess, Chess.com, a PGN file. The import runs as a background job; progress is in Activity. */
export function ImportDialog() {
  const { importOpen, setImportOpen } = useDialogs();
  const nav = useNavigate();
  const accounts = useAccounts().data;
  const user = useImportUser(), pgn = useImportPgn();
  const [tab, setTab] = useState("lichess");
  const [name, setName] = useState({ lichess: "", chesscom: "" });
  const [count, setCount] = useState("200");
  const [onlyNew, setOnlyNew] = useState(true);
  const [text, setText] = useState("");
  const [player, setPlayer] = useState("");
  const [error, setError] = useState("");
  const file = useRef<HTMLInputElement>(null);
  useEffect(() => { if (accounts) { setName((n) => ({ lichess: n.lichess || accounts.lichess || "", chesscom: n.chesscom || accounts.chesscom || "" })); setPlayer((p) => p || accounts.lichess || accounts.chesscom || ""); } }, [accounts]);
  useEffect(() => { if (!importOpen) setError(""); }, [importOpen]);

  const started = () => { setImportOpen(false); nav("/activity"); };
  const fail = (e: unknown) => setError((e as Error).message);
  const submit = () => {
    setError("");
    if (tab === "pgn") pgn.mutate({ text, player: player.trim() || undefined }, { onSuccess: started, onError: fail });
    else user.mutate({ platform: tab as "lichess" | "chesscom", username: name[tab as "lichess" | "chesscom"].trim(), max: Number(count), only_new: onlyNew }, { onSuccess: started, onError: fail });
  };
  const ready = tab === "pgn" ? text.trim().length > 0 : name[tab as "lichess" | "chesscom"].trim().length >= 2;
  const busy = user.isPending || pgn.isPending;
  const onFile = async (f?: File) => { if (f) setText(await f.text()); };

  return (
    <Dialog.Root open={importOpen} onOpenChange={setImportOpen}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-[#0b1118]/50 backdrop-blur-[2px]" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-[min(92vw,500px)] -translate-x-1/2 -translate-y-1/2 rounded-[16px] border border-border bg-surface p-6 shadow-[var(--shadow)]">
          <div className="flex items-start justify-between">
            <div><Dialog.Title className="text-[18px] font-semibold tracking-[-0.02em]">Import games</Dialog.Title>
              <Dialog.Description className="mt-1 text-[13.5px] text-muted">Only public games are read. They are stored and analysed on this computer.</Dialog.Description></div>
            <Dialog.Close className="-mr-1 rounded-md p-1.5 text-muted hover:bg-surface-2 cursor-pointer" aria-label="Close"><X size={17} /></Dialog.Close>
          </div>
          <Tabs.Root value={tab} onValueChange={(v) => { setTab(v); setError(""); }} className="mt-5">
            <Tabs.List className="mb-5 inline-flex rounded-[9px] bg-sunken p-0.5" aria-label="Where from">
              {[["lichess", "Lichess"], ["chesscom", "Chess.com"], ["pgn", "PGN file"]].map(([v, l]) => <Tabs.Trigger key={v} value={v} className="h-8 rounded-[7px] px-3.5 text-[13px] font-medium text-muted data-[state=active]:bg-surface data-[state=active]:text-text data-[state=active]:shadow-[var(--shadow-sm)] cursor-pointer">{l}</Tabs.Trigger>)}
            </Tabs.List>
            {(["lichess", "chesscom"] as const).map((v) => (
              <Tabs.Content key={v} value={v} className="space-y-4 outline-none">
                <Label>Username<Input className="mt-1.5" autoFocus value={name[v]} onChange={(e) => setName({ ...name, [v]: e.target.value })} placeholder={v === "lichess" ? "your Lichess username" : "your Chess.com username"} /></Label>
                <Label>How many games<Select className="mt-1.5" value={count} onChange={(e) => setCount(e.target.value)}>{COUNTS.map(([c, l]) => <option key={c} value={c}>{l}</option>)}</Select></Label>
                <label className="flex items-center gap-2.5 text-[13.5px]"><input type="checkbox" checked={onlyNew} onChange={(e) => setOnlyNew(e.target.checked)} className="h-4 w-4 accent-[var(--accent)]" /> Stop at games I already have <span className="text-muted">(quick update)</span></label>
              </Tabs.Content>
            ))}
            <Tabs.Content value="pgn" className="space-y-4 outline-none">
              <div>
                <div className="mb-1.5 flex items-center justify-between"><span className="text-[12.5px] font-medium">PGN text</span><button onClick={() => file.current?.click()} className="inline-flex items-center gap-1.5 text-[12.5px] font-medium text-accent hover:underline cursor-pointer"><FileUp size={14} /> Choose a file</button></div>
                <textarea value={text} onChange={(e) => setText(e.target.value)} placeholder="Paste PGN here, or choose a .pgn file" aria-label="PGN text" rows={6}
                  onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); onFile(e.dataTransfer.files[0]); }}
                  className="w-full resize-none rounded-[9px] border border-border bg-surface p-3 font-mono text-[12px] text-text shadow-[var(--shadow-sm)] outline-none placeholder:text-faint focus:border-accent" />
                <input ref={file} type="file" accept=".pgn,.txt,text/plain" className="hidden" onChange={(e) => onFile(e.target.files?.[0])} />
              </div>
              <Label hint="To know which side is yours. Optional.">Your name in these games<Input className="mt-1.5" value={player} onChange={(e) => setPlayer(e.target.value)} placeholder="as written in the PGN" /></Label>
            </Tabs.Content>
          </Tabs.Root>
          {error && <p role="alert" className="mt-4 rounded-[9px] bg-[color-mix(in_srgb,var(--q-blunder)_10%,transparent)] px-3 py-2 text-[13px] text-[var(--q-blunder)]">{error}</p>}
          <div className="mt-6 flex justify-end gap-2">
            <Dialog.Close asChild><Button variant="ghost">Cancel</Button></Dialog.Close>
            <Button variant="primary" disabled={!ready || busy} onClick={submit}>{busy ? "Starting…" : "Import"}</Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
