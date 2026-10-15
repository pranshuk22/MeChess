import { memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { ClassIcon } from "@/components/ClassIcon";
import { isPromotion } from "@/lib/game";
import type { MoveClass } from "@/lib/types";
import { useBoardTheme, usePieceSet } from "@/state/ui";
import { Arrows, type Arrow } from "./Arrows";
import { matchPieces, parsePieces, sqToView, viewToSq, type KeyedPiece, type Orientation } from "./geometry";
import type { PieceSet, Role } from "./pieces";
import type { BoardTheme } from "./themes";

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
  /** the class of the move just played, shown as a badge on the square it went to */
  badge?: { sq: string; cls: MoveClass } | null;
  /** override the player's chosen themes (used by previews) */
  pieceSet?: PieceSet;
  theme?: BoardTheme;
  showCoords?: boolean;
  onMove?: (from: string, to: string, promotion?: Role) => void;
}

type Shapes = { arrows: { from: string; to: string }[]; marks: string[] };
const EMPTY: Shapes = { arrows: [], marks: [] };
const MOVE_LIMIT_FOR_ANIMATION = 4;                                    // more pieces than this changing square (a jump through the game) is shown at once, not animated

/** The board: DOM pieces moved with CSS transforms only (GPU, no layout), pointer events for mouse and touch. While a piece is dragged nothing is re-rendered:
 *  its transform is written once per frame straight to the element from a cached board rectangle. */
