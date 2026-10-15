import { Bot, Play, Square } from "lucide-react";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { Button } from "@/components/ui/Button";
import { Badge, EmptyState } from "@/components/ui/Misc";
import { PageHeader, Panel, PanelTitle } from "@/components/ui/Panel";

interface BotStatus { installed: boolean; token: boolean; running: boolean; log: string[]; dir: string }

/** Run MeChess as a Lichess bot (the lichess-bot program next to this repository). The token is read by the launcher from the environment or the Keychain: this page never sees it. */
export function BotPage() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["bot"], queryFn: () => api<BotStatus>("/api/bot"), refetchInterval: (s) => (s.state.data?.running ? 3000 : false) });
  const [error, setError] = useState("");
  const act = useMutation({ mutationFn: (what: "start" | "stop") => api<BotStatus>(`/api/bot/${what}`, { method: "POST" }), onSuccess: (d) => { qc.setQueryData(["bot"], d); setError(""); }, onError: (e) => setError((e as Error).message) });
  const s = q.data;
  return (
    <div className="mx-auto max-w-[860px] px-8 py-8 max-md:px-4">
      <PageHeader title="Lichess bot" sub="Let other players challenge MeChess on Lichess, at a strength you choose." />
      {s && !s.installed ? (
        <Panel><EmptyState icon={Bot} title="The bot program is not installed" text={<>MeChess uses <code className="rounded bg-sunken px-1 font-mono text-[12px]">lichess-bot</code> in <code className="rounded bg-sunken px-1 font-mono text-[12px]">{s.dir}</code>. Use a <b>new</b> Lichess account for the bot (it can only play as a bot afterwards); the steps are in docs/lichess-bot.md.</>} /></Panel>
      ) : (
        <div className="space-y-5">
          <Panel className="p-5">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div className="flex items-center gap-3"><Badge tone={s?.running ? "good" : "neutral"}>{s?.running ? "Running" : "Stopped"}</Badge><Badge tone={s?.token ? "good" : "warn"}>{s?.token ? "Token found" : "No token"}</Badge></div>
              {s?.running ? <Button onClick={() => act.mutate("stop")} disabled={act.isPending}><Square size={15} /> Stop the bot</Button> : <Button variant="primary" onClick={() => act.mutate("start")} disabled={act.isPending || !s}><Play size={15} /> Start the bot</Button>}
            </div>
            {!s?.token && s && <p className="mt-3 text-[13px] text-muted">The token is never typed here. Set <code className="rounded bg-sunken px-1 font-mono text-[12px]">LICHESS_BOT_TOKEN</code> in the terminal where you start MeChess, or keep it in the macOS Keychain (docs/lichess-bot.md).</p>}
            {error && <p role="alert" className="mt-3 text-[13px] text-[var(--q-blunder)]">{error}</p>}
          </Panel>
          <Panel>
            <PanelTitle sub="The end of the bot's own log">Log</PanelTitle>
            <pre className="mx-5 mb-5 max-h-[340px] overflow-auto rounded-[9px] bg-sunken p-3 font-mono text-[11.5px] leading-5" aria-label="Bot log">{s?.log.length ? s.log.join("\n") : "Nothing logged yet."}</pre>
          </Panel>
        </div>
      )}
    </div>
  );
}
