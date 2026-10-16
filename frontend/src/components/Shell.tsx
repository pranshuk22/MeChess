import clsx from "clsx";
import { Activity, BarChart3, Bot, BookOpen, ChevronsLeft, Compass, Crosshair, GraduationCap, Home, Library, Loader2, Moon, PanelLeft, Search, Settings, Sun, Swords } from "lucide-react";
import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { useJobEvents, useMe, useRunningJobs, useWorkspace } from "@/api/hooks";
import { ServerDown } from "./ServerDown";
import { useDialogs } from "@/state/dialogs";
import { resolveMode, useUi } from "@/state/ui";
import { TipProvider, Tip } from "./ui/Tip";

const GROUPS = [
  { label: "Overview", items: [{ to: "/", label: "Home", icon: Home, end: true }, { to: "/library", label: "Library", icon: Library }] },
  { label: "Train", items: [{ to: "/coach", label: "Coach", icon: GraduationCap }, { to: "/play", label: "Play", icon: Swords }, { to: "/prepare", label: "Prepare", icon: Crosshair }] },
  { label: "Explore", items: [{ to: "/explorer", label: "Explorer", icon: Compass }, { to: "/insights", label: "Insights", icon: BarChart3 }, { to: "/books", label: "Books", icon: BookOpen }, { to: "/bot", label: "Bot", icon: Bot }] },
];

function Mark({ size = 26 }: { size?: number }) {
  return (
    <span className="grid shrink-0 place-items-center rounded-[7px] bg-accent text-[var(--accent-text)]" style={{ width: size, height: size }} aria-hidden>
      <svg viewBox="0 0 32 32" width={size * 0.66} height={size * 0.66}><path d="M16 5.5v3.4m-1.8-1.7h3.6M11.6 26h8.8l-1.1-4.4c2.1-.9 3.4-3 3.4-5.6 0-2.1-1-4.1-2.9-5.4h-7.6c-1.9 1.3-2.9 3.300-2.9 5.400 0 2.600 1.300 4.700 3.400 5.600z" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinejoin="round" strokeLinecap="round" /></svg>
    </span>
  );
}

const ImportDialog = lazy(() => import("@/features/library/ImportDialog").then((m) => ({ default: m.ImportDialog })));
const CommandPalette = lazy(() => import("./CommandPalette").then((m) => ({ default: m.CommandPalette })));          // loaded the first time it is opened

const ShortcutsDialog = lazy(() => import("./ShortcutsDialog").then((m) => ({ default: m.ShortcutsDialog })));

const initials = (name?: string | null) => (name ? name.replace(/[^A-Za-z0-9]/g, "").slice(0, 2).toUpperCase() || "ME" : "ME");

