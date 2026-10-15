import { ServerOff } from "lucide-react";
import { Button } from "./ui/Button";
import { EmptyState } from "./ui/Misc";
import { Panel } from "./ui/Panel";

/** Shown instead of a page full of failed requests when the MeChess server is not running. */
export function ServerDown({ onRetry, signedOut = false }: { onRetry: () => void; signedOut?: boolean }) {
  return (
    <div className="mx-auto max-w-[640px] px-6 py-16">
      <Panel>
        {signedOut ? <EmptyState icon={ServerOff} title="Open MeChess from its own address"
          text={<>Every run of MeChess has an access key, so that other programs on this computer cannot use it. Start it with <code className="rounded bg-sunken px-1.5 py-0.5 font-mono text-[12px] text-text">python -m chessme app</code> (it opens the right address), or use the address with <code className="rounded bg-sunken px-1.5 py-0.5 font-mono text-[12px] text-text">?t=…</code> that it printed.</>}
          action={<Button onClick={onRetry}>Check again</Button>} /> :
        <EmptyState icon={ServerOff} title="The MeChess server is not running"
          text={<>The pages get your games from a small program on this computer. Start it from the project folder with <code className="rounded bg-sunken px-1.5 py-0.5 font-mono text-[12px] text-text">python -m chessme app</code>, or for development with <code className="rounded bg-sunken px-1.5 py-0.5 font-mono text-[12px] text-text">npm run dev:all</code> in <code className="rounded bg-sunken px-1.5 py-0.5 font-mono text-[12px] text-text">frontend/</code>. This page reconnects by itself.</>}
          action={<Button onClick={onRetry}>Check again</Button>} />}
      </Panel>
    </div>
  );
}
