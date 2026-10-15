import * as Dialog from "@radix-ui/react-dialog";
import * as Tabs from "@radix-ui/react-tabs";
import { X } from "lucide-react";
import { Button } from "@/components/ui/Button";

const field = "h-9 w-full rounded-md border border-border bg-surface px-3 text-[13.5px] outline-none focus:border-accent";

export function ImportDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/40" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-[min(92vw,460px)] -translate-x-1/2 -translate-y-1/2 rounded-xl border border-border bg-surface p-5 shadow-xl">
          <div className="flex items-center justify-between"><Dialog.Title className="text-[16px] font-semibold">Import games</Dialog.Title><Dialog.Close className="cursor-pointer rounded p-1 text-muted hover:bg-surface-2" aria-label="Close"><X size={16} /></Dialog.Close></div>
          <Dialog.Description className="mt-1 text-[13px] text-muted">Only public games are read. Nothing is sent anywhere except the request for your games.</Dialog.Description>
          <Tabs.Root defaultValue="lichess" className="mt-4">
            <Tabs.List className="mb-4 inline-flex rounded-md border border-border p-0.5">
              {[["lichess", "Lichess"], ["chesscom", "Chess.com"], ["pgn", "PGN file"]].map(([v, l]) => <Tabs.Trigger key={v} value={v} className="h-8 rounded px-3 text-[13px] font-medium text-muted data-[state=active]:bg-accent-soft data-[state=active]:text-accent cursor-pointer">{l}</Tabs.Trigger>)}
            </Tabs.List>
            {["lichess", "chesscom"].map((v) => (
              <Tabs.Content key={v} value={v} className="space-y-3 outline-none">
                <label className="block text-[12.5px] font-medium">Username<input className={field + " mt-1"} placeholder={v === "lichess" ? "your Lichess username" : "your Chess.com username"} /></label>
                <label className="block text-[12.5px] font-medium">How many games<select className={field + " mt-1"} defaultValue="200"><option>50</option><option>200</option><option>1000</option><option value="all">All</option></select></label>
                <p className="text-[12px] text-faint">Runs in the background; you can keep using the app and see progress under Activity.</p>
              </Tabs.Content>
            ))}
            <Tabs.Content value="pgn" className="outline-none">
              <div className="grid h-32 place-items-center rounded-lg border border-dashed border-border text-[13px] text-muted">Drop a .pgn file here or paste PGN text</div>
            </Tabs.Content>
          </Tabs.Root>
          <div className="mt-5 flex justify-end gap-2">
            <Dialog.Close asChild><Button variant="ghost">Cancel</Button></Dialog.Close>
            <Button variant="primary" disabled title="Importing is built in the next step of the project">Import</Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
