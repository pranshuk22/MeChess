import { create } from "zustand";

export const useDialogs = create<{ importOpen: boolean; setImportOpen: (v: boolean) => void; paletteOpen: boolean; setPaletteOpen: (v: boolean) => void }>((set) => ({
  importOpen: false, setImportOpen: (v) => set({ importOpen: v }),
  paletteOpen: false, setPaletteOpen: (v) => set({ paletteOpen: v }),
}));
