import * as Dialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";

const SECTIONS: [string, [string, string][]][] = [
  ["Anywhere", [["Ctrl / Cmd + K", "Search and commands"], ["?", "This list"]]],
  ["Reviewing a game", [["← →", "Previous and next move"], ["Home  End", "First and last move"], ["N  P", "Next and previous key moment"], ["Space", "Play the game, pause"], ["F", "Flip the board"], ["B", "Show or hide the engine's best move"], ["E", "Engine on or off"], ["Esc", "Leave a side line"]]],
  ["On the board", [["Click or drag", "Move a piece"], ["Right-drag", "Draw an arrow"], ["Right-click", "Mark a square"], ["Tab, arrows, Enter", "Move with the keyboard"]]],
];

/** The keyboard shortcuts, opened with "?". */
export function ShortcutsDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-[#0b1118]/45" />
        <Dialog.Content aria-describedby={undefined} className="fixed left-1/2 top-1/2 z-50 w-[min(92vw,520px)] -translate-x-1/2 -translate-y-1/2 rounded-[12px] border border-border bg-surface p-6 shadow-[var(--shadow)]">
          <div className="flex items-center justify-between"><Dialog.Title className="text-[16px] font-semibold">Keyboard shortcuts</Dialog.Title><Dialog.Close aria-label="Close" className="cursor-pointer rounded p-1 text-muted hover:bg-surface-2"><X size={16} /></Dialog.Close></div>
          <div className="mt-4 space-y-5">
            {SECTIONS.map(([title, rows]) => (
              <section key={title}><h3 className="mb-1.5 text-[11.5px] font-semibold uppercase tracking-[0.06em] text-muted">{title}</h3>
                <dl className="space-y-1.5 text-[13.5px]">{rows.map(([k, d]) => <div key={k} className="flex items-center justify-between gap-4"><dt className="text-muted">{d}</dt><dd><kbd className="rounded border border-border bg-surface-2 px-1.5 py-0.5 font-mono text-[12px]">{k}</kbd></dd></div>)}</dl></section>
            ))}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
