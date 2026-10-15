import { Activity as ActivityIcon, CheckCircle2, CircleSlash, Loader2, XCircle } from "lucide-react";
import { useCancelJob, useJobs, type Job } from "@/api/hooks";
import { Button } from "@/components/ui/Button";
import { EmptyState, Progress, Skeleton } from "@/components/ui/Misc";
import { PageHeader, Panel } from "@/components/ui/Panel";

function ago(iso: string | null | undefined) {
  if (!iso) return "";
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  return s < 60 ? "just now" : s < 3600 ? `${Math.floor(s / 60)} min ago` : s < 86400 ? `${Math.floor(s / 3600)} h ago` : `${Math.floor(s / 86400)} d ago`;
}

export function ActivityPage() {
  const { data: jobs, isLoading } = useJobs();
  const cancel = useCancelJob();
  const active = jobs?.filter((j) => j.status === "running" || j.status === "queued") ?? [];
  const past = jobs?.filter((j) => !(j.status === "running" || j.status === "queued")) ?? [];
  return (
    <div className="mx-auto max-w-[860px] px-8 py-8 max-md:px-4">
      <PageHeader title="Activity" sub="Imports, analyses and other work running in the background." />
      {isLoading && <Skeleton className="h-24 rounded-[12px]" />}
      {jobs && jobs.length === 0 && <Panel><EmptyState icon={ActivityIcon} title="Nothing has run yet" text="When you import or analyse games, their progress shows here." /></Panel>}
      {active.length > 0 && <Section title="Running">{active.map((j) => <Row key={j.id} job={j} onCancel={() => cancel.mutate(j.id)} />)}</Section>}
      {past.length > 0 && <Section title="Finished">{past.map((j) => <Row key={j.id} job={j} />)}</Section>}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return <section className="mb-6"><h2 className="mb-2 text-[12px] font-semibold uppercase tracking-[0.06em] text-muted">{title}</h2><Panel className="divide-y divide-border/70 overflow-hidden">{children}</Panel></section>;
}

function Row({ job, onCancel }: { job: Job; onCancel?: () => void }) {
  const running = job.status === "running" || job.status === "queued";
  const Icon = running ? Loader2 : job.status === "done" ? CheckCircle2 : job.status === "failed" ? XCircle : CircleSlash;
  const colour = running ? "var(--accent)" : job.status === "done" ? "var(--q-best)" : job.status === "failed" ? "var(--q-blunder)" : "var(--faint)";
  return (
    <div className="flex items-start gap-3.5 px-5 py-4">
      <Icon size={19} className={running ? "mt-0.5 animate-spin" : "mt-0.5"} style={{ color: colour }} />
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline justify-between gap-3"><span className="text-[14px] font-medium">{job.title}</span><span className="shrink-0 text-[12px] text-faint">{running ? (job.status === "queued" ? "waiting" : "") : ago(job.finishedAt)}</span></div>
        {running && <Progress value={job.progress} className="mt-2" />}
        {job.message && <p className={`mt-1 text-[13px] ${job.status === "failed" ? "text-[var(--q-blunder)]" : "text-muted"}`}>{job.message}</p>}
      </div>
      {running && onCancel && <Button size="sm" variant="ghost" onClick={onCancel}>Cancel</Button>}
    </div>
  );
}
