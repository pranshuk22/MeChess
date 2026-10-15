import { useEffect, useRef, useState } from "react";

export interface LiveLine { multipv: number; depth: number; kind: "cp" | "mate"; score: number; nodes: number; nps: number; san: string[]; uci: string[] }
export interface Live { lines: LiveLine[]; fen: string | null; cached: boolean; status: "off" | "connecting" | "running" | "error"; error: string | null }

const wsUrl = () => `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/ws/analysis`;

/** Live engine lines for a position, over a WebSocket. While `enabled` the connection stays open (and the server's engine works); a new `fen` replaces the old
 *  analysis; lines of an older position are never shown for the new one. The connection is re-opened after a drop. */
export function useLiveAnalysis(enabled: boolean, fen: string, multipv: number): Live {
  const [live, setLive] = useState<Live>({ lines: [], fen: null, cached: false, status: "off", error: null });
  const sock = useRef<WebSocket | null>(null);
  const want = useRef({ fen, multipv });
  want.current = { fen, multipv };

  useEffect(() => {
    if (!enabled) { setLive({ lines: [], fen: null, cached: false, status: "off", error: null }); return; }
    let closed = false, retry = 0, failures = 0, timer: ReturnType<typeof setTimeout>;
    const open = () => {
      setLive((l) => ({ ...l, status: "connecting" }));
      const ws = new WebSocket(wsUrl());
      sock.current = ws;
      ws.onopen = () => { retry = 0; failures = 0; ws.send(JSON.stringify(want.current)); setLive((l) => ({ ...l, status: "running", error: null })); };
      ws.onmessage = (e) => {
        const m = JSON.parse(e.data);
        if (m.type === "lines" && m.fen === want.current.fen) setLive({ lines: m.lines, fen: m.fen, cached: !!m.cached, status: "running", error: null });
        else if (m.type === "error") setLive((l) => ({ ...l, status: "error", error: m.message }));
      };
      ws.onclose = () => {
        if (closed) return;
        failures++;
        setLive((l) => (failures >= 3 ? { ...l, status: "error", error: "The engine channel could not be reached. Is the MeChess server running (and the 'websockets' package installed)?" } : { ...l, status: "connecting" }));
        timer = setTimeout(open, Math.min(8000, 500 * 2 ** retry++));
      };
    };
    open();
    return () => { closed = true; clearTimeout(timer); sock.current?.close(); sock.current = null; };
  }, [enabled]);

  useEffect(() => {
    const ws = sock.current;
    if (!enabled || !ws || ws.readyState !== WebSocket.OPEN) return;
    const t = setTimeout(() => ws.send(JSON.stringify({ fen, multipv })), 90);          // stepping quickly through moves asks the engine only about where you stop
    return () => clearTimeout(t);
  }, [enabled, fen, multipv]);

  return live.fen === fen || !enabled ? live : { ...live, lines: [] };
}

export function formatScore(kind: "cp" | "mate", score: number): string {
  if (kind === "mate") return score > 0 ? `M${score}` : `-M${Math.abs(score)}`;
  const v = (score / 100).toFixed(1);
  return (score > 0 ? "+" : "") + v;
}
/** the evaluation as centipawns for the eval bar (a mate counts as a very large value) */
export const scoreToCp = (kind: "cp" | "mate", score: number) => (kind === "mate" ? (score > 0 ? 1500 : -1500) : Math.max(-1500, Math.min(1500, score)));
