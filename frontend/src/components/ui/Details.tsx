import type { ReactNode } from "react";

/** The technical part of an explanation, folded away: a player reads the plain sentence; whoever sets things up opens this. */
export function Details({ summary = "How to set this up", children }: { summary?: string; children: ReactNode }) {
  return (
    <details className="mx-auto mt-4 max-w-md rounded-[8px] border border-border px-3 py-2 text-left text-[12.5px] text-muted">
      <summary className="cursor-pointer select-none font-medium text-text">{summary}</summary>
      <div className="mt-2 space-y-1.5">{children}</div>
    </details>
  );
}
