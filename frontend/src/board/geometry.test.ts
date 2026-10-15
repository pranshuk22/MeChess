import { describe, expect, it } from "vitest";
import { START_FEN } from "@/lib/game";
import { coordsToSq, matchPieces, parsePieces, sqToCoords, sqToView, viewToSq } from "./geometry";

describe("geometry", () => {
  it("maps squares to the screen for both orientations and back", () => {
    expect(sqToView("a1", "white")).toEqual([0, 7]);
    expect(sqToView("a1", "black")).toEqual([7, 0]);
    expect(sqToView("h8", "white")).toEqual([7, 0]);
    for (const o of ["white", "black"] as const) for (let f = 0; f < 8; f++) for (let r = 0; r < 8; r++) {
      const [c, row] = sqToView(coordsToSq(f, r), o);
      expect(viewToSq(c, row, o)).toBe(coordsToSq(f, r));
    }
    expect(sqToCoords("e4")).toEqual([4, 3]);
  });

  it("reads the pieces of a FEN", () => {
    const p = parsePieces(START_FEN);
    expect(p).toHaveLength(32);
    expect(p.filter((x) => x.colour === "w" && x.role === "p")).toHaveLength(8);
    expect(p.find((x) => x.sq === "e1")).toMatchObject({ colour: "w", role: "k" });
    expect(p.find((x) => x.sq === "d8")).toMatchObject({ colour: "b", role: "q" });
  });
});

describe("matchPieces keeps a piece's identity across a move so it can animate", () => {
  const start = matchPieces([], parsePieces(START_FEN));
  const afterE4 = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1";
  it("the moved pawn keeps its id, the others do not change", () => {
    const next = matchPieces(start, parsePieces(afterE4));
    const e2 = start.find((p) => p.sq === "e2")!, e4 = next.find((p) => p.sq === "e4")!;
    expect(e4.id).toBe(e2.id);
    for (const p of start.filter((q) => q.sq !== "e2")) expect(next.find((q) => q.id === p.id)?.sq).toBe(p.sq);
  });
  it("a capture removes the captured piece and moves the capturer", () => {
    const before = matchPieces([], parsePieces("4k3/8/8/3p4/4P3/8/8/4K3 w - - 0 1"));
    const after = matchPieces(before, parsePieces("4k3/8/8/3P4/8/8/8/4K3 b - - 0 1"));
    expect(after).toHaveLength(3);
    expect(after.find((p) => p.sq === "d5")!.id).toBe(before.find((p) => p.sq === "e4")!.id);
  });
  it("castling moves both the king and the rook", () => {
    const before = matchPieces([], parsePieces("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1"));
    const after = matchPieces(before, parsePieces("r3k2r/8/8/8/8/8/8/R4RK1 b kq - 1 1"));
    expect(after.find((p) => p.sq === "g1")!.id).toBe(before.find((p) => p.sq === "e1")!.id);
    expect(after.find((p) => p.sq === "f1")!.id).toBe(before.find((p) => p.sq === "h1")!.id);
  });
  it("a promotion gives a new piece and the pawn's id is dropped", () => {
    const before = matchPieces([], parsePieces("8/P6k/8/8/8/8/8/K7 w - - 0 1"));
    const after = matchPieces(before, parsePieces("Q7/7k/8/8/8/8/8/K7 b - - 0 1"));
    expect(after.find((p) => p.sq === "a8")!.id).not.toBe(before.find((p) => p.sq === "a7")!.id);
  });
});
