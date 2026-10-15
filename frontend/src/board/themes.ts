export interface BoardTheme { id: string; name: string; light: string; dark: string; grain: boolean; image?: string }

/** Board colour themes: original palettes. A custom pair of colours is also possible (see the settings). */
export const BOARD_THEMES: BoardTheme[] = [
  { id: "icy", name: "Icy", light: "#dbe6ee", dark: "#8aa3b8", grain: true },
  { id: "moss", name: "Moss", light: "#e6ead3", dark: "#7b9b6c", grain: true },
  { id: "walnut", name: "Walnut", light: "#ecd9b8", dark: "#ad7f58", grain: true },
  { id: "sand", name: "Sand", light: "#f1e6cb", dark: "#c9a676", grain: true },
  { id: "dusk", name: "Dusk", light: "#e5dcec", dark: "#8d78a5", grain: false },
  { id: "slate", name: "Neutral", light: "#cfd3d7", dark: "#6c7782", grain: false },
  { id: "latte", name: "Latte", light: "#e6e9ef", dark: "#8c8fa1", grain: false },
  { id: "mocha", name: "Mocha", light: "#9399b2", dark: "#45475a", grain: false },
  { id: "ink", name: "Ink", light: "#f2f2f2", dark: "#595959", grain: false },
];
export const DEFAULT_BOARD = BOARD_THEMES[0];

export interface Palette { id: string; name: string; swatch: string }
/** Website palettes; every one has a light and a dark mode. */
export const PALETTES: Palette[] = [
  { id: "slate", name: "Studio", swatch: "#1b7a4b" },
  { id: "catppuccin", name: "Catppuccin", swatch: "#388a26" },
  { id: "macchiato", name: "Macchiato", swatch: "#1e66f5" },
  { id: "glacier", name: "Glacier", swatch: "#2b6a8c" },
  { id: "paper", name: "Paper", swatch: "#98582b" },
  { id: "forest", name: "Forest", swatch: "#2d7652" },
  { id: "graphite", name: "Graphite", swatch: "#35353f" },
];
export type Mode = "light" | "dark" | "system";
