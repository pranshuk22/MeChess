import * as Popover from "@radix-ui/react-popover";
import clsx from "clsx";
import { Check, Palette } from "lucide-react";
import { BOARD_THEMES, PALETTES, type BoardTheme, type Mode } from "@/board/themes";
import { pieceSets } from "@/board/pieces";
import { useUi } from "@/state/ui";
import { IconButton } from "./ui/IconButton";

const swatchBg = (t: Pick<BoardTheme, "light" | "dark">) => `conic-gradient(${t.dark} 25%, ${t.light} 0 50%, ${t.dark} 0 75%, ${t.light} 0) 0 0 / 24px 24px`;

function Choice({ selected, onClick, label, children }: { selected: boolean; onClick: () => void; label: string; children: React.ReactNode }) {
  return (
    <button onClick={onClick} aria-pressed={selected} aria-label={label} title={label}
      className={clsx("relative flex flex-col items-center gap-1 rounded-lg border p-1.5 text-[11.5px] cursor-pointer", selected ? "border-accent bg-accent-soft" : "border-border hover:border-[var(--border-strong)] hover:bg-surface-2")}>
      {children}
      <span className="max-w-full truncate">{label}</span>
      {selected && <Check size={12} className="absolute right-1 top-1 text-accent" />}
    </button>
  );
}
const Heading = ({ children }: { children: React.ReactNode }) => <div className="mb-1.5 mt-4 text-[11.5px] font-semibold uppercase tracking-wide text-faint first:mt-0">{children}</div>;

/** Board and piece choices (the quick switcher next to the board). */
export function BoardAndPieces() {
  const ui = useUi();
  const sets = pieceSets();
  return (
    <div>
      <Heading>Board</Heading>
      <div className="grid grid-cols-4 gap-1.5">
        {BOARD_THEMES.map((t) => (
          <Choice key={t.id} selected={ui.boardId === t.id} onClick={() => ui.setBoard(t.id)} label={t.name}><span className="block h-9 w-full rounded" style={{ background: swatchBg(t) }} /></Choice>
        ))}
        {ui.custom && <Choice selected={ui.boardId === "custom"} onClick={() => ui.setBoard("custom")} label="Custom"><span className="block h-9 w-full rounded" style={{ background: swatchBg(ui.custom) }} /></Choice>}
      </div>
      <div className="mt-2.5 flex items-center gap-3 text-[12.5px]">
        <label className="flex items-center gap-1.5">Light <input type="color" aria-label="Light squares" value={ui.custom?.light ?? "#dbe6ee"} onChange={(e) => ui.setCustom({ light: e.target.value, dark: ui.custom?.dark ?? "#8aa3b8" })} className="h-6 w-8 cursor-pointer rounded border border-border bg-transparent p-0" /></label>
        <label className="flex items-center gap-1.5">Dark <input type="color" aria-label="Dark squares" value={ui.custom?.dark ?? "#8aa3b8"} onChange={(e) => ui.setCustom({ dark: e.target.value, light: ui.custom?.light ?? "#dbe6ee" })} className="h-6 w-8 cursor-pointer rounded border border-border bg-transparent p-0" /></label>
        <label className="ml-auto flex items-center gap-1.5"><input type="checkbox" checked={ui.grain} onChange={(e) => ui.setGrain(e.target.checked)} className="accent-[var(--accent)]" /> Texture</label>
      </div>

      <Heading>Pieces</Heading>
      <div className="grid grid-cols-3 gap-1.5">
        {sets.map((s) => (
          <Choice key={s.id} selected={ui.pieceSetId === s.id} onClick={() => ui.setPieceSet(s.id)} label={s.name}>
            <span className="flex h-9 items-center justify-center rounded px-1" style={{ background: swatchBg({ light: "#dbe6ee", dark: "#8aa3b8" }) }}>
              {(["wN", "bQ", "wK"] as const).map((k) => <img key={k} alt="" width={26} height={26} src={s.url({ colour: k[0] as "w" | "b", role: k[1].toLowerCase() as "n" | "q" | "k" })} />)}
            </span>
          </Choice>
        ))}
      </div>
    </div>
  );
}

/** Website appearance: mode (light, dark or system) and palette; every palette has both modes. */
export function SiteAppearance() {
  const { mode, setMode, palette, setPalette } = useUi();
  return (
    <div>
      <Heading>Mode</Heading>
      <div role="group" aria-label="Mode" className="inline-flex rounded-md border border-border bg-surface p-0.5">
        {(["light", "dark", "system"] as Mode[]).map((m) => (
          <button key={m} onClick={() => setMode(m)} aria-pressed={mode === m} className={clsx("h-8 rounded px-3 text-[13px] font-medium capitalize cursor-pointer", mode === m ? "bg-accent-soft text-accent" : "text-muted hover:text-text")}>{m}</button>
        ))}
      </div>
      <Heading>Colours</Heading>
      <div className="grid grid-cols-4 gap-1.5">
        {PALETTES.map((p) => (
          <Choice key={p.id} selected={palette === p.id} onClick={() => setPalette(p.id)} label={p.name}>
            <span className="grid h-9 w-full place-items-center rounded" style={{ background: "linear-gradient(90deg, #ffffff 50%, #15191c 50%)" }}><span className="h-4 w-4 rounded-full" style={{ background: p.swatch }} /></span>
          </Choice>
        ))}
      </div>
    </div>
  );
}

/** The quick switcher: a button beside the board that opens board and piece choices. */
export function AppearanceButton() {
  return (
    <Popover.Root>
      <Popover.Trigger asChild><IconButton label="Board and pieces"><Palette size={18} /></IconButton></Popover.Trigger>
      <Popover.Portal>
        <Popover.Content side="top" align="end" sideOffset={8} className="z-50 w-[320px] rounded-xl border border-border bg-surface p-4 shadow-xl"><BoardAndPieces /></Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
