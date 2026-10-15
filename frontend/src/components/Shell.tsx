import clsx from "clsx";
import { Activity, BookOpen, Compass, GraduationCap, Home, Library, Moon, Settings, Sun, Swords, User } from "lucide-react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useUi } from "@/state/ui";
import { IconButton } from "./ui/IconButton";
import { TipProvider } from "./ui/Tip";

const NAV = [
  { to: "/", label: "Home", icon: Home, end: true },
  { to: "/library", label: "Library", icon: Library },
  { to: "/coach", label: "Coach", icon: GraduationCap },
  { to: "/play", label: "Play", icon: Swords },
  { to: "/explorer", label: "Explorer", icon: Compass },
  { to: "/style", label: "Profile", icon: User },
  { to: "/books", label: "Books", icon: BookOpen },
];
const TITLES: Record<string, string> = { "/": "Home", "/library": "Library", "/coach": "Coach", "/play": "Play", "/explorer": "Explorer", "/style": "Profile", "/books": "Books", "/settings": "Settings", "/activity": "Activity" };

export function Shell() {
  const { theme, toggleTheme } = useUi();
  const { pathname } = useLocation();
  const title = pathname.startsWith("/review") ? "Review" : TITLES[pathname] ?? "";
  return (
    <TipProvider>
      <div className="grid h-full grid-cols-[72px_1fr] grid-rows-[52px_1fr] max-md:grid-cols-1 max-md:grid-rows-[52px_1fr_56px]">
        <nav aria-label="Main" className="row-span-2 flex flex-col items-center gap-1 border-r border-border bg-surface py-3 max-md:order-3 max-md:row-span-1 max-md:flex-row max-md:justify-around max-md:border-r-0 max-md:border-t max-md:py-0">
          <div className="mb-3 grid h-9 w-9 place-items-center rounded-lg bg-[#26323b] text-[#dbe6ee] max-md:hidden" aria-hidden>
            <svg viewBox="0 0 32 32" width="22" height="22"><path d="M16 6v4m-2-2h4M12 25h8l-1-4c2-1 3-3 3-6 0-2-1-4-3-5h-6c-2 1-3 3-3 5 0 3 1 5 3 6z" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" strokeLinecap="round" /></svg>
          </div>
          {NAV.slice(0, 5).map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end} className={({ isActive }) => clsx("flex w-14 flex-col items-center gap-0.5 rounded-lg py-2 text-[11px] font-medium transition-colors", isActive ? "bg-accent-soft text-accent" : "text-muted hover:bg-surface-2 hover:text-text")}>
              <Icon size={20} strokeWidth={1.8} /> {label}
            </NavLink>
          ))}
          <div className="mt-auto flex flex-col gap-1 max-md:hidden">
            <NavLink to="/settings" className={({ isActive }) => clsx("flex w-14 flex-col items-center gap-0.5 rounded-lg py-2 text-[11px] font-medium", isActive ? "bg-accent-soft text-accent" : "text-muted hover:bg-surface-2 hover:text-text")}><Settings size={20} strokeWidth={1.8} /> Settings</NavLink>
          </div>
        </nav>
        <header className="flex items-center gap-3 border-b border-border bg-surface px-5 max-md:px-3">
          <h1 className="text-[15px] font-semibold">{title}</h1>
          <span className="rounded-full border border-border px-2 py-0.5 text-[11px] text-muted max-sm:hidden" title="This is a prototype: games and analyses shown are sample data">Prototype · sample data</span>
          <div className="ml-auto flex items-center gap-1">
            <NavLink to="/activity"><IconButton label="Activity" tabIndex={-1}><Activity size={18} strokeWidth={1.8} /></IconButton></NavLink>
            <IconButton label={theme === "dark" ? "Light theme" : "Dark theme"} onClick={toggleTheme}>{theme === "dark" ? <Sun size={18} strokeWidth={1.8} /> : <Moon size={18} strokeWidth={1.8} />}</IconButton>
          </div>
        </header>
        <main className="min-h-0 overflow-auto"><Outlet /></main>
      </div>
    </TipProvider>
  );
}
