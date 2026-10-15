import * as T from "@radix-ui/react-tooltip";
import type { ReactNode } from "react";

export function Tip({ label, children, side = "bottom" }: { label: ReactNode; children: ReactNode; side?: "top" | "bottom" | "left" | "right" }) {
  return (
    <T.Root delayDuration={350}>
      <T.Trigger asChild>{children}</T.Trigger>
      <T.Portal>
        <T.Content side={side} sideOffset={6} className="z-50 rounded-md bg-[#1d262d] px-2 py-1 text-[12px] text-[#e8eef2] shadow-lg">{label}</T.Content>
      </T.Portal>
    </T.Root>
  );
}
export const TipProvider = T.Provider;
