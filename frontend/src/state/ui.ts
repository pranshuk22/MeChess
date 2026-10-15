import { create } from "zustand";
import { BOARD_THEMES, DEFAULT_BOARD, PALETTES, type BoardTheme, type Mode } from "@/board/themes";
import { customPieceSet, DEFAULT_PIECE_SET, pieceSets, type PieceSet } from "@/board/pieces";
import { useThemes } from "@/api/hooks";

const read = (k: string): string | null => { try { return localStorage.getItem(k); } catch { return null; } };
const write = (k: string, v: string) => { try { localStorage.setItem(k, v); } catch { /* private mode: the choice just is not remembered */ } };

const systemDark = () => typeof matchMedia === "function" && matchMedia("(prefers-color-scheme: dark)").matches;
export const resolveMode = (m: Mode): "light" | "dark" => (m === "system" ? (systemDark() ? "dark" : "light") : m);

export const BOARD_SIZE = { min: 60, max: 130, step: 5, def: 100 };
const clampSize = (n: number) => Math.min(BOARD_SIZE.max, Math.max(BOARD_SIZE.min, Math.round(n / BOARD_SIZE.step) * BOARD_SIZE.step));
const storedSize = () => { const n = Number(read("mechess.boardsize")); return Number.isFinite(n) && n > 0 ? clampSize(n) : BOARD_SIZE.def; };
const applySize = (n: number) => { document.documentElement.style.setProperty("--board-scale", String(n / 100)); };       // every board is sized from this: 100 = the largest that fits the window

function applyDocument(mode: Mode, palette: string) {
  document.documentElement.dataset.theme = resolveMode(mode);
  document.documentElement.dataset.palette = palette;
}

const storedMode = (): Mode => { const v = read("mechess.mode") ?? read("mechess.theme"); return v === "dark" || v === "system" ? v : "light"; };   // light unless the player chose otherwise
const storedPalette = () => { const v = read("mechess.palette"); return PALETTES.some((p) => p.id === v) ? v! : PALETTES[0].id; };
const storedCustom = (): { light: string; dark: string } | null => { try { const v = JSON.parse(read("mechess.board.custom") ?? "null"); return v && /^#[0-9a-f]{6}$/i.test(v.light) && /^#[0-9a-f]{6}$/i.test(v.dark) ? v : null; } catch { return null; } };

interface UiState {
  mode: Mode;
  palette: string;
  boardId: string;
  boardSize: number;
  custom: { light: string; dark: string } | null;
  grain: boolean;
  pieceSetId: string;
  showCoords: boolean;
  setMode: (m: Mode) => void;
  toggleMode: () => void;
  setPalette: (id: string) => void;
  setBoard: (id: string) => void;
  setBoardSize: (n: number) => void;
  setCustom: (c: { light: string; dark: string } | null) => void;
  setGrain: (v: boolean) => void;
  setPieceSet: (id: string) => void;
  setShowCoords: (v: boolean) => void;
}

export const useUi = create<UiState>((set, get) => ({
  mode: storedMode(),
  palette: storedPalette(),
  boardId: read("mechess.board") ?? DEFAULT_BOARD.id,
  boardSize: storedSize(),
  custom: storedCustom(),
  grain: read("mechess.grain") === "1",                                              // flat squares unless the texture is switched on
  pieceSetId: read("mechess.pieces") ?? DEFAULT_PIECE_SET.id,
  showCoords: read("mechess.coords") !== "0",
  setMode: (m) => { write("mechess.mode", m); applyDocument(m, get().palette); set({ mode: m }); },
  toggleMode: () => get().setMode(resolveMode(get().mode) === "dark" ? "light" : "dark"),
  setPalette: (id) => { write("mechess.palette", id); applyDocument(get().mode, id); set({ palette: id }); },
  setBoard: (id) => { write("mechess.board", id); set({ boardId: id }); },
  setBoardSize: (n) => { const v = clampSize(n); write("mechess.boardsize", String(v)); applySize(v); set({ boardSize: v }); },
  setCustom: (c) => { write("mechess.board.custom", JSON.stringify(c)); set({ custom: c, ...(c ? { boardId: "custom" } : {}) }); if (c) write("mechess.board", "custom"); },
  setGrain: (v) => { write("mechess.grain", v ? "1" : "0"); set({ grain: v }); },
  setPieceSet: (id) => { write("mechess.pieces", id); set({ pieceSetId: id }); },
  setShowCoords: (v) => { write("mechess.coords", v ? "1" : "0"); set({ showCoords: v }); },
}));

/** built-in board themes plus the player's own board images */
export function useBoardThemes(): BoardTheme[] {
  const t = useThemes().data;
  return [...BOARD_THEMES, ...(t?.boards ?? []).map((b) => ({ id: "img:" + b.id, name: b.name, light: "#cfd6dc", dark: "#8c98a3", grain: false, image: b.url }))];
}
/** the board theme in effect (a built-in one, one of the player's images, or the player's own pair of colours) */
export function useBoardTheme(): BoardTheme {
  const { boardId, custom, grain } = useUi();
  const all = useBoardThemes();
  const base = boardId === "custom" && custom ? { id: "custom", name: "Custom", light: custom.light, dark: custom.dark, grain: false } : all.find((t) => t.id === boardId) ?? DEFAULT_BOARD;
  return { ...base, grain: base.grain && grain };
}
export function usePieceSets(): PieceSet[] {
  const t = useThemes().data;
  return [...pieceSets(), ...(t?.pieces ?? []).map(customPieceSet)];
}
export function usePieceSet(): PieceSet {
  const id = useUi((s) => s.pieceSetId);
  return usePieceSets().find((p) => p.id === id) ?? DEFAULT_PIECE_SET;
}

// follow the system while the mode is "system"
if (typeof matchMedia === "function") matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { const { mode, palette } = useUi.getState(); if (mode === "system") applyDocument(mode, palette); });

if (typeof document !== "undefined") applySize(storedSize());
