/** The player's profile as the server builds it (`/api/profile`). */
export type Colour = "white" | "black";
export interface Bucket { games: number; score: number | null }
export interface Estimate { rating: number; low: number; high: number; moves: number; games: number }
export interface ProfileSummary {
  games: number; analysed: number; wins: number; draws: number; losses: number; score: number | null; accuracy: number | null; mistakesPerGame: number | null;
  performance: Estimate | null; performanceByResult: number | null; against: Record<"stronger" | "similar" | "weaker", Bucket>; ratings: Record<string, { date: string; rating: number }[]>;
}
export interface OpeningRow { name: string; colour: Colour; games: number; score: number | null; wins: number; draws: number; losses: number; accuracy: number | null; earlyMistakes: number | null; after12: number | null; last: string | null; weak: boolean; strong: boolean }
export interface Habits {
  weekday: ({ name: string } & Bucket)[]; timeOfDay: ({ name: string } & Bucket)[]; sessionPlace: ({ place: number; accuracy: number | null } & Bucket)[];
  afterWin: Bucket; afterLoss: Bucket; afterTwoLosses: Bucket; sessions: number; sentences: string[];
}
export interface Rate { moves: number; mistake_rate: number; mean_loss: number; z: number | null }
export interface Tactic { motif: string; name: string; found: number; missed: number; allowed: number }
export interface TacticExample { game: string; ply: number; fen: string; played: string; playedUci: string; best: string; bestSan: string; motif: string; loss: number }
export interface Deep {
  games: number; moves: number;
  weakness?: { profile: { moves: number; by_phase?: Record<string, Rate>; by_situation?: Record<string, Rate>; kinds?: Record<string, { count: number; share: number }> }; sentences: string[]; reference: { band: number; speed: string; comparable: boolean } | null };
  endgames?: { type: string; moves: number; games: number; mistakeRate: number; meanLoss: number; weak: boolean }[];
  time?: { games: number; flagLosses: number; losses: number; troubleShare?: number; scoreInTrouble?: number | null; scoreOtherwise?: number | null; mistakeRateLow?: number | null; mistakeRateOk?: number | null };
  conversion?: { hadWinning: number; converted: number; wasLosing: number; saved: number };
  accuracyByPhase?: Record<string, number | null>;
  tactics?: { table: Tactic[]; examples: TacticExample[] };
  quality?: { month: string; moves: number; good: number; mistakesPer100: number; accuracy: number | null }[];
  opportunism?: { opportunism: number | null; opportunismN: number; luck: number | null; luckN: number };
}
export interface Profile { filters: { speed: string | null; colour: string | null; days: number | null }; summary: ProfileSummary; openings: OpeningRow[]; habits: Habits; deep: Deep }
