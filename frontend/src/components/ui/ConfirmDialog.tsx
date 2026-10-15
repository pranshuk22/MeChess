import * as Dialog from "@radix-ui/react-dialog";
import type { ReactNode } from "react";
import { Button } from "./Button";

/** A small "are you sure" for things that delete data. */
export function ConfirmDialog({ open, onOpenChange, title, text, confirm, onConfirm }: { open: boolean; onOpenChange: (v: boolean) => void; title: string; text: ReactNode; confirm: string; onConfirm: () => void }) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-[#0b1118]/50 backdrop-blur-[2px]" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-[min(92vw,420px)] -translate-x-1/2 -translate-y-1/2 rounded-[12px] border border-border bg-surface p-6 shadow-[var(--shadow)]">
          <Dialog.Title className="text-[17px] font-semibold tracking-[-0.02em]">{title}</Dialog.Title>
          <Dialog.Description className="mt-2 text-[13.5px] text-muted">{text}</Dialog.Description>
          <div className="mt-6 flex justify-end gap-2">
            <Dialog.Close asChild><Button variant="ghost">Cancel</Button></Dialog.Close>
            <Button variant="primary" onClick={() => { onConfirm(); onOpenChange(false); }}>{confirm}</Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
