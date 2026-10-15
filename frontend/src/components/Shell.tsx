import clsx from "clsx";
import { Activity, BookOpen, ChevronsLeft, Compass, GraduationCap, Home, Library, Moon, PanelLeft, Settings, Sun, Swords, User } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { useJobEvents, useRunningJobs, useWorkspace } from "@/api/hooks";
import { ServerDown } from "./ServerDown";
import { ImportDialog } from "@/features/library/ImportDialog";
import { resolveMode, useUi } from "@/state/ui";
import { TipProvider, Tip } from "./ui/Tip";

const GROUPS = [
  { label: "Overview", items: [{ to: "/", label: "Home", icon: Home, end: true }, { to: "/library", label: "Library", icon: Library }] },
  { label: "Train", items: [{ to: "/coach", label: "Coach", icon: GraduationCap }, { to: "/play", label: "Play", icon: Swords }] },
  { label: "Explore", items: [{ to: "/explorer", label: "Explorer", icon: Compass }, { to: "/style", label: "Profile", icon: User }, { to: "/books", label: "Books", icon: BookOpen }] },
];

function Mark({ size = 28 }: { size?: number }) {
  return (
    <span className="grid shrink-0 place-items-center rounded-[9px] bg-accent text-[var(--accent-text)] shadow-[inset_0_1px_0_rgba(255,255,255,0.18)]" style={{ width: size, height: size }} aria-hidden>
      <svg viewBox="0 0 32 32" width={size * 0.68} height={size * 0.68}><path d="M16 5.5v3.4m-1.8-1.7h3.6M11.6 26h8.8l-1.1-4.4c2.1-.9 3.4-3 3.4-5.6 0-2.1-1-4.1-2.9-5.4h-7.6c-1.9 1.3-2.9 3.300-2.9 5.400 0 2.600 1.300 4.700 3.400 5.600z" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" /></svg>
    </span>
  );
}

