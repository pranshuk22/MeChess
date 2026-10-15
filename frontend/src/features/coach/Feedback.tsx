import { AlertTriangle, CheckCircle2, Sparkles, ThumbsUp, XCircle } from "lucide-react";

/** The graded answer to a move tried in practice (`/api/coach/feedback`, the drill attempt): a title by grade, then the reasons in plain sentences. */
export interface Feedback {
  grade: "best" | "great" | "good" | "inaccuracy" | "mistake" | "blunder";
  solved: boolean;
  loss: number | null;
  title: string;
  reasons: string[];
  line?: string;
  san?: string;
  uci?: string;
  bestSan?: string;
  bestWhy?: string[];
  alternatives?: string[];
}

const LOOK: Record<Feedback["grade"], { color: string; Icon: typeof CheckCircle2 }> = {
  best: { color: "var(--q-best)", Icon: Sparkles },
  great: { color: "var(--q-great)", Icon: CheckCircle2 },
  good: { color: "var(--q-good)", Icon: ThumbsUp },
  inaccuracy: { color: "var(--q-inaccuracy)", Icon: AlertTriangle },
  mistake: { color: "var(--q-mistake)", Icon: XCircle },
  blunder: { color: "var(--q-blunder)", Icon: XCircle },
};

export function FeedbackCard({ fb, compact = false }: { fb: Feedback; compact?: boolean }) {
  const { color, Icon } = LOOK[fb.grade] ?? LOOK.good;
  return (
    <div role="status" data-grade={fb.grade} className="rounded-[10px] border px-3.5 py-3" style={{ borderColor: `color-mix(in srgb, ${color} 45%, transparent)`, background: `color-mix(in srgb, ${color} 8%, transparent)` }}>
      <div className="flex items-center gap-2 text-[15px] font-semibold" style={{ color: `color-mix(in srgb, ${color} 35%, var(--text))` }}><Icon size={18} />{fb.san ? `${fb.san}: ` : ""}{fb.title}</div>
      <div className={compact ? "mt-1.5 space-y-1.5 text-[13px]" : "mt-2 space-y-2 text-[13.5px]"}>
        {fb.reasons.map((r, i) => <p key={i}>{r}</p>)}
      </div>
    </div>
  );
}