export const Board = memo(function Board(props: BoardProps) {
  const { fen, orientation = "white", legal, movable = null, lastMove, checkSquare, arrows = [], marks = [], badge, showCoords = true, onMove } = props;
  const themed = useBoardTheme(), chosen = usePieceSet();
  const theme = props.theme ?? themed, pieceSet = props.pieceSet ?? chosen;
  const root = useRef<HTMLDivElement>(null);
  const prev = useRef<KeyedPiece[]>([]);
  const prevOrientation = useRef(orientation);
  const { pieces, instantAll } = useMemo(() => {
    const list = matchPieces(prev.current, parsePieces(fen));
    const before = new Map(prev.current.map((p) => [p.id, p.sq]));
    const moved = list.filter((p) => before.get(p.id) !== p.sq).length;
    return { pieces: list, instantAll: prevOrientation.current !== orientation || (prev.current.length > 0 && moved > MOVE_LIMIT_FOR_ANIMATION) };
  }, [fen, orientation]);
  useEffect(() => { prev.current = pieces; prevOrientation.current = orientation; }, [pieces, orientation]);

  const [selected, setSelected] = useState<string | null>(null);
  const [hover, setHover] = useState<string | null>(null);
  const [drag, setDrag] = useState<KeyedPiece | null>(null);
  const [instant, setInstant] = useState<number | null>(null);
  const [promo, setPromo] = useState<{ from: string; to: string } | null>(null);
  const [shapes, setShapes] = useState<Shapes>(EMPTY);
  const [preview, setPreview] = useState<{ from: string; to: string } | null>(null);
  const dragEl = useRef<HTMLDivElement>(null);
  const rect = useRef<DOMRect | null>(null);                           // the board's rectangle, read once per gesture (reading it on every move forces a layout)
  const pointer = useRef({ x: 0, y: 0 });
  const frame = useRef(0);
  const gesture = useRef<{ kind: "left" | "right"; from: string; id?: number; moved: boolean; wasSelected: boolean } | null>(null);

  const turn = fen.split(" ")[1] as "w" | "b";
  const bySquare = useMemo(() => new Map(pieces.map((p) => [p.sq, p])), [pieces]);
  const canMove = (colour: "w" | "b") => !!legal && legal.size > 0 && colour === turn && (movable === "both" || movable === colour);

  useEffect(() => { setSelected(null); setPromo(null); setShapes(EMPTY); }, [fen]);
  useEffect(() => { setShapes(EMPTY); }, [orientation]);
  useEffect(() => () => cancelAnimationFrame(frame.current), []);

  const squareAt = useCallback((x: number, y: number): string | null => {
    const r = rect.current ?? root.current!.getBoundingClientRect();
    const col = Math.floor(((x - r.left) / r.width) * 8), row = Math.floor(((y - r.top) / r.height) * 8);
    return col < 0 || col > 7 || row < 0 || row > 7 ? null : viewToSq(col, row, orientation);
  }, [orientation]);

  const place = useCallback(() => {
    const el = dragEl.current, r = rect.current;
    if (!el || !r) return;
    const size = r.width / 8;
    el.style.transform = `translate3d(${pointer.current.x - r.left - size / 2}px, ${pointer.current.y - r.top - size / 2}px, 0) scale(1.08)`;
  }, []);
  useLayoutEffect(() => { if (drag) place(); }, [drag, place]);          // before the first paint: the picked-up piece never shows at the board's corner

  const attempt = (from: string, to: string, fromDrop: boolean, id?: number) => {
    if (!legal?.get(from)?.includes(to)) return false;
    if (isPromotion(fen, from, to)) { setPromo({ from, to }); setSelected(null); return true; }
    if (fromDrop && id !== undefined) { setInstant(id); requestAnimationFrame(() => requestAnimationFrame(() => setInstant(null))); }   // the piece is already under the cursor: no slide
    setSelected(null);
    onMove?.(from, to);
    return true;
  };

  const begin = (e: React.PointerEvent) => {
    rect.current = root.current!.getBoundingClientRect();
    pointer.current = { x: e.clientX, y: e.clientY };
    root.current!.setPointerCapture(e.pointerId);
  };

  const onPointerDown = (e: React.PointerEvent) => {
    rect.current = root.current!.getBoundingClientRect();
    const sq = squareAt(e.clientX, e.clientY);
    if (!sq) return;
    if (e.button === 2) { gesture.current = { kind: "right", from: sq, moved: false, wasSelected: false }; begin(e); return; }
    if (e.button !== 0) return;
    if (shapes.arrows.length || shapes.marks.length) setShapes(EMPTY);
    if (promo) { setPromo(null); return; }
    if (selected && attempt(selected, sq, false)) return;
    const p = bySquare.get(sq);
    if (p && canMove(p.colour)) {
      const wasSelected = selected === sq;
      setSelected(sq);
      gesture.current = { kind: "left", from: sq, id: p.id, moved: false, wasSelected };
      begin(e);
    } else setSelected(null);
  };

  const onPointerMove = (e: React.PointerEvent) => {
    const g = gesture.current;
    if (!g) return;
    pointer.current = { x: e.clientX, y: e.clientY };
    const sq = squareAt(e.clientX, e.clientY);
    if (g.kind === "right") { setPreview(sq && sq !== g.from ? { from: g.from, to: sq } : null); return; }
    if (!g.moved) {
      const p = bySquare.get(g.from);
      if (!p) return;
      g.moved = true;
      setDrag(p);
    } else if (!frame.current) {
      frame.current = requestAnimationFrame(() => { frame.current = 0; place(); });   // at most one style write per frame
    }
    setHover((h) => (h === sq ? h : sq));
  };

  const finish = (e: React.PointerEvent) => {
    const g = gesture.current;
    gesture.current = null;
    cancelAnimationFrame(frame.current);
    frame.current = 0;
    if (!g) return;
    const sq = squareAt(e.clientX, e.clientY);
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
    if (g.moved) { if (sq && sq !== g.from) attempt(g.from, sq, true, g.id); }
    else if (g.wasSelected && sq === g.from) setSelected(null);          // a second click on the selected piece deselects
  };

  const dests = selected ? legal?.get(selected) ?? [] : [];
  const view = (sq: string) => sqToView(sq, orientation);
  const pos = (sq: string) => { const [c, r] = view(sq); return { left: `${c * 12.5}%`, top: `${r * 12.5}%` }; };
  const shown: Arrow[] = [...arrows, ...shapes.arrows.map((a) => ({ ...a, kind: "user" as const })), ...(preview ? [{ ...preview, kind: "user" as const }] : [])];
  const badgePos = badge ? (() => { const [c, r] = view(badge.sq); return { left: `calc(${(c + 1) * 12.5}% - 2px)`, top: `calc(${r * 12.5}% + 2px)` }; })() : null;

  return (
    <div ref={root} className="board" data-grain={theme.grain ? "1" : "0"} role="application" aria-label="Chess board" style={{ "--sq-light": theme.light, "--sq-dark": theme.dark } as React.CSSProperties}
      onContextMenu={(e) => e.preventDefault()} onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={finish} onPointerCancel={() => { gesture.current = null; setDrag(null); setHover(null); setPreview(null); }}>
      <div className="layer">
        {lastMove?.map((sq) => <div key={sq} className="sq move" style={pos(sq)} />)}
        {selected && <div className="sq select" style={pos(selected)} />}
        {checkSquare && <div className="sq check" style={pos(checkSquare)} />}
        {[...marks, ...shapes.marks].map((sq) => <div key={"m" + sq} className="sq mark" style={pos(sq)} />)}
        {dests.map((sq) => <div key={"d" + sq} className={"sq " + (bySquare.has(sq) ? "ring" : "dot")} style={pos(sq)} />)}
        {drag && hover && dests.includes(hover) && <div className="sq hover" style={pos(hover)} />}
      </div>
      {showCoords && (
        <div className="layer" aria-hidden>
          {Array.from({ length: 8 }, (_, i) => {
            const rank = viewToSq(0, i, orientation)[1], file = viewToSq(i, 7, orientation)[0];
            return (
              <span key={i}>
                <span className={"coord " + (i % 2 === 0 ? "on-light" : "on-dark")} style={{ left: 4, top: `calc(${i * 12.5}% + 3px)` }}>{rank}</span>
                <span className={"coord " + ((i + 7) % 2 === 0 ? "on-light" : "on-dark")} style={{ right: `calc(${(7 - i) * 12.5}% + 4px)`, bottom: 3 }}>{file}</span>
              </span>
            );
          })}
        </div>
      )}
      <div className="layer">
        {pieces.map((p) => {
          const [c, r] = view(p.sq);
          return <div key={p.id} className={"piece" + (instantAll || instant === p.id ? " fresh" : "")} data-sq={p.sq}
            style={{ transform: `translate3d(${c * 100}%, ${r * 100}%, 0)`, backgroundImage: `url("${pieceSet.url(p)}")`, opacity: drag?.id === p.id ? 0.3 : 1, zIndex: p.role === "k" ? 2 : 1 }} />;
        })}
      </div>
      <Arrows arrows={shown} orientation={orientation} />
      {badge && badgePos && <div className="badge-pos" style={{ position: "absolute", zIndex: 6, transform: "translate(-100%, 0)", pointerEvents: "none", ...badgePos }}><ClassIcon cls={badge.cls} size={24} style={{ boxShadow: "0 0 0 1.5px rgba(255,255,255,.95)" }} /></div>}
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
