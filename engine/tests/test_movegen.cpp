#include <algorithm>

#include "test_framework.h"
#include "../src/board/position.h"
#include "../src/movegen/movegen.h"

using namespace chess;

static MoveList legal_for(const char* fen, Position* keep = nullptr) {
  Position p;
  CHECK(p.set_fen(fen));
  MoveList l;
  generate_legal(p, l);
  if (keep) *keep = p;
  return l;
}
static bool has(const MoveList& l, const char* uci) {
  for (Move m : l)
    if (move_to_uci(m) == uci) return true;
  return false;
}

TEST(MoveGen, StartPositionHas20Moves) { CHECK_EQ(legal_for(Position::START_FEN).count, 20); }

TEST(MoveGen, KiwipeteHas48Moves) {
  CHECK_EQ(legal_for("r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1").count, 48);
}

TEST(MoveGen, CastlingBothSidesWhenClear) {
  MoveList l = legal_for("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1");
  CHECK(has(l, "e1g1"));
  CHECK(has(l, "e1c1"));
}

TEST(MoveGen, NoCastlingThroughAttackedSquare) {
  // Black rook on f8 covers f1: white cannot castle king-side, may still castle queen-side.
  MoveList l = legal_for("4kr2/8/8/8/8/8/8/R3K2R w KQ - 0 1");
  CHECK(!has(l, "e1g1"));
  CHECK(has(l, "e1c1"));
}

TEST(MoveGen, NoCastlingOutOfCheck) {
  MoveList l = legal_for("4r1k1/8/8/8/8/8/8/R3K2R w KQ - 0 1");
  CHECK(!has(l, "e1g1"));
  CHECK(!has(l, "e1c1"));
}

TEST(MoveGen, NoCastlingWithPieceInTheWay) {
  MoveList l = legal_for("4k3/8/8/8/8/8/8/RN2K1NR w KQ - 0 1");
  CHECK(!has(l, "e1g1"));
  CHECK(!has(l, "e1c1"));
}

TEST(MoveGen, CastlingAllowedWhenOnlyRookPathIsAttacked) {
  // b1 is attacked but the king does not cross it: queen-side castling is legal.
  MoveList l = legal_for("1r2k3/8/8/8/8/8/8/R3K3 w Q - 0 1");
  CHECK(has(l, "e1c1"));
}

TEST(MoveGen, EnPassantGenerated) {
  MoveList l = legal_for("rnbqkbnr/ppp1p1pp/8/3pPp2/8/8/PPPP1PPP/RNBQKBNR w KQkq f6 0 3");
  CHECK(has(l, "e5f6"));
}

TEST(MoveGen, EnPassantIllegalWhenItExposesKingAlongRank) {
  // White Ka5, Pb5; black pawn just played c7-c5; black rook on h5. bxc6 would open the 5th rank.
  MoveList l = legal_for("8/8/8/KPp4r/8/8/8/7k w - c6 0 1");
  CHECK(!has(l, "b5c6"));
  CHECK(has(l, "b5b6"));
}

TEST(MoveGen, EnPassantOfferedAlongsideNormalPush) {
  MoveList l = legal_for("4k3/8/8/2pP4/8/8/8/4K3 w - c6 0 1");
  CHECK(has(l, "d5c6"));
  CHECK(has(l, "d5d6"));
}

TEST(MoveGen, PromotionsAllFourPieces) {
  MoveList l = legal_for("8/P7/8/8/8/8/8/k6K w - - 0 1");
  CHECK(has(l, "a7a8q"));
  CHECK(has(l, "a7a8r"));
  CHECK(has(l, "a7a8b"));
  CHECK(has(l, "a7a8n"));
  CHECK(!has(l, "a7a8"));
  CHECK_EQ(l.count, 7);  // 4 promotions + 3 king moves
}

TEST(MoveGen, PromotionWithCapture) {
  MoveList l = legal_for("1n2k3/P7/8/8/8/8/8/4K3 w - - 0 1");
  CHECK(has(l, "a7b8q"));
  CHECK(has(l, "a7b8n"));
  CHECK(has(l, "a7a8q"));
}

TEST(MoveGen, PinnedPieceCannotLeaveThePin) {
  MoveList l = legal_for("4k3/8/8/8/4r3/8/4B3/4K3 w - - 0 1");
  for (Move m : l) CHECK(m.from() == 4);  // only king moves are legal
  CHECK_EQ(l.count, 4);
}

TEST(MoveGen, PinnedPieceMayMoveAlongThePin) {
  MoveList l = legal_for("4k3/8/8/8/4r3/8/4R3/4K3 w - - 0 1");
  CHECK(has(l, "e2e3"));
  CHECK(has(l, "e2e4"));  // captures the pinner
  CHECK(!has(l, "e2d2"));
}

TEST(MoveGen, DoubleCheckOnlyKingMoves) {
  // The a1 rook (open rank) and the d3 knight both give check to the king on e1.
  MoveList l = legal_for("4k3/8/8/8/8/3n4/8/r3K2R w - - 0 1");
  CHECK(l.count > 0);
  for (Move m : l) CHECK(m.from() == 4);
}

TEST(MoveGen, CheckmateHasNoMoves) {
  Position p;
  MoveList l = legal_for("7k/6Q1/6K1/8/8/8/8/8 b - - 0 1", &p);
  CHECK_EQ(l.count, 0);
  CHECK(p.in_check());
}

TEST(MoveGen, StalemateHasNoMovesAndNoCheck) {
  Position p;
  MoveList l = legal_for("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1", &p);
  CHECK_EQ(l.count, 0);
  CHECK(!p.in_check());
}

TEST(MoveGen, KingCannotStepIntoCheck) {
  MoveList l = legal_for("4k3/8/8/8/8/8/3r4/4K3 w - - 0 1");
  CHECK(!has(l, "e1d1"));
  CHECK(!has(l, "e1e2"));  // e2 is attacked along the 2nd rank
  CHECK(has(l, "e1d2"));  // capturing the rook is fine
}

TEST(MoveGen, PseudoLegalIsSupersetOfLegal) {
  Position p;
  CHECK(p.set_fen("r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1"));
  MoveList pseudo, legal;
  generate_pseudo_legal(p, pseudo);
  generate_legal(p, legal);
  CHECK(pseudo.count >= legal.count);
  for (Move m : legal) CHECK(std::find(pseudo.begin(), pseudo.end(), m) != pseudo.end());
}

TEST(MoveGen, ParseUciRejectsIllegalAndGarbage) {
  Position p;
  CHECK(parse_uci_move(p, "e2e5").is_null());
  CHECK(parse_uci_move(p, "e1e2").is_null());
  CHECK(parse_uci_move(p, "").is_null());
  CHECK(parse_uci_move(p, "zzzz").is_null());
  CHECK(!parse_uci_move(p, "e2e4").is_null());
  CHECK(!parse_uci_move(p, "g1f3").is_null());
}
