import { Details } from "@/components/ui/Details";
import { BookOpen, Search } from "lucide-react";
import { useEffect, useState } from "react";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "@/api/client";
import { Board } from "@/board/Board";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Field";
import { Badge, EmptyState } from "@/components/ui/Misc";
import { PageHeader, Panel } from "@/components/ui/Panel";

interface Note { id: number; fen: string; san: string; uci: string; glyph: string | null; judgement: string | null; evaluation: string | null; source: string | null; comment: string; concepts: string[] }
interface Stat { indexed: number; available: boolean; concepts: { name: string; count: number }[] }

/** What chess books and annotated games say about positions: search the comments by words or by idea. */
export function BooksPage() {
  const qc = useQueryClient(), nav = useNavigate();
  const stat = useQuery({ queryKey: ["books"], queryFn: () => api<Stat>("/api/books") });
  const [q, setQ] = useState(""), [dq, setDq] = useState(""), [concept, setConcept] = useState<string | null>(null);
  useEffect(() => { const t = setTimeout(() => setDq(q), 250); return () => clearTimeout(t); }, [q]);
  const index = useMutation({ mutationFn: () => api("/api/books/index", { method: "POST" }), onSuccess: () => { qc.invalidateQueries({ queryKey: ["jobs"] }); nav("/activity"); } });
  const results = useInfiniteQuery({
    queryKey: ["books-search", dq, concept], enabled: (stat.data?.indexed ?? 0) > 0, initialPageParam: 0,
    queryFn: ({ pageParam }) => api<{ total: number; items: Note[] }>(`/api/books/search?${new URLSearchParams({ ...(dq ? { q: dq } : {}), ...(concept ? { concept } : {}), limit: "12", offset: String(pageParam) })}`),
    getNextPageParam: (last, all) => { const n = all.reduce((a, p) => a + p.items.length, 0); return n < last.total ? n : undefined; },
  });
  const s = stat.data;
  const items = results.data?.pages.flatMap((p) => p.items) ?? [];
  if (s && !s.indexed) {
    return (
      <div className="mx-auto max-w-[760px] px-8 py-10"><PageHeader title="Books" />
        <Panel><EmptyState icon={BookOpen} title={s.available ? "Index the book comments" : "No book comments found"}
          text={s.available ? "Comments from chess books and annotated games were found on this computer. Indexing makes them searchable by words and ideas, and shows them next to the positions they are about." : "Commentary from public-domain chess books and annotated games, searchable by idea (outpost, zugzwang, minority attack) and shown with the position each comment is about. None has been collected yet."}
          action={s.available ? <Button variant="primary" onClick={() => index.mutate()} disabled={index.isPending}>Index the comments</Button> : <Details summary="How to collect books"><p>Run <code className="font-mono text-text">chessme books-learn</code> in the project folder (see docs/language-model.md); it collects public-domain books and annotated games. Then open this page again.</p></Details>} /></Panel></div>
    );
  }
  return (
    <div className="mx-auto max-w-[1180px] px-8 py-8 max-md:px-4">
      <PageHeader title="Books" sub={s ? `${s.indexed.toLocaleString()} comments from public-domain books and annotated games, with the positions they are about.` : ""} />
      <div className="mb-4 w-[min(100%,420px)]"><Input icon={<Search size={15} />} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search the comments: outpost, zugzwang, minority attack…" aria-label="Search the comments" /></div>
      <div className="mb-5 flex flex-wrap gap-1.5" role="group" aria-label="Ideas">
        {s?.concepts.slice(0, 24).map((c) => (
          <button key={c.name} aria-pressed={concept === c.name} onClick={() => setConcept(concept === c.name ? null : c.name)} className={`rounded-full border px-3 py-1 text-[12.5px] transition-colors cursor-pointer ${concept === c.name ? "border-accent bg-accent-soft text-accent" : "border-border hover:bg-surface-2"}`}>{c.name} <span className="text-faint">{c.count}</span></button>
        ))}
      </div>
      <p className="mb-3 text-[12.5px] text-muted" role="status">{results.data ? `${results.data.pages[0].total.toLocaleString()} found` : ""}</p>
      <div className="grid grid-cols-2 gap-4 max-lg:grid-cols-1">
        {items.map((n) => (
          <Panel key={n.id} className="grid grid-cols-[150px_1fr] gap-4 p-4 max-sm:grid-cols-1">
            <div className="w-[150px] overflow-hidden rounded-[5px]"><Board fen={n.fen} showCoords={false} arrows={[{ from: n.uci.slice(0, 2), to: n.uci.slice(2, 4), kind: "best" }]} /></div>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2"><b className="text-[15px]">{n.san}{n.glyph && n.glyph !== "None" ? n.glyph : ""}</b>{n.judgement && <Badge>{n.judgement}</Badge>}{n.evaluation && <Badge tone="accent">{n.evaluation}</Badge>}</div>
              <p className="mt-1.5 text-[13.5px] leading-[1.55]">{n.comment}</p>
              <div className="mt-2 flex flex-wrap gap-1.5">{n.concepts.map((c) => <Badge key={c}>{c}</Badge>)}{n.source && <span className="text-[11.5px] text-faint">{n.source}</span>}</div>
            </div>
          </Panel>
        ))}
      </div>
      {items.length === 0 && results.isSuccess && <p className="py-10 text-center text-[13.5px] text-muted">Nothing found. Try another word or idea.</p>}
      {results.hasNextPage && <div className="mt-5 text-center"><Button onClick={() => results.fetchNextPage()} disabled={results.isFetchingNextPage}>Show more</Button></div>}
    </div>
  );
}
