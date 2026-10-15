// Generated from the API's OpenAPI schema by tools/gen_ts_types.py: do not edit.

export interface Accounts {
  lichess?: string | null;
  chesscom?: string | null;
}

export interface Accuracy {
  white: number;
  black: number;
}

export interface AccuracyStats {
  recent: number | null;
  previous: number | null;
  series: number[];
}

export interface AnalyseRequest {
  ids?: string[] | null;
  limit?: number | null;
  nodes?: number | null;
}

export interface Attempt {
  uci: string;
  tries: number;
  hints: number;
}

export interface CacheBuild {
  min_count: number;
  limit: number;
  include_theory: boolean;
  nodes: number | null;
}

export interface CacheMove {
  move: number;
  positions: number;
}

export interface CacheStats {
  positions: number;
  hits: number;
  bytes: number;
  byMove: CacheMove[];
  bySource: Record<string, number>;
  oldest: string | null;
  newest: string | null;
  maxMoves: number;
}

export interface Check {
  id: string;
  title: string;
  state: string;
  detail: string;
  action: string | null;
}

export interface DayCount {
  date: string;
  games: number;
}

export interface EngineLine {
  uci: string;
  cp: number;
  pv: string[];
}

export interface GameDetail {
  id: string;
  source: string;
  white: string;
  black: string;
  whiteElo: number | null;
  blackElo: number | null;
  result: string;
  date: string | null;
  speed: string | null;
  opening: string | null;
  title: string | null;
  user: string | null;
  plies: number;
  analysed: boolean;
  accuracy: Accuracy | null;
  mistakes: number | null;
  spark: number[];
  moves: Move[];
  pgn: string | null;
}

export interface GamePage {
  total: number;
  items: GameSummary[];
}

export interface GameSummary {
  id: string;
  source: string;
  white: string;
  black: string;
  whiteElo: number | null;
  blackElo: number | null;
  result: string;
  date: string | null;
  speed: string | null;
  opening: string | null;
  title: string | null;
  user: string | null;
  plies: number;
  analysed: boolean;
  accuracy: Accuracy | null;
  mistakes: number | null;
  spark: number[];
}

export interface ImportPgn {
  text: string;
  player?: string | null;
}

export interface ImportUser {
  username: string;
  max?: number;
  only_new?: boolean;
  rated_only?: boolean;
}

export interface JobOut {
  id: string;
  kind: string;
  title: string;
  status: string;
  progress: number;
  message: string | null;
  createdAt: string;
  startedAt: string | null;
  finishedAt: string | null;
}

export interface MistakeStats {
  recent: number | null;
  previous: number | null;
}

export interface Move {
  san: string;
  uci: string;
  cls: string;
  loss: number;
  best: string;
  winBefore: number;
  winAfter: number;
  cp: number;
  acc: number | null;
  phase: string | null;
  lines: EngineLine[] | null;
}

export interface MoveBody {
  uci: string;
}

export interface OpeningStat {
  name: string;
  colour: string;
  games: number;
  score: number;
}

export interface PhaseAccuracy {
  opening: number | null;
  middlegame: number | null;
  endgame: number | null;
}

export interface RatingPoint {
  date: string;
  rating: number;
}

export interface Results {
  win: number;
  draw: number;
  loss: number;
}

export interface Settings {
  engine_path: string | null;
  nodes: number;
  multipv: number;
  threads: number;
  hash_mb: number;
  use_cache: boolean;
}

export interface SettingsPatch {
  engine_path?: string | null;
  nodes?: number | null;
  multipv?: number | null;
  threads?: number | null;
  hash_mb?: number | null;
  use_cache?: boolean | null;
}

export interface SplitStat {
  name: string;
  games: number;
  score: number;
}

export interface StartBody {
  colour: string;
  opponent: string;
  level: number;
}

export interface Stats {
  perDay: DayCount[];
  phaseAccuracy: PhaseAccuracy;
  classCounts: Record<string, number>;
  ratingSeries: RatingPoint[];
  colours: SplitStat[];
  speeds: SplitStat[];
  games: number;
  analysed: number;
  results: Results;
  accuracy: AccuracyStats;
  mistakesPerGame: MistakeStats;
  openings: OpeningStat[];
}

export interface Workspace {
  data_dir: string;
  checks: Check[];
  next_step: string | null;
}
