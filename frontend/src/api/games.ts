import { useQuery } from "@tanstack/react-query";
import type { GameRecord } from "@/lib/types";

// Prototype: sample games bundled as JSON (loaded lazily). The backend replaces this file's two functions; the hooks and the rest of the app stay the same.
let cache: Promise<GameRecord[]> | null = null;
const load = () => (cache ??= import("@/samples/sample-games.json").then((m) => m.default as unknown as GameRecord[]));

export const useGames = () => useQuery({ queryKey: ["games"], queryFn: load, staleTime: Infinity });
export const useGame = (id: string | undefined) =>
  useQuery({ queryKey: ["game", id], queryFn: async () => (await load()).find((g) => g.id === id) ?? null, enabled: !!id, staleTime: Infinity });
