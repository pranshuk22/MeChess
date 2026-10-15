import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Arrows, type Arrow } from "./Arrows";
import { matchPieces, parsePieces, sqToView, viewToSq, FILES, type KeyedPiece, type Orientation } from "./geometry";
import { DEFAULT_PIECE_SET, type PieceSet, type Role } from "./pieces";
import { isPromotion } from "@/lib/game";

export interface BoardProps {
  fen: string;
  orientation?: Orientation;
  /** legal destinations per origin square for the side to move (empty map: the board is read-only) */
  legal?: Map<string, string[]>;
  /** which colour the user may move: "w", "b", "both" or null (watching) */
  movable?: "w" | "b" | "both" | null;
  lastMove?: [string, string] | null;
  checkSquare?: string | null;
  arrows?: Arrow[];
  /** squares marked from outside (a hint) */
  marks?: string[];
  pieceSet?: PieceSet;
  showCoords?: boolean;
  onMove?: (from: string, to: string, promotion?: Role) => void;
}

const px = (v: number) => `${v}px`;
type Shapes = { arrows: { from: string; to: string }[]; marks: string[] };
const EMPTY: Shapes = { arrows: [], marks: [] };

/** The board: DOM pieces moved with CSS transforms only (GPU, no layout), pointer events for mouse and touch, no network and no React work while dragging. */
export const Board = memo(function Board({ fen, orientation = "white", legal, movable = null, lastMove, checkSquare, arrows = [], marks = [], pieceSet = DEFAULT_PIECE_SET, showCoords = true, onMove }: BoardProps) {
  const root = useRef<HTMLDivElement>(null);
  const prev = useRef<KeyedPiece[]>([]);
  const pieces = useMemo(() => matchPieces(prev.current, parsePieces(fen)), [fen]);
  useEffect(() => { prev.current = pieces; }, [pieces]);

  const [selected, setSelected] = useState<string | null>(null);
  const [hover, setHover] = useState<string | null>(null);
  const [drag, setDrag] = useState<KeyedPiece | null>(null);
  const [instant, setInstant] = useState<number | null>(null);
  const [promo, setPromo] = useState<{ from: string; to: string } | null>(null);
  const [shapes, setShapes] = useState<Shapes>(EMPTY);
  const [preview, setPreview] = useState<{ from: string; to: string } | null>(null);
  const dragEl = useRef<HTMLDivElement>(null);
  const gesture = useRef<{ kind: "left" | "right"; from: string; id?: number; moved: boolean; wasSelected: boolean } | null>(null);

  const turn = fen.split(" ")[1] as "w" | "b";
  const byId = useMemo(() => new Map(pieces.map((p) => [p.sq, p])), [pieces]);
  const canMove = (colour: "w" | "b") => !!legal && legal.size > 0 && colour === turn && (movable === "both" || movable === colour);

  // a new position resets the selection and the user's drawn shapes
  useEffect(() => { setSelected(null); setPromo(null); setShapes(EMPTY); }, [fen]);
  useEffect(() => { setShapes(EMPTY); }, [orientation]);

  const squareAt = useCallback((e: { clientX: number; clientY: number }): string | null => {
    const r = root.current!.getBoundingClientRect();
    const col = Math.floor(((e.clientX - r.left) / r.width) * 8), row = Math.floor(((e.clientY - r.top) / r.height) * 8);
    return col < 0 || col > 7 || row < 0 || row > 7 ? null : viewToSq(col, row, orientation);
  }, [orientation]);

  const place = (el: HTMLElement, e: { clientX: number; clientY: number }) => {
    const r = root.current!.getBoundingClientRect(), size = r.width / 8;
    el.style.transform = `translate(${px(e.clientX - r.left - size / 2)}, ${px(e.clientY - r.top - size / 2)})`;
  };

  const attempt = (from: string, to: string, animateFromDrop: boolean, id?: number) => {
    if (!legal?.get(from)?.includes(to)) return false;
    if (isPromotion(fen, from, to)) { setPromo({ from, to }); setSelected(null); return true; }
    if (animateFromDrop && id !== undefined) { setInstant(id); requestAnimationFrame(() => requestAnimationFrame(() => setInstant(null))); }
    setSelected(null);
    onMove?.(from, to);
    return true;
  };

  const onPointerDown = (e: React.PointerEvent) => {
    const sq = squareAt(e);
    if (!sq) return;
    if (e.button === 2) {
      gesture.current = { kind: "right", from: sq, moved: false, wasSelected: false };
      root.current!.setPointerCapture(e.pointerId);
      return;
    }
    if (e.button !== 0) return;
    if (shapes.arrows.length || shapes.marks.length) setShapes(EMPTY);
    if (promo) { setPromo(null); return; }
    if (selected && attempt(selected, sq, false)) return;
    const p = byId.get(sq);
    if (p && canMove(p.colour)) {
      const wasSelected = selected === sq;
      setSelected(sq);
      gesture.current = { kind: "left", from: sq, id: p.id, moved: false, wasSelected };
      root.current!.setPointerCapture(e.pointerId);
    } else setSelected(null);
  };

  const onPointerMove = (e: React.PointerEvent) => {
    const g = gesture.current;
    if (!g) return;
    const sq = squareAt(e);
    if (g.kind === "right") { setPreview(sq && sq !== g.from ? { from: g.from, to: sq } : null); return; }
    if (!g.moved) {
      const p = byId.get(g.from);
      if (!p) return;
      g.moved = true;
      setDrag(p);
      requestAnimationFrame(() => dragEl.current && place(dragEl.current, e));
    }
    if (dragEl.current) place(dragEl.current, e);
    setHover((h) => (h === sq ? h : sq));
  };

  const onPointerUp = (e: React.PointerEvent) => {
    const g = gesture.current;
    gesture.current = null;
    if (!g) return;
    const sq = squareAt(e);
    if (g.kind === "right") {
      setPreview(null);
      if (!sq) return;
      setShapes((s) => sq === g.from
        ? { ...s, marks: s.marks.includes(sq) ? s.marks.filter((m) => m !== sq) : [...s.marks, sq] }
        : { ...s, arrows: s.arrows.some((a) => a.from === g.from && a.to === sq) ? s.arrows.filter((a) => !(a.from === g.from && a.to === sq)) : [...s.arrows, { from: g.from, to: sq }] });
      return;
    }
    setDrag(null);
    setHover(null);
    if (g.moved) {
      if (sq && sq !== g.from) attempt(g.from, sq, true, g.id);
    } else if (g.wasSelected && sq === g.from) setSelected(null);       // a second click on the selected piece deselects
  };

  const dests = selected ? legal?.get(selected) ?? [] : [];
  const view = (sq: string) => sqToView(sq, orientation);
  const pos = (sq: string) => { const [c, r] = view(sq); return { left: `${c * 12.5}%`, top: `${r * 12.5}%` }; };
  const shown: Arrow[] = [...arrows, ...shapes.arrows.map((a) => ({ ...a, kind: "user" as const })), ...(preview ? [{ ...preview, kind: "user" as const }] : [])];

  return (
    <div ref={root} className="board" role="application" aria-label="Chess board" onContextMenu={(e) => e.preventDefault()}
      onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerCancel={() => { gesture.current = null; setDrag(null); setHover(null); setPreview(null); }}>
      <div className="layer">
        {lastMove?.map((sq) => <div key={sq} className="sq move" style={pos(sq)} />)}
        {selected && <div className="sq select" style={pos(selected)} />}
        {checkSquare && <div className="sq check" style={pos(checkSquare)} />}
        {[...marks, ...shapes.marks].map((sq) => <div key={"m" + sq} className="sq mark" style={pos(sq)} />)}
        {dests.map((sq) => <div key={"d" + sq} className={"sq " + (byId.has(sq) ? "ring" : "dot")} style={pos(sq)} />)}
        {drag && hover && dests.includes(hover) && <div className="sq hover" style={pos(hover)} />}
      </div>
      {showCoords && (
        <div className="layer" aria-hidden>
          {Array.from({ length: 8 }, (_, i) => {
            const rankSq = viewToSq(0, i, orientation), fileSq = viewToSq(i, 7, orientation);
            const lightRank = i % 2 === 0, lightFile = (i + 7) % 2 === 0;
            return (
              <span key={i}>
                <span className="coord" style={{ left: 4, top: `calc(${i * 12.5}% + 3px)`, color: lightRank ? "var(--sq-light-text)" : "var(--sq-dark-text)" }}>{rankSq[1]}</span>
                <span className="coord" style={{ right: `calc(${(7 - i) * 12.5}% + 4px)`, bottom: 3, color: lightFile ? "var(--sq-light-text)" : "var(--sq-dark-text)" }}>{fileSq[0]}</span>
              </span>
            );
          })}
        </div>
      )}
      <div className="layer">
        {pieces.map((p) => {
          const [c, r] = view(p.sq);
          return <div key={p.id} className={"piece" + (instant === p.id ? " fresh" : "")} data-sq={p.sq}
            style={{ transform: `translate(${c * 100}%, ${r * 100}%)`, backgroundImage: `url("${pieceSet.url(p)}")`, opacity: drag?.id === p.id ? 0.3 : 1, zIndex: p.role === "k" ? 2 : 1 }} />;
        })}
      </div>
      <Arrows arrows={shown} orientation={orientation} />
      {drag && <div ref={dragEl} className="piece drag" style={{ backgroundImage: `url("${pieceSet.url(drag)}")` }} />}
      {promo && <PromotionPicker colour={turn} sq={promo.to} orientation={orientation} pieceSet={pieceSet} onPick={(role) => { const m = promo; setPromo(null); onMove?.(m.from, m.to, role); }} />}
    </div>
  );
});

const PROMO_NAMES: Partial<Record<Role, string>> = { q: "Queen", n: "Knight", r: "Rook", b: "Bishop" };

function PromotionPicker({ colour, sq, orientation, pieceSet, onPick }: { colour: "w" | "b"; sq: string; orientation: Orientation; pieceSet: PieceSet; onPick: (r: Role) => void }) {
  const [c, r] = sqToView(sq, orientation);
  const top = r === 0 ? 0 : 50;                                         // the picker opens away from the edge: downwards from the top edge, upwards from the bottom edge
  return (
    <div className="promo" style={{ left: `${c * 12.5}%`, top: `${top}%` }} onPointerDown={(e) => e.stopPropagation()} role="menu" aria-label="Promote to">
      {(["q", "n", "r", "b"] as Role[]).map((role) => (
        <button key={role} role="menuitem" aria-label={PROMO_NAMES[role]} style={{ backgroundImage: `url("${pieceSet.url({ colour, role })}")` }} onClick={() => onPick(role)} />
      ))}
    </div>
  );
}

export { FILES };
