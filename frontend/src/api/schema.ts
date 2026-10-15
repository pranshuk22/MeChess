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

export interface Check {
  id: string;
  title: string;
  state: string;
  detail: string;
  action?: string | null;
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
  spark?: number[];
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
  spark?: number[];
}

export interface ImportPgn {
  text: string;
  player?: string | null;
}

export interface ImportUser {
  username: string;
  max?: number;
  only_new?: boolean;
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
  acc?: number | null;
  phase?: string | null;
}

export interface OpeningStat {
  name: string;
  colour: string;
  games: number;
  score: number;
}

export interface Results {
  win: number;
  draw: number;
  loss: number;
}

export interface Settings {
  engine_path?: string | null;
  nodes?: number;
  multipv?: number;
  threads?: number;
  hash_mb?: number;
}

export interface SettingsPatch {
  engine_path?: string | null;
  nodes?: number | null;
  multipv?: number | null;
  threads?: number | null;
  hash_mb?: number | null;
}

export interface Stats {
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
