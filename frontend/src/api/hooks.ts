import { keepPreviousData, useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import type { GameDetail, GameSummary, S } from "@/lib/types";
import { api } from "./client";

export type Job = S.JobOut;
export interface GameFilters { q?: string; colour?: string; result?: string; analysed?: boolean }
const PAGE = 200;

export const useStats = () => useQuery({ queryKey: ["stats"], queryFn: () => api<S.Stats>("/api/stats") });
export const useWorkspace = () => useQuery({ queryKey: ["workspace"], queryFn: () => api<S.Workspace>("/api/workspace") });
export const useSettings = () => useQuery({ queryKey: ["settings"], queryFn: () => api<S.Settings>("/api/settings") });
export const useAccounts = () => useQuery({ queryKey: ["accounts"], queryFn: () => api<S.Accounts>("/api/accounts") });
export const useJobs = () => useQuery({ queryKey: ["jobs"], queryFn: () => api<Job[]>("/api/jobs"), refetchInterval: (q) => (q.state.data?.some((j) => j.status === "running" || j.status === "queued") ? 4000 : false) });

export function useGamesPage(filters: GameFilters = {}, limit = 6) {
  return useQuery({
    queryKey: ["games", "page", filters, limit],
    queryFn: () => api<{ total: number; items: GameSummary[] }>(`/api/games?${qs({ ...filters, limit })}`),
    placeholderData: keepPreviousData,
  });
}

/** all games for the library, newest first, loaded page by page as the list is scrolled */
export function useGamesInfinite(filters: GameFilters) {
  return useInfiniteQuery({
    queryKey: ["games", "infinite", filters],
    initialPageParam: 0,
    queryFn: ({ pageParam }) => api<{ total: number; items: GameSummary[] }>(`/api/games?${qs({ ...filters, limit: PAGE, offset: pageParam })}`),
    getNextPageParam: (last, all) => { const loaded = all.reduce((n, p) => n + p.items.length, 0); return loaded < last.total ? loaded : undefined; },
    placeholderData: keepPreviousData,
  });
}

export const useGame = (id: string | undefined) => useQuery({ queryKey: ["game", id], queryFn: () => api<GameDetail>(`/api/games/${encodeURIComponent(id!)}`), enabled: !!id, retry: (n, e) => (e as { status?: number }).status !== 404 && n < 2 });

function qs(o: Record<string, unknown>) {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(o)) if (v !== undefined && v !== "" && v !== "all" && v !== null) p.set(k, String(v));
  return p.toString();
}

/** Live job updates (server-sent events); when a job finishes, everything it may have changed is fetched again. */
export function useJobEvents() {
  const qc = useQueryClient();
  useEffect(() => {
    if (typeof EventSource === "undefined") return;
    const es = new EventSource("/api/events");
    es.addEventListener("job", (e) => {
      const job = JSON.parse((e as MessageEvent).data) as Job;
      qc.setQueryData<Job[]>(["jobs"], (old = []) => [job, ...old.filter((j) => j.id !== job.id)].sort((a, b) => b.createdAt.localeCompare(a.createdAt)));
      if (job.status === "done" || job.status === "failed" || job.status === "cancelled") {
        for (const k of ["games", "game", "stats", "workspace", "cache", "drills", "profile"]) qc.invalidateQueries({ queryKey: [k] });
      }
    });
    return () => es.close();
  }, [qc]);
}

export const useRunningJobs = () => (useJobs().data ?? []).filter((j) => j.status === "running" || j.status === "queued");

