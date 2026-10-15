import { memo, useMemo } from "react";
import { ClassIcon } from "@/components/ClassIcon";
import { CLASS_LABEL, CLASS_ORDER, type GameRecord } from "@/lib/types";

const PHASES = [["opening", "Opening"], ["middlegame", "Middlegame"], ["endgame", "Endgame"]] as const;

/** The game at a glance: accuracy of both players, how many moves of every kind each played, and accuracy by phase. */
export const Summary = memo(function Summary({ game }: { game: GameRecord }) {
  const { counts, phase } = useMemo(() => {
    const counts = CLASS_ORDER.map((cls) => ({ cls, white: 0, black: 0 }));
    const acc: Record<string, { white: number[]; black: number[] }> = {};
    game.moves.forEach((m, i) => {
      const side = i % 2 === 0 ? "white" : "black";
      const row = counts.find((c) => c.cls === m.cls);
      if (row) row[side]++;
      if (m.acc !== undefined && m.phase) (acc[m.phase] ??= { white: [], black: [] })[side].push(m.acc);
    });
    const mean = (xs: number[]) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null);
    return { counts, phase: PHASES.map(([id, label]) => ({ label, white: mean(acc[id]?.white ?? []), black: mean(acc[id]?.black ?? []) })).filter((p) => p.white !== null || p.black !== null) };
  }, [game]);
  const side = (colour: "white" | "black") => ({ name: colour === "white" ? game.white : game.black, elo: colour === "white" ? game.whiteElo : game.blackElo, acc: game.accuracy[colour], you: game.user === colour });
  const [w, b] = [side("white"), side("black")];
  return (
    <div className="space-y-4 p-4 text-[13.5px]">
      <div className="grid grid-cols-2 gap-3">
        {[w, b].map((p, i) => (
          <div key={i} className="rounded-lg bg-surface-2 px-3 py-2.5 text-center">
            <div className="truncate text-[12.5px] font-medium">{p.name}{p.you ? " (you)" : ""}</div>
            <div className="tnum text-[11.5px] text-muted">{p.elo ?? "unrated"}</div>
            <div className="tnum mt-1.5 text-[26px] font-semibold leading-none">{p.acc.toFixed(1)}</div>
            <div className="mt-1 text-[10.5px] uppercase tracking-wide text-faint">accuracy</div>
          </div>
        ))}
      </div>

      <table className="w-full" aria-label="Moves by kind">
        <thead><tr className="text-[11.5px] uppercase tracking-wide text-faint"><th className="pb-1.5 text-left font-semibold">Move kind</th><th className="w-14 pb-1.5 text-right font-semibold">White</th><th className="w-14 pb-1.5 text-right font-semibold">Black</th></tr></thead>
        <tbody>
          {counts.map((c) => (
            <tr key={c.cls} className={c.white + c.black === 0 ? "text-faint" : ""}>
              <td className="py-[3px]"><span className="inline-flex items-center gap-2"><ClassIcon cls={c.cls} size={18} style={c.white + c.black === 0 ? { opacity: 0.35 } : undefined} />{CLASS_LABEL[c.cls]}</span></td>
              <td className="tnum py-[3px] text-right font-medium">{c.white}</td>
              <td className="tnum py-[3px] text-right font-medium">{c.black}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {phase.length > 0 && (
        <div>
          <div className="mb-1.5 text-[11.5px] font-semibold uppercase tracking-wide text-faint">Accuracy by phase</div>
          <div className="space-y-1.5">
            {phase.map((p) => (
              <div key={p.label} className="grid grid-cols-[88px_1fr_1fr] items-center gap-3">
                <span className="text-muted">{p.label}</span>
                <Bar value={p.white} /><Bar value={p.black} />
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
});

function Bar({ value }: { value: number | null }) {
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-2"><div className="h-full rounded-full bg-accent" style={{ width: `${value ?? 0}%` }} /></div>
      <span className="tnum w-9 text-right text-[12.5px]">{value === null ? "–" : value.toFixed(0)}</span>
    </div>
  );
}
