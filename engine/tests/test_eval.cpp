#include "test_framework.h"
#include "../src/board/position.h"
#include "../src/eval/eval.h"

using namespace chess;

static int eval_of(const char* fen) {
  Position p;
  CHECK(p.set_fen(fen));
  return evaluate(p);
}

TEST(Eval, StartPositionIsJustTempo) {
  CHECK_EQ(eval_of(Position::START_FEN), 10);
}

TEST(Eval, ExtraQueenIsWinning) {
  CHECK(eval_of("rnb1kbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1") > 800);
  CHECK(eval_of("rnb1kbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR b KQkq - 0 1") < -800);  // same, other POV
}

TEST(Eval, ColourFlippedPositionEvaluatesTheSame) {
  // A position and its colour-mirrored twin (ranks flipped, colours swapped, side flipped) must match.
  const int a = eval_of("r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3");
  const int b = eval_of("rnbqkb1r/pppp1ppp/5n2/4p3/4P3/2N5/PPPP1PPP/R1BQKBNR b KQkq - 2 3");
  CHECK_EQ(a, b);
}

TEST(Eval, CentralKnightBeatsRimKnight) {
  const int centre = eval_of("4k3/8/8/8/3N4/8/8/4K3 w - - 0 1");
  const int rim = eval_of("4k3/8/8/8/8/8/8/N3K3 w - - 0 1");
  CHECK(centre > rim);
}

TEST(Eval, AdvancedPassedPawnBeatsHomePawn) {
  const int advanced = eval_of("4k3/8/4P3/8/8/8/8/4K3 w - - 0 1");
  const int home = eval_of("4k3/8/8/8/8/8/4P3/4K3 w - - 0 1");
  CHECK(advanced > home);
}

TEST(Eval, BishopPairBonus) {
  const int pair = eval_of("4k3/8/8/8/8/8/8/2B1KB2 w - - 0 1");
  const int mixed = eval_of("4k3/8/8/8/8/8/8/2B1KN2 w - - 0 1");
  CHECK(pair > mixed);
}

TEST(Eval, KingPrefersCentreInEndgameButNotMiddlegame) {
  const int eg_centre = eval_of("4k3/8/8/8/4K3/8/8/8 w - - 0 1");
  const int eg_corner = eval_of("4k3/8/8/8/8/8/8/K7 w - - 0 1");
  CHECK(eg_centre > eg_corner);
  // With the full army on the board, a castled king beats a centralised one (same pieces otherwise).
  const int castled = eval_of("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQ1RK1 w kq - 0 1");
  const int central = eval_of("rnbqkbnr/pppppppp/8/8/8/4K3/PPPPPPPP/RNBQ1R2 w kq - 0 1");
  CHECK(castled > central);
}