function useJobMutation<V>(path: (v: V) => string, body?: (v: V) => unknown) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: V) => api<Job>(path(v), { method: "POST", json: body ? body(v) : undefined }),
    onSuccess: (job) => { qc.setQueryData<Job[]>(["jobs"], (old = []) => [job, ...old.filter((j) => j.id !== job.id)]); qc.invalidateQueries({ queryKey: ["jobs"] }); },
  });
}
export const useImportUser = () => useJobMutation<{ platform: "lichess" | "chesscom"; username: string; max: number; only_new: boolean }>((v) => `/api/import/${v.platform}`, ({ platform: _p, ...b }) => b);
export const useImportPgn = () => useJobMutation<{ text: string; player?: string }>(() => "/api/import/pgn", (v) => v);
export const useAnalyse = () => useJobMutation<{ ids?: string[]; limit?: number; nodes?: number }>(() => "/api/analyse", (v) => v);
export const useImportLegacy = () => useJobMutation<void>(() => "/api/workspace/import-legacy");
export function useCancelJob() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (id: string) => api(`/api/jobs/${id}/cancel`, { method: "POST" }), onSuccess: () => qc.invalidateQueries({ queryKey: ["jobs"] }) });
}
export function useSaveSettings() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (patch: Partial<S.Settings>) => api<S.Settings>("/api/settings", { method: "PATCH", json: patch }), onSuccess: (d) => { qc.setQueryData(["settings"], d); qc.invalidateQueries({ queryKey: ["workspace"] }); } });
}
export function useSaveAccounts() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (a: S.Accounts) => api<S.Accounts>("/api/accounts", { method: "PUT", json: a }), onSuccess: (d) => qc.setQueryData(["accounts"], d) });
}
export function useDeleteGame() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (id: string) => api(`/api/games/${encodeURIComponent(id)}`, { method: "DELETE" }), onSuccess: () => { for (const k of ["games", "stats", "workspace"]) qc.invalidateQueries({ queryKey: [k] }); } });
}

export interface Themes { pieces: { id: string; name: string; files: Record<string, string> }[]; boards: { id: string; name: string; url: string }[]; pieces_dir: string; boards_dir: string }
export const useThemes = () => useQuery({ queryKey: ["themes"], queryFn: () => api<Themes>("/api/themes"), staleTime: 60_000 });

export interface ExplorerMove { san: string; uci: string; games: number; share: number; white: number; draw: number; black: number; avg_rating: number; eval: number | null }
export interface ExplorerResult { total: number; other: number; moves: ExplorerMove[]; opening?: { eco: string; name: string } | null }
/** what players play in a position; `unavailable` when the explorer database has not been built */
export function useExplorer(fen: string, enabled: boolean, rating = 1500) {
  return useQuery({
    queryKey: ["explorer", fen, rating],
    enabled,
    retry: false,
    staleTime: Infinity,
    queryFn: async () => {
      try { return await api<ExplorerResult>(`/api/explorer?${new URLSearchParams({ fen, rating: String(rating) })}`); }
      catch (e) { if ((e as { status?: number }).status === 404) return null; throw e; }
    },
  });
}

export const useCacheStats = () => useQuery({ queryKey: ["cache"], queryFn: () => api<S.CacheStats>("/api/cache") });
export const useBuildCache = () => useJobMutation<{ min_count?: number; limit?: number; include_theory?: boolean }>(() => "/api/cache/build", (v) => v);
export function useClearCache() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (source?: string) => api<{ deleted: number }>(`/api/cache${source ? `?source=${source}` : ""}`, { method: "DELETE" }), onSuccess: () => qc.invalidateQueries({ queryKey: ["cache"] }) });
}

export interface DrillStats { total: number; due: number; boxes: number[] }
export interface Drill { id: string; fen: string; colour: "white" | "black"; ply: number | null; move: number | null; phase: string | null; class: string | null; loss: number | null; playedSan: string; gameId: string | null; box: number }
export const useDrillStats = () => useQuery({ queryKey: ["drills"], queryFn: () => api<DrillStats>("/api/coach/drills") });
export interface Profile {
  games: number; moves: number; mistake_rate?: number; blunder_rate?: number;
  by_phase?: Record<string, { moves: number; mistake_rate: number; mean_loss: number; z: number }>;
  by_situation?: Record<string, { moves: number; mistake_rate: number; mean_loss: number; z: number }>;
  kinds?: Record<string, { count: number; share: number }>;
  sentences: string[]; foci: { id: string; reason: string }[];
  reference?: { band: number; speed: string; ref_moves: number; comparable: boolean; overall: { moves: number; you: number; ref: number; z: number }; areas: Record<string, { moves: number; you: number; ref: number | null; z: number }> };
}
export const useProfile = () => useQuery({ queryKey: ["profile"], queryFn: () => api<Profile>("/api/coach/profile") });
