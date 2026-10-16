import { usePieceSet } from "@/state/ui";

const ORDER = ["q", "r", "b", "n", "p"];

/** The pieces a player has taken, as small piece icons (most valuable first), with the material lead when they are ahead. */
export function Captured({ taken, takenColour, lead }: { taken: string[]; takenColour: "w" | "b"; lead: number }) {
  const set = usePieceSet();
  if (!taken.length && lead <= 0) return null;
  const sorted = [...taken].sort((a, b) => ORDER.indexOf(a) - ORDER.indexOf(b));
  return (
    <span className="flex items-center gap-1.5" aria-label={`Captured: ${sorted.join(" ") || "nothing"}${lead > 0 ? `, ${lead} ahead` : ""}`}>
      <span className="flex items-center">
        {sorted.map((r, i) => <img key={i} alt="" width={15} height={15} src={set.url({ colour: takenColour, role: r as "p" })} className={i > 0 && r === sorted[i - 1] ? "-ml-[7px]" : "ml-px"} />)}
      </span>
      {lead > 0 && <span className="tnum text-[11.5px] font-medium text-muted">+{lead}</span>}
    </span>
  );
}
