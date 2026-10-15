import { describe, expect, it } from "vitest";
import { applyUci, checkSquare, fensFromUci, isPromotion, legalMap, START_FEN, uciToSan } from "./game";
import { formatEval, winPercent } from "./types";

describe("game helpers", () => {
  it("lists the legal moves per square", () => {
    const m = legalMap(START_FEN);
    expect([...m.values()].flat()).toHaveLength(20);
    expect(m.get("e2")).toEqual(expect.arrayContaining(["e3", "e4"]));
    expect(m.has("e1")).toBe(false);
  });
  it("finds the king in check", () => {
    expect(checkSquare(START_FEN)).toBeNull();
    expect(checkSquare("rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3")).toBe("e1");
  });
  it("replays UCI moves into FENs, applies and prints moves", () => {
    const fens = fensFromUci(["e2e4", "e7e5"]);
    expect(fens).toHaveLength(3);
    expect(fens[2].startsWith("rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w")).toBe(true);
    expect(applyUci(START_FEN, "e2e5")).toBeNull();
    expect(uciToSan(START_FEN, "g1f3")).toBe("Nf3");
    expect(uciToSan(START_FEN, "e2e5")).toBe("e2e5");
  });
  it("knows a promotion", () => {
    const fen = "8/P6k/8/8/8/8/8/K7 w - - 0 1";
    expect(isPromotion(fen, "a7", "a8")).toBe(true);
    expect(isPromotion(START_FEN, "e2", "e4")).toBe(false);
  });
});

describe("evaluation formatting", () => {
  it("shows pawns with a sign and caps mate-like values", () => {
    expect(formatEval(130)).toBe("+1.3");
    expect(formatEval(-45)).toBe("-0.5");
    expect(formatEval(0)).toBe("0.0");
    expect(formatEval(1500)).toBe("+M");
  });
  it("turns centipawns into a win chance that is symmetric and bounded", () => {
    expect(winPercent(0)).toBeCloseTo(50);
    expect(winPercent(300) + winPercent(-300)).toBeCloseTo(100);
    expect(winPercent(1500)).toBeLessThan(100);
  });
});
