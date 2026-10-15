/** The preparation report as the server builds it (`chessme.prep.report`): plain data, typed here by hand because the report is a free-form document. */
export type Colour = "white" | "black";

export interface PlanNode {
  san: string; uci: string; by: "you" | "opp"; fen: string; engine: number; reach: number; children: PlanNode[];
  value?: number; cost?: number; p?: number; games?: number; score?: number | null; loss?: number;
  yourGames?: number; yourScore?: number | null; alts?: { san: string; value: number; engine: number; games: number }[];
  usual?: { san: string; games: number; score: number | null } | null;
}
export interface PlanTree { fen: string; value: number; engine: number; gain: number; children: PlanNode[] }
export interface MatchupRow { name: string; theirGames: number; theirScore: number | null; yourGames: number; yourScore: number | null; weak: boolean }
export interface Plan { tree: PlanTree | null; reason?: string; lines?: { moves: string; p: number; value: number | null }[]; pgn?: string; matchup?: MatchupRow[] }

export interface Family {
  name: string; games: number; share: number; score: number | null; wins: number; draws: number; losses: number; analysed: number;
  earlyMistakes: number | null; meanLoss: number | null; below: number | null; weak: boolean; why: string[]; last: string | null;
}
export interface Openings { overall: number | null; games: number; families: Family[] }

export interface Trap {
  path: string; fen: string; fenAfter: string; move: string; uci: string; games: number; visits: number; share: number; loss: number;
  better: string | null; betterUci: string | null; punish: string | null; punishUci: string | null; punishLine: string[];
  youStand: number; score: number | null; yourWorstLoss: number; sound: boolean; ply: number;
}

export interface Rate { moves: number; mistake_rate: number; mean_loss: number; z: number | null }
export interface Moment { game: string; fen: string; played: string; best: string | null; uci: string; loss: number; phase: string; ply: number; kind: string | null; situation: string; url?: string | null }
export interface Weakness {
  games: number; moves: number; sentences: string[]; referenceSentences: string[];
  profile: { moves: number; mistake_rate?: number; blunder_rate?: number; by_phase?: Record<string, Rate>; by_situation?: Record<string, Rate>; kinds?: Record<string, { count: number; share: number }> };
  endgames: { type: string; moves: number; games: number; mistakeRate: number; meanLoss: number; weak: boolean }[];
  time: { games: number; flagLosses: number; losses: number; troubleShare?: number; scoreInTrouble?: number | null; scoreOtherwise?: number | null; mistakeRateLow?: number | null; mistakeRateOk?: number | null; lowMoves?: number };
  conversion: { hadWinning: number; converted: number; wasLosing: number; saved: number };
  moments: Moment[];
}
export interface RecentGame { id: string; url: string | null; date: string | null; colour: Colour; score: number | null; opening: string | null; speed: string | null; plies: number; rating: number | null; against: number | null }

export interface Report {
  opponent: { games: number; white: number; black: number; speeds: Record<string, number>; rating: number | null; from: string | null; to: string | null; score: number | null; handles: { site: string; name: string }[] };
  openings: Record<Colour, Openings>;
  you: { games: number; rating: number | null; white: Openings; black: Openings };
  traps: Record<Colour, Trap[]>;                                   // keyed by the OPPONENT's colour
  plan: Record<Colour, Plan>;                                      // keyed by YOUR colour
  weakness: Weakness;
  headline: string[];
  notes: string[];
  recent: RecentGame[];
  made: { depth: string; nodes: number; at: string; fullGames: number };
  searches: number;
}

export interface PrepRow { id: string; title: string; status: "running" | "done" | "failed"; error: string | null; handles: { site: string; name: string }[]; games: number | null; rating: number | null; createdAt: string | null; updatedAt: string | null }
export interface PrepDetail extends PrepRow { report: Report | null; downloaded: number; analysed: number; job: { id: string; status: string; progress: number; message: string | null } | null }
