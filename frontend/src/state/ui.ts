import { create } from "zustand";
import { DEFAULT_PIECE_SET, PIECE_SETS, type PieceSet } from "@/board/pieces";

type Theme = "light" | "dark";
const read = (k: string): string | null => { try { return localStorage.getItem(k); } catch { return null; } };
const write = (k: string, v: string) => { try { localStorage.setItem(k, v); } catch { /* private mode: the choice just is not remembered */ } };

interface UiState {
  theme: Theme;
  pieceSetId: string;
  showCoords: boolean;
  toggleTheme: () => void;
  setPieceSet: (id: string) => void;
  setShowCoords: (v: boolean) => void;
  pieceSet: () => PieceSet;
}

export const useUi = create<UiState>((set, get) => ({
  theme: (document.documentElement.dataset.theme as Theme) ?? "light",
  pieceSetId: read("mechess.pieces") ?? DEFAULT_PIECE_SET.id,
  showCoords: read("mechess.coords") !== "0",
  toggleTheme: () => {
    const next: Theme = get().theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    write("mechess.theme", next);
    set({ theme: next });
  },
  setPieceSet: (id) => { write("mechess.pieces", id); set({ pieceSetId: id }); },
  setShowCoords: (v) => { write("mechess.coords", v ? "1" : "0"); set({ showCoords: v }); },
  pieceSet: () => PIECE_SETS.find((p) => p.id === get().pieceSetId) ?? DEFAULT_PIECE_SET,
}));