export function Shell() {
  useJobEvents();
  const health = useQuery({ queryKey: ["health"], queryFn: () => api("/api/health"), retry: false, refetchInterval: (q) => (q.state.status === "error" ? 3000 : 20000) });
  const { mode, toggleMode } = useUi();
  const dark = resolveMode(mode) === "dark";
  const qc = useQueryClient();
  const wasDown = useRef(false);
  useEffect(() => { if (health.isError) wasDown.current = true; else if (health.isSuccess && wasDown.current) { wasDown.current = false; qc.invalidateQueries(); } }, [health.isError, health.isSuccess, qc]);   // the server came back: fetch everything again
  const running = useRunningJobs();
  const engine = useWorkspace().data?.checks.find((c) => c.id === "engine");
  const [collapsed, setCollapsed] = useState(() => { try { return localStorage.getItem("mechess.rail") === "1"; } catch { return false; } });
  const toggle = () => setCollapsed((c) => { try { localStorage.setItem("mechess.rail", c ? "0" : "1"); } catch { /* not remembered */ } return !c; });

  const link = (to: string, label: string, Icon: typeof Home, opts: { end?: boolean; badge?: number } = {}) => (
    <Tip key={to} label={label} side="right">
      <NavLink to={to} end={opts.end} aria-label={label}
        className={({ isActive }) => clsx("group relative flex h-9 items-center gap-3 rounded-[9px] px-2.5 text-[13.5px] font-medium transition-colors", collapsed && "justify-center px-0",
          isActive ? "bg-[var(--rail-active)] text-[var(--rail-strong)]" : "text-[var(--rail-text)] hover:bg-[var(--rail-hover)] hover:text-[var(--rail-strong)]")}>
        {({ isActive }) => (<>
          {isActive && <span className="absolute -left-3 top-2 h-5 w-[3px] rounded-r-full bg-accent max-md:hidden" />}
          <Icon size={18} strokeWidth={1.7} className="shrink-0" />
          {!collapsed && <span className="truncate">{label}</span>}
          {!!opts.badge && <span className={clsx("grid h-[18px] min-w-[18px] place-items-center rounded-full bg-accent px-1 text-[10.5px] font-semibold text-[var(--accent-text)]", collapsed ? "absolute right-1 top-0.5" : "ml-auto")}>{opts.badge}</span>}
        </>)}
      </NavLink>
    </Tip>
  );

  return (
    <TipProvider>
      <div className="grid h-full max-md:grid-cols-1 max-md:grid-rows-[1fr_60px]" style={{ gridTemplateColumns: `${collapsed ? 68 : 232}px 1fr` }}>
        <nav aria-label="Main" className="flex min-h-0 flex-col bg-[var(--rail-bg)] px-3 py-4 max-md:order-2 max-md:flex-row max-md:items-center max-md:justify-around max-md:px-1 max-md:py-0">
          <div className={clsx("mb-5 flex items-center gap-2.5 px-1 max-md:hidden", collapsed && "justify-center px-0")}>
            <Mark />
            {!collapsed && <span className="font-display text-[15px] font-semibold tracking-[-0.04em] text-[var(--rail-strong)]">MeChess</span>}
          </div>
          <div className="min-h-0 flex-1 space-y-5 overflow-y-auto max-md:flex max-md:flex-none max-md:space-y-0 max-md:overflow-visible">
            {GROUPS.map((g, i) => (
              <div key={g.label} className="space-y-0.5 max-md:flex max-md:space-y-0">
                {!collapsed && <div className="mb-1.5 px-2.5 font-display text-[10.5px] font-semibold uppercase tracking-[0.07em] text-[var(--rail-text)] opacity-60 max-md:hidden">{g.label}</div>}
                {collapsed && i > 0 && <div className="mx-2 mb-2 h-px bg-[var(--rail-line)] max-md:hidden" />}
                {g.items.map((it) => link(it.to, it.label, it.icon, { end: (it as { end?: boolean }).end }))}
              </div>
            ))}
          </div>
          <div className="mt-3 space-y-0.5 border-t border-[var(--rail-line)] pt-3 max-md:hidden">
            {link("/activity", "Activity", Activity, { badge: running.length || undefined })}
            {link("/settings", "Settings", Settings)}
            <Tip label={dark ? "Light mode" : "Dark mode"} side="right">
              <button onClick={toggleMode} aria-label={dark ? "Light mode" : "Dark mode"} className={clsx("flex h-9 w-full items-center gap-3 rounded-[9px] px-2.5 text-[13.5px] font-medium text-[var(--rail-text)] transition-colors hover:bg-[var(--rail-hover)] hover:text-[var(--rail-strong)] cursor-pointer", collapsed && "justify-center px-0")}>
                {dark ? <Sun size={18} strokeWidth={1.7} /> : <Moon size={18} strokeWidth={1.7} />}{!collapsed && <span>{dark ? "Light mode" : "Dark mode"}</span>}
              </button>
            </Tip>
            <div className={clsx("flex items-center gap-2 px-2.5 pt-2 text-[12px] text-[var(--rail-text)]", collapsed && "justify-center px-0")} title={engine?.detail}>
              <span className={clsx("h-2 w-2 shrink-0 rounded-full", engine?.state === "ok" ? "bg-[var(--q-best)]" : engine ? "bg-[var(--q-inaccuracy)]" : "bg-[var(--faint)]")} />
              {!collapsed && <span className="truncate">{engine ? (engine.state === "ok" ? engine.detail : "Engine not found") : "Checking engine…"}</span>}
              {!collapsed && <button onClick={toggle} aria-label="Collapse the sidebar" className="ml-auto rounded p-1 hover:bg-[var(--rail-hover)] cursor-pointer"><ChevronsLeft size={15} /></button>}
            </div>
            {collapsed && <button onClick={toggle} aria-label="Expand the sidebar" className="mx-auto mt-1 flex h-8 w-8 items-center justify-center rounded-md text-[var(--rail-text)] hover:bg-[var(--rail-hover)] cursor-pointer"><PanelLeft size={16} /></button>}
          </div>
        </nav>
        <main className="min-h-0 overflow-auto">{health.isError ? <ServerDown onRetry={() => health.refetch()} /> : <Outlet />}</main>
      </div>
      <ImportDialog />
    </TipProvider>
  );
}
