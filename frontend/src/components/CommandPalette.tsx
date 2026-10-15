import * as Dialog from "@radix-ui/react-dialog";
import { useQuery } from "@tanstack/react-query";
import { Activity, BarChart3, BookOpen, Bot, Compass, Crosshair, Download, GraduationCap, Home, Library, Moon, Search, Settings, Swords, type LucideIcon } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "@/api/client";
import { useDialogs } from "@/state/dialogs";
import { useUi } from "@/state/ui";
import type { GameSummary } from "@/lib/types";

interface Item { id: string; label: string; hint?: string; icon: LucideIcon; run: () => void; group: string }

/** Ctrl/Cmd+K: jump to a page, start something, or find one of your games by player or opening. Arrow keys and Enter; nothing is sent anywhere but to this computer's own server. */
export function CommandPalette() {
  const { paletteOpen, setPaletteOpen, setImportOpen } = useDialogs();
  const nav = useNavigate();
  const toggleMode = useUi((s) => s.toggleMode);
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  const listRef = useRef<HTMLDivElement>(null);
  const term = q.trim().toLowerCase();

  useEffect(() => { if (!paletteOpen) { setQ(""); setActive(0); } }, [paletteOpen]);

  const games = useQuery({
    queryKey: ["palette-games", term], enabled: paletteOpen && term.length >= 2, staleTime: 30_000,
    queryFn: () => api<{ items: GameSummary[] }>(`/api/games?q=${encodeURIComponent(term)}&limit=6`),
  }).data?.items ?? [];

  const go = (to: string) => () => nav(to);
  const base: Item[] = useMemo(() => [
    { id: "home", label: "Home", icon: Home, run: go("/"), group: "Go to" }, { id: "library", label: "Library", icon: Library, run: go("/library"), group: "Go to" },
    { id: "coach", label: "Coach", hint: "practice, openings, endgames", icon: GraduationCap, run: go("/coach"), group: "Go to" }, { id: "play", label: "Play", icon: Swords, run: go("/play"), group: "Go to" },
    { id: "prepare", label: "Prepare against an opponent", icon: Crosshair, run: go("/prepare"), group: "Go to" }, { id: "explorer", label: "Opening explorer", icon: Compass, run: go("/explorer"), group: "Go to" },
    { id: "insights", label: "Insights", icon: BarChart3, run: go("/insights"), group: "Go to" }, { id: "books", label: "Books", icon: BookOpen, run: go("/books"), group: "Go to" },
    { id: "bot", label: "Bot", icon: Bot, run: go("/bot"), group: "Go to" }, { id: "activity", label: "Activity", icon: Activity, run: go("/activity"), group: "Go to" },
    { id: "settings", label: "Settings", icon: Settings, run: go("/settings"), group: "Go to" },
    { id: "import", label: "Import games", hint: "Lichess, Chess.com or a PGN file", icon: Download, run: () => setImportOpen(true), group: "Do" },
    { id: "theme", label: "Switch between light and dark", icon: Moon, run: toggleMode, group: "Do" },
  ], []); // eslint-disable-line react-hooks/exhaustive-deps
  const items: Item[] = useMemo(() => {
    const own = base.filter((i) => !term || (i.label + " " + (i.hint ?? "")).toLowerCase().includes(term));
    const found: Item[] = games.map((g) => ({ id: "g:" + g.id, label: `${g.white} – ${g.black}`, hint: [g.opening, g.date].filter(Boolean).join(" · "), icon: Library, run: () => nav(`/review/${encodeURIComponent(g.id)}`), group: "Your games" }));
    return [...own, ...found];
  }, [base, term, games, nav]);
  useEffect(() => setActive(0), [term]);
  useEffect(() => { listRef.current?.querySelector(`[data-i="${active}"]`)?.scrollIntoView({ block: "nearest" }); }, [active]);

  const choose = (i: Item | undefined) => { if (!i) return; setPaletteOpen(false); i.run(); };
  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(items.length - 1, a + 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(0, a - 1)); }
    else if (e.key === "Enter") { e.preventDefault(); choose(items[active]); }
  };
  let last = "";
  return (
    <Dialog.Root open={paletteOpen} onOpenChange={setPaletteOpen}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-[#0b1118]/45" />
        <Dialog.Content aria-describedby={undefined} className="fixed left-1/2 top-[14vh] z-50 w-[min(92vw,560px)] -translate-x-1/2 overflow-hidden rounded-[12px] border border-border bg-surface shadow-[var(--shadow)]">
          <Dialog.Title className="sr-only">Search and commands</Dialog.Title>
          <div className="flex items-center gap-2.5 border-b border-border px-4">
            <Search size={16} className="shrink-0 text-faint" />
            <input autoFocus value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={onKeyDown} placeholder="Jump to a page, or search your games" aria-label="Search and commands" role="combobox" aria-expanded aria-controls="palette-list" aria-activedescendant={items[active] ? `pal-${active}` : undefined}
              className="h-12 w-full bg-transparent text-[14px] text-text outline-none placeholder:text-faint" />
            <kbd className="shrink-0 rounded border border-border px-1.5 py-0.5 text-[11px] text-faint">Esc</kbd>
          </div>
          <div ref={listRef} id="palette-list" role="listbox" aria-label="Results" className="max-h-[48vh] overflow-y-auto p-1.5">
            {items.length === 0 && <p className="px-3 py-8 text-center text-[13px] text-muted">Nothing found for “{q}”.</p>}
            {items.map((it, i) => {
              const head = it.group !== last ? it.group : null;
              last = it.group;
              return (
                <div key={it.id}>
                  {head && <div className="px-2.5 pb-1 pt-2.5 text-[11px] font-semibold uppercase tracking-[0.06em] text-faint">{head}</div>}
                  <div id={`pal-${i}`} data-i={i} role="option" aria-selected={i === active} onMouseMove={() => setActive(i)} onClick={() => choose(it)}
                    className={"flex h-9 cursor-pointer items-center gap-2.5 rounded-[6px] px-2.5 text-[13.5px] " + (i === active ? "bg-surface-2 text-text" : "text-muted")}>
                    <it.icon size={16} strokeWidth={1.7} className={i === active ? "text-accent" : ""} />
                    <span className="truncate font-medium text-text">{it.label}</span>
                    {it.hint && <span className="ml-1 truncate text-[12.5px] text-faint">{it.hint}</span>}
                  </div>
                </div>
              );
            })}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
