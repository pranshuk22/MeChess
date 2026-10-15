import { create } from "zustand";

/** dialogs that can be opened from anywhere (the import dialog from the home page, the library or the sidebar) */
export const useDialogs = create<{ importOpen: boolean; setImportOpen: (v: boolean) => void }>((set) => ({ importOpen: false, setImportOpen: (v) => set({ importOpen: v }) }));
