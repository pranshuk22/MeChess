import { Link } from "react-router-dom";
import { Target } from "lucide-react";
import { useProfile } from "@/api/hooks";
import { BarRow } from "@/components/charts";
import { EmptyState, Skeleton } from "@/components/ui/Misc";
import { Panel, PanelTitle } from "@/components/ui/Panel";
import { Button } from "@/components/ui/Button";

const KIND: Record<string, string> = { "mate in 1": "Allowed a checkmate in one", "ignores a threat": "Did not deal with a threat", "walks into a capture": "Put a piece where it can be captured", deeper: "Lost the advantage over a longer sequence" };
const pct = (x: number) => `${Math.round(100 * x)}%`;

/** Where you give away points: against your own rate elsewhere, and against players of your rating when a reference exists. */
export function Weaknesses() {
  const { data: p, isLoading } = useProfile();
  if (isLoading || !p) return <Skeleton className="h-64 rounded-[12px]" />;
  if (!p.moves) return <Panel><EmptyState icon={Target} title="Nothing to analyse yet" text="Analyse some of your games. The profile needs a few hundred of your moves to say anything fair." action={<Link to="/library"><Button variant="primary">Go to the library</Button></Link>} /></Panel>;
  const phases = Object.entries(p.by_phase ?? {}), situations = Object.entries(p.by_situation ?? {});
  const ref = p.reference;
  return (
    <div className="grid grid-cols-2 gap-5 max-lg:grid-cols-1">
      <Panel className="col-span-2 max-lg:col-span-1">
        <PanelTitle sub={`From ${p.games} games and ${p.moves.toLocaleString()} of your moves. A mistake gives away at least 10% of the win chance.`}>What stands out</PanelTitle>
        <ul className="space-y-2 px-5 pb-5">
          {p.sentences.map((s, i) => <li key={i} className="rounded-[9px] bg-sunken px-4 py-2.5 text-[13.5px]">{s}</li>)}
        </ul>
      </Panel>
      <Panel>
        <PanelTitle sub="Share of your moves that were mistakes">By phase and situation</PanelTitle>
        <div className="space-y-3 px-5 pb-5 pt-1">
          {phases.map(([k, v]) => <BarRow key={k} label={k} value={100 * v.mistake_rate} max={40} right={`${pct(v.mistake_rate)} · ${v.moves}`} tone={v.z >= 1.64 ? "warn" : "accent"} />)}
          <div className="h-px bg-border/70" />
          {situations.map(([k, v]) => <BarRow key={k} label={k} value={100 * v.mistake_rate} max={40} right={`${pct(v.mistake_rate)} · ${v.moves}`} tone={v.z >= 1.64 ? "warn" : "accent"} />)}
        </div>
      </Panel>
      <Panel>
        <PanelTitle sub="What kind of mistake it was">Kinds of mistake</PanelTitle>
        <div className="space-y-3 px-5 pb-5 pt-1">
          {Object.entries(p.kinds ?? {}).sort((a, b) => b[1].count - a[1].count).map(([k, v]) => <div key={k} className="grid grid-cols-[1fr_64px] items-center gap-3 text-[13px]"><span>{KIND[k] ?? k}</span><span className="tnum text-right text-muted">{pct(v.share)} · {v.count}</span></div>)}
          {!Object.keys(p.kinds ?? {}).length && <p className="text-[13px] text-muted">No mistakes to sort yet.</p>}
        </div>
      </Panel>
      {ref && (
        <Panel className="col-span-2 max-lg:col-span-1">
          <PanelTitle sub={`${ref.ref_moves.toLocaleString()} moves of players rated ${ref.band} to ${ref.band + 199} in ${ref.speed}${ref.comparable ? "" : " (analysed with other settings: treat as rough)"}`}>You and players of your rating</PanelTitle>
          <div className="grid grid-cols-2 gap-x-8 gap-y-3 px-5 pb-5 pt-1 max-sm:grid-cols-1">
            <BarRow label="overall" value={100 * ref.overall.you} max={40} right={`you ${pct(ref.overall.you)} · them ${pct(ref.overall.ref)}`} tone={Math.abs(ref.overall.z) >= 2.5 ? (ref.overall.z > 0 ? "warn" : "good") : "accent"} />
            {Object.entries(ref.areas).filter(([, v]) => v.ref !== null).map(([k, v]) => <BarRow key={k} label={k.split(": ")[1]} value={100 * v.you} max={40} right={`you ${pct(v.you)} · them ${pct(v.ref!)}`} tone={Math.abs(v.z) >= 2.5 ? (v.z > 0 ? "warn" : "good") : "accent"} />)}
          </div>
        </Panel>
      )}
    </div>
  );
}
