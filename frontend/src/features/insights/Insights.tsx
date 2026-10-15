import { BarChart3, Download } from "lucide-react";
import { useStats } from "@/api/hooks";
import { BarRow, Calendar, LineChart, QualityBar } from "@/components/charts";
import { Button } from "@/components/ui/Button";
import { EmptyState, Skeleton } from "@/components/ui/Misc";
import { PageHeader, Panel, PanelTitle } from "@/components/ui/Panel";
import { useDialogs } from "@/state/dialogs";

const PHASES: [string, string][] = [["opening", "Opening"], ["middlegame", "Middlegame"], ["endgame", "Endgame"]];

export function InsightsPage() {
  const { data: st, isLoading } = useStats();
  const setImportOpen = useDialogs((s) => s.setImportOpen);
  if (isLoading || !st) return <div className="mx-auto max-w-[1180px] px-8 py-8"><Skeleton className="h-[420px] rounded-[12px]" /></div>;
  if (!st.games) return <div className="mx-auto max-w-[760px] px-8 py-12"><Panel><EmptyState icon={BarChart3} title="No games to learn from yet" text="Import your games and analyse them: this page shows how you play, by phase, by move kind, over time." action={<Button variant="primary" onClick={() => setImportOpen(true)}><Download size={15} /> Import games</Button>} /></Panel></div>;
  const ratings = st.ratingSeries;
  return (
    <div className="mx-auto max-w-[1180px] px-8 py-8 max-md:px-4">
      <PageHeader title="Insights" sub={`From ${st.analysed.toLocaleString()} analysed and ${st.games.toLocaleString()} imported games.`} />
      <div className="grid grid-cols-2 gap-5 max-lg:grid-cols-1">
        <Panel className="col-span-2 max-lg:col-span-1">
          <PanelTitle sub="Games per day, last 26 weeks">Activity</PanelTitle>
          <div className="px-5 pb-5"><Calendar days={st.perDay} /></div>
        </Panel>
        <Panel>
          <PanelTitle sub="Your rating in your games, oldest to newest">Rating</PanelTitle>
          <div className="px-5 pb-5"><LineChart values={ratings.map((r) => r.rating)} labels={[ratings[0]?.date, ratings.at(-1)?.date].filter(Boolean) as string[]} /></div>
        </Panel>
        <Panel>
          <PanelTitle sub="Average accuracy of your moves in your last 100 analysed games">Accuracy by phase</PanelTitle>
          <div className="space-y-3.5 px-5 pb-5 pt-2">{PHASES.map(([k, l]) => <BarRow key={k} label={l} value={st.phaseAccuracy[k as keyof typeof st.phaseAccuracy]} right={st.phaseAccuracy[k as keyof typeof st.phaseAccuracy] === null ? "–" : `${st.phaseAccuracy[k as keyof typeof st.phaseAccuracy]!.toFixed(0)}%`} />)}</div>
        </Panel>
        <Panel>
          <PanelTitle sub="How your moves were judged">Move quality</PanelTitle>
          <div className="px-5 pb-5"><QualityBar counts={st.classCounts} /></div>
        </Panel>
        <Panel>
          <PanelTitle sub="Points per game: win 1, draw ½, loss 0">Results by colour and speed</PanelTitle>
          <div className="space-y-3.5 px-5 pb-5 pt-2">
            {st.colours.map((c) => <BarRow key={c.name} label={c.name} value={c.score * 100} right={`${Math.round(c.score * 100)}% · ${c.games}`} tone={c.score >= 0.5 ? "good" : "warn"} />)}
            {st.colours.length > 0 && st.speeds.length > 0 && <div className="h-px bg-border/70" />}
            {st.speeds.map((c) => <BarRow key={c.name} label={c.name} value={c.score * 100} right={`${Math.round(c.score * 100)}% · ${c.games}`} tone={c.score >= 0.5 ? "good" : "warn"} />)}
          </div>
        </Panel>
      </div>
    </div>
  );
}
