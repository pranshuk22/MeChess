export type Colour = "w" | "b";
export type Role = "p" | "n" | "b" | "r" | "q" | "k";
export interface PieceInfo { colour: Colour; role: Role }

/** A piece set is one image per piece. */
export interface PieceSet { id: string; name: string; author: string; licence: string; url(p: PieceInfo): string }

// every folder in assets/pieces holds wK.svg ... bP.svg; small files are inlined by the bundler, so a set costs no extra request
const FILES = import.meta.glob("../assets/pieces/*/*.svg", { eager: true, query: "?url", import: "default" }) as Record<string, string>;

const META: Record<string, { name: string; author: string; licence: string }> = {
  cburnett: { name: "Classic", author: "Colin M.L. Burnett", licence: "BSD 3-clause" },
  chessnut: { name: "Chessnut", author: "Alexis Luengas", licence: "Apache 2.0" },
  rhosgfx: { name: "Rhos", author: "RhosGFX", licence: "CC0" },
  celtic: { name: "Celtic", author: "Maurizio Monge", licence: "MIT" },
  "kiwen-suwi": { name: "Kiwen", author: "neverRare", licence: "CC BY 4.0" },
  papercut: { name: "Papercut", author: "Nikolay Anzarov", licence: "CC BY 4.0" },
};
const ORDER = ["cburnett", "chessnut", "rhosgfx", "celtic", "kiwen-suwi", "papercut"];

function build(): PieceSet[] {
  const sets = new Map<string, Record<string, string>>();
  for (const [path, url] of Object.entries(FILES)) {
    const m = path.match(/pieces\/([^/]+)\/([wb][KQRBNP])\.svg$/);
    if (m) (sets.get(m[1]) ?? sets.set(m[1], {}).get(m[1])!)[m[2]] = url;
  }
  return ORDER.filter((id) => sets.has(id)).map((id) => ({ id, ...META[id], url: (p: PieceInfo) => sets.get(id)![p.colour + p.role.toUpperCase()] }));
}
const BUILT = build();
/** all bundled sets (custom sets added by the player come from the backend later) */
export const pieceSets = (): PieceSet[] => BUILT;
export const DEFAULT_PIECE_SET = BUILT[0];