export function Shell() {
  useJobEvents();
  const health = useQuery({ queryKey: ["health"], queryFn: () => api<{ ok: boolean; auth: boolean }>("/api/health"), retry: false, refetchInterval: (q) => (q.state.status === "error" ? 3000 : 20000) });
  const { mode, toggleMode } = useUi();
  const dark = resolveMode(mode) === "dark";
  const qc = useQueryClient();
  const wasDown = useRef(false);
  useEffect(() => { if (health.isError) wasDown.current = true; else if (health.isSuccess && wasDown.current) { wasDown.current = false; qc.invalidateQueries(); } }, [health.isError, health.isSuccess, qc]);   // the server came back: fetch everything again
  const running = useRunningJobs();
  const engine = useWorkspace().data?.checks.find((c) => c.id === "engine");
  const me = useMe().data;
  const setPaletteOpen = useDialogs((s) => s.setPaletteOpen), paletteOpen = useDialogs((s) => s.paletteOpen);
  const importOpen = useDialogs((s) => s.importOpen);
  const [importEverOpened, setImportEverOpened] = useState(false);
  useEffect(() => { if (importOpen) setImportEverOpened(true); }, [importOpen]);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  useEffect(() => {                                                                                  // ? opens the list of keyboard shortcuts (not while typing)
    const onKey = (e: KeyboardEvent) => { const t = e.target as HTMLElement; if (e.key === "?" && !e.ctrlKey && !e.metaKey && !t.closest("input, textarea, select, [contenteditable]")) { e.preventDefault(); setShortcutsOpen((v) => !v); } };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  const [paletteLoaded, setPaletteLoaded] = useState(false);
  useEffect(() => { if (paletteOpen) setPaletteLoaded(true); }, [paletteOpen]);
  useEffect(() => {                                                                                  // the shortcut works before the palette's code is loaded
    const onKey = (e: KeyboardEvent) => { if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && e.key.toLowerCase() === "k") { e.preventDefault(); setPaletteLoaded(true); setPaletteOpen(!useDialogs.getState().paletteOpen); } };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [setPaletteOpen]);
  const [collapsed, setCollapsed] = useState(() => { try { return localStorage.getItem("mechess.rail") === "1"; } catch { return false; } });
  const toggle = () => setCollapsed((c) => { try { localStorage.setItem("mechess.rail", c ? "0" : "1"); } catch { /* not remembered */ } return !c; });

  const { pathname } = useLocation();
  /** (The active state is worked out here and a plain class string is given to NavLink: a function as className is turned into text by the tooltip trigger around it.) */
  const link = (to: string, label: string, Icon: typeof Home, opts: { end?: boolean; badge?: number } = {}) => {
    const isActive = opts.end ? pathname === to : pathname === to || pathname.startsWith(to + "/");
    return (
      <Tip key={to} label={label} side="right">
        <NavLink to={to} end={opts.end} aria-label={label} aria-current={isActive ? "page" : undefined}
          className={clsx("group relative flex h-8 items-center gap-2.5 rounded-[6px] px-2.5 text-[13.5px] font-medium transition-colors", collapsed && "justify-center px-0", ["/insights", "/books", "/bot", "/prepare"].includes(to) && "max-md:hidden", "max-md:h-auto max-md:flex-col max-md:justify-center max-md:gap-0.5 max-md:px-0 max-md:text-[10.5px]",
            isActive ? "bg-[var(--rail-active)] text-[var(--rail-strong)]" : "text-[var(--rail-text)] hover:bg-[var(--rail-hover)] hover:text-[var(--rail-strong)]")}>
          <Icon size={17} strokeWidth={1.75} className={clsx("shrink-0", isActive && "text-accent")} />
          {!collapsed && <span className="truncate">{label}</span>}
          {!!opts.badge && <span className={clsx("grid h-[18px] min-w-[18px] place-items-center rounded-full bg-accent px-1 text-[10.5px] font-semibold text-[var(--accent-text)]", collapsed ? "absolute right-1 top-0.5" : "ml-auto")}>{opts.badge}</span>}
        </NavLink>
      </Tip>
    );
  };

  return (
    <TipProvider>
      <div className="grid h-full grid-cols-1 grid-rows-[minmax(0,1fr)_60px] md:grid-cols-[var(--rail-w)_minmax(0,1fr)] md:grid-rows-1" style={{ "--rail-w": `${collapsed ? 60 : 224}px` } as React.CSSProperties}>
        <nav aria-label="Main" className="flex min-h-0 flex-col border-r border-[var(--rail-line)] bg-[var(--rail-bg)] px-2.5 py-3 max-md:order-2 max-md:grid max-md:auto-cols-fr max-md:grid-flow-col max-md:items-stretch max-md:border-r-0 max-md:border-t max-md:px-1 max-md:py-0">
          <div className={clsx("mb-4 flex h-8 items-center gap-2.5 px-1.5 max-md:hidden", collapsed && "justify-center px-0")}>
            <Mark />
            {!collapsed && <span className="text-[15px] font-semibold tracking-[-0.02em] text-[var(--rail-strong)]">MeChess</span>}
          </div>
          <div className="min-h-0 flex-1 space-y-4 overflow-y-auto max-md:contents">
            {GROUPS.map((g, i) => (
              <div key={g.label} className="space-y-0.5 max-md:contents">
                {!collapsed && <div className="mb-1 px-2.5 text-[11px] font-semibold uppercase tracking-[0.06em] text-[var(--rail-text)] max-md:hidden">{g.label}</div>}
                {collapsed && i > 0 && <div className="mx-2 mb-2 h-px bg-[var(--rail-line)] max-md:hidden" />}
                {g.items.map((it) => link(it.to, it.label, it.icon, { end: (it as { end?: boolean }).end }))}
              </div>
            ))}
          </div>
          <div className="hidden max-md:contents">{link("/settings", "Settings", Settings)}</div>
          <div className="mt-3 space-y-0.5 border-t border-[var(--rail-line)] pt-3 max-md:hidden">
            {link("/activity", "Activity", Activity, { badge: running.length || undefined })}
            {link("/settings", "Settings", Settings)}
            <Tip label={me?.name ? `${me.name}${me.rating ? ` · ${me.rating}` : ""}` : "Your profile"} side="right">
              <NavLink to="/settings" aria-label="Your profile" className={clsx("mt-2 flex items-center gap-2.5 rounded-[6px] px-1.5 py-1.5 transition-colors hover:bg-[var(--rail-hover)]", collapsed && "justify-center px-0")}>
                <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-accent-soft text-[11px] font-semibold text-accent">{initials(me?.name)}</span>
                {!collapsed && <span className="min-w-0 leading-tight"><span className="block truncate text-[13px] font-medium text-[var(--rail-strong)]">{me?.name ?? "Your profile"}</span><span className="block truncate text-[11.5px] text-[var(--rail-text)]">{me?.rating ? `${me.rating}${me.mainSpeed ? ` · ${me.mainSpeed}` : ""}` : "add your name in Settings"}</span></span>}
              </NavLink>
            </Tip>
            <div className={clsx("flex items-center gap-2 px-2.5 pt-2 text-[12px] text-[var(--rail-text)]", collapsed && "justify-center px-0")} title={engine?.detail}>
              <span className={clsx("h-2 w-2 shrink-0 rounded-full", engine?.state === "ok" ? "bg-[var(--q-best)]" : engine ? "bg-[var(--q-inaccuracy)]" : "bg-[var(--faint)]")} />
              {!collapsed && <span className="truncate">{engine ? (engine.state === "ok" ? engine.detail : "Engine not found") : "Checking engine…"}</span>}
              {!collapsed && <button onClick={toggle} aria-label="Collapse the sidebar" className="ml-auto rounded p-1 hover:bg-[var(--rail-hover)] cursor-pointer"><ChevronsLeft size={15} /></button>}
            </div>
            {collapsed && <button onClick={toggle} aria-label="Expand the sidebar" className="mx-auto mt-1 flex h-8 w-8 items-center justify-center rounded-md text-[var(--rail-text)] hover:bg-[var(--rail-hover)] cursor-pointer"><PanelLeft size={16} /></button>}
          </div>
        </nav>
        <div className="flex min-h-0 min-w-0 flex-col max-md:order-1">
          <header className="flex h-12 shrink-0 items-center gap-3 border-b border-border bg-surface px-4 max-md:h-11 max-md:px-3">
            <span className="hidden max-md:block"><Mark size={24} /></span>
            <button onClick={() => setPaletteOpen(true)} aria-label="Search and commands (Ctrl or Cmd plus K)" className="flex h-8 w-full max-w-[380px] cursor-pointer items-center gap-2 rounded-[6px] border border-border bg-bg px-2.5 text-[13px] text-faint transition-colors hover:border-[var(--border-strong)]">
              <Search size={15} /><span className="truncate">Search or jump to…</span><kbd className="ml-auto hidden rounded border border-border bg-surface px-1.5 text-[11px] text-faint md:block">{typeof navigator !== "undefined" && /Mac/i.test(navigator.platform) ? "⌘K" : "Ctrl K"}</kbd>
            </button>
            <div className="ml-auto flex items-center gap-1">
              {running.length > 0 && <NavLink to="/activity" className="flex h-8 items-center gap-1.5 rounded-[6px] px-2.5 text-[12.5px] font-medium text-muted hover:bg-surface-2" aria-label={`${running.length} background job${running.length === 1 ? "" : "s"} running`}><Loader2 size={14} className="animate-spin text-accent" />{running.length} running</NavLink>}
              <Tip label={dark ? "Light mode" : "Dark mode"}>
                <button onClick={toggleMode} aria-label={dark ? "Light mode" : "Dark mode"} className="grid h-8 w-8 cursor-pointer place-items-center rounded-[6px] text-muted transition-colors hover:bg-surface-2 hover:text-text">{dark ? <Sun size={16} strokeWidth={1.75} /> : <Moon size={16} strokeWidth={1.75} />}</button>
              </Tip>
            </div>
          </header>
          <main tabIndex={0} aria-label="Page" className="min-h-0 min-w-0 flex-1 overflow-auto focus-visible:outline-none">{health.isError ? <ServerDown onRetry={() => health.refetch()} /> : health.data?.auth === false ? <ServerDown signedOut onRetry={() => health.refetch()} /> : <Outlet />}</main>
        </div>
      </div>
      {importEverOpened && <Suspense fallback={null}><ImportDialog /></Suspense>}
      {shortcutsOpen && <Suspense fallback={null}><ShortcutsDialog open={shortcutsOpen} onOpenChange={setShortcutsOpen} /></Suspense>}
      {paletteLoaded && <Suspense fallback={null}><CommandPalette /></Suspense>}
    </TipProvider>
  );
}
