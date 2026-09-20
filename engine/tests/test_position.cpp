#include "test_framework.h"
#include "../src/board/position.h"
#include "../src/movegen/movegen.h"

using namespace chess;

static Move mv(Position& p, const char* uci) {
  Move m = parse_uci_move(p, uci);
  CHECK(!m.is_null());
  return m;
}

TEST(Position, StartPositionLayout) {
  Position p;
  CHECK_EQ(p.fen(), std::string(Position::START_FEN));
  CHECK_EQ(int(p.piece_on(4)), int(make_piece(WHITE, KING)));
  CHECK_EQ(int(p.piece_on(60)), int(make_piece(BLACK, KING)));
  CHECK_EQ(popcount(p.pieces(WHITE, PAWN)), 8);
  CHECK_EQ(popcount(p.occupied()), 32);
  CHECK_EQ(int(p.side_to_move()), int(WHITE));
  CHECK_EQ(int(p.castling()), 15);
}

TEST(Position, FenRoundTrip) {
  const char* fens[] = {
      Position::START_FEN,
      "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
      "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1",
      "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq e6 0 2",
      "r4rk1/1pp1qppp/p1np1n2/2b1p1B1/2B1P1b1/P1NP1N2/1PP1QPPP/R4RK1 b - - 5 12",
      "8/8/8/8/8/8/8/K6k w - - 99 120",
  };
  for (const char* f : fens) {
    Position p;
    CHECK(p.set_fen(f));
    CHECK_EQ(p.fen(), std::string(f));
  }
}

TEST(Position, RejectsMalformedFenAndKeepsState) {
  Position p;
  const std::string before = p.fen();
  const char* bad[] = {
      "", "not a fen", "8/8/8/8/8/8/8/8 w - - 0 1",                        // no kings
      "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBN w KQkq - 0 1",           // short rank
      "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR x KQkq - 0 1",          // bad side
      "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq z9 0 1",         // bad ep
      "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQxq - 0 1",          // bad castling
      "4k3/8/8/8/8/8/4R3/4K3 w - - 0 1",                                   // side not to move is in check
      "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNRR w KQkq - 0 1",         // rank too long
      "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR/8 w KQkq - 0 1",        // too many ranks
  };
  for (const char* f : bad) {
    CHECK(!p.set_fen(f));
    CHECK_EQ(p.fen(), before);
  }
}

TEST(Position, MakeUnmakeRestoresEverything) {
  const char* fens[] = {
      "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
      "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1",
      "rnbqkbnr/ppp1p1pp/8/3pPp2/8/8/PPPP1PPP/RNBQKBNR w KQkq f6 0 3",
  };
  for (const char* f : fens) {
    Position p;
    CHECK(p.set_fen(f));
    MoveList list;
    generate_legal(p, list);
    CHECK(list.count > 0);
    const std::string fen0 = p.fen();
    const uint64_t key0 = p.key();
    for (Move m : list) {
      p.make_move(m);
      CHECK_EQ(p.key(), p.compute_key());
      p.unmake_move(m);
      CHECK_EQ(p.fen(), fen0);
      CHECK_EQ(p.key(), key0);
    }
  }
}

TEST(Position, EnPassantSquareAndCapture) {
  Position p;
  p.make_move(mv(p, "e2e4"));
  CHECK_EQ(p.fen(), std::string("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"));
  p.make_move(mv(p, "a7a6"));
  p.make_move(mv(p, "e4e5"));
  p.make_move(mv(p, "d7d5"));
  CHECK_EQ(int(p.ep_square()), make_square(3, 5));  // d6
  Move ep = mv(p, "e5d6");
  CHECK_EQ(int(ep.flags()), int(EP_CAPTURE));
  p.make_move(ep);
  CHECK_EQ(int(p.piece_on(make_square(3, 4))), int(NO_PIECE));  // captured pawn on d5 is gone
  CHECK_EQ(int(p.piece_on(make_square(3, 5))), int(make_piece(WHITE, PAWN)));
  CHECK_EQ(p.key(), p.compute_key());
  p.unmake_move(ep);
  CHECK_EQ(int(p.piece_on(make_square(3, 4))), int(make_piece(BLACK, PAWN)));
}

TEST(Position, CastlingMovesRookAndClearsRights) {
  Position p;
  CHECK(p.set_fen("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1"));
  p.make_move(mv(p, "e1g1"));
  CHECK_EQ(int(p.piece_on(6)), int(make_piece(WHITE, KING)));
  CHECK_EQ(int(p.piece_on(5)), int(make_piece(WHITE, ROOK)));
  CHECK_EQ(int(p.piece_on(7)), int(NO_PIECE));
  CHECK_EQ(int(p.castling()), int(BLACK_OO | BLACK_OOO));
  p.make_move(mv(p, "e8c8"));
  CHECK_EQ(int(p.piece_on(58)), int(make_piece(BLACK, KING)));
  CHECK_EQ(int(p.piece_on(59)), int(make_piece(BLACK, ROOK)));
  CHECK_EQ(int(p.castling()), 0);
  CHECK_EQ(p.key(), p.compute_key());
}

TEST(Position, RookMoveOrCaptureRemovesCastlingRight) {
  Position p;
  CHECK(p.set_fen("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1"));
  p.make_move(mv(p, "h1h8"));  // rook takes rook: white loses K-side, black loses k-side
  CHECK_EQ(int(p.castling()), int(WHITE_OOO | BLACK_OOO));
}

TEST(Position, PromotionAndUnmake) {
  Position p;
  CHECK(p.set_fen("1n2k3/P7/8/8/8/8/8/4K3 w - - 0 1"));
  const std::string before = p.fen();
  Move m = mv(p, "a7b8q");
  CHECK(m.is_capture() && m.is_promotion());
  p.make_move(m);
  CHECK_EQ(int(p.piece_on(make_square(1, 7))), int(make_piece(WHITE, QUEEN)));
  CHECK_EQ(int(p.piece_on(make_square(0, 6))), int(NO_PIECE));
  p.unmake_move(m);
  CHECK_EQ(p.fen(), before);
}

TEST(Position, HalfmoveClockAndFullmove) {
  Position p;
  p.make_move(mv(p, "g1f3"));
  CHECK_EQ(p.halfmove_clock(), 1);
  CHECK_EQ(p.fullmove_number(), 1);
  p.make_move(mv(p, "g8f6"));
  CHECK_EQ(p.halfmove_clock(), 2);
  CHECK_EQ(p.fullmove_number(), 2);
  p.make_move(mv(p, "e2e4"));  // pawn move resets
  CHECK_EQ(p.halfmove_clock(), 0);
}

TEST(Position, TranspositionsShareAKey) {
  Position a, b;
  for (const char* m : {"g1f3", "g8f6", "b1c3", "b8c6"}) a.make_move(mv(a, m));
  for (const char* m : {"b1c3", "b8c6", "g1f3", "g8f6"}) b.make_move(mv(b, m));
  CHECK_EQ(a.key(), b.key());
  CHECK_EQ(a.fen(), b.fen());
}

TEST(Position, KeyDependsOnSideCastlingAndEp) {
  Position w, b, nc, ep;
  CHECK(w.set_fen("4k3/8/8/8/8/8/8/4K3 w - - 0 1"));
  CHECK(b.set_fen("4k3/8/8/8/8/8/8/4K3 b - - 0 1"));
  CHECK(w.key() != b.key());
  CHECK(nc.set_fen("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1"));
  Position nc2;
  CHECK(nc2.set_fen("r3k2r/8/8/8/8/8/8/R3K2R w Kkq - 0 1"));
  CHECK(nc.key() != nc2.key());
  // ep square only matters when a pawn can actually capture onto it
  Position with_ep, without_ep, capturable, capturable_no_ep;
  CHECK(with_ep.set_fen("4k3/8/8/8/4P3/8/8/4K3 b - e3 0 1"));
  CHECK(without_ep.set_fen("4k3/8/8/8/4P3/8/8/4K3 b - - 0 1"));
  CHECK_EQ(with_ep.key(), without_ep.key());  // no black pawn can take: identical for hashing
  CHECK(capturable.set_fen("4k3/8/8/8/3pP3/8/8/4K3 b - e3 0 1"));
  CHECK(capturable_no_ep.set_fen("4k3/8/8/8/3pP3/8/8/4K3 b - - 0 1"));
  CHECK(capturable.key() != capturable_no_ep.key());
}

TEST(Position, NullMoveRestores) {
  Position p;
  CHECK(p.set_fen("rnbqkbnr/ppp1p1pp/8/3pPp2/8/8/PPPP1PPP/RNBQKBNR w KQkq f6 0 3"));
  const std::string fen = p.fen();
  const uint64_t key = p.key();
  p.make_null_move();
  CHECK_EQ(int(p.side_to_move()), int(BLACK));
  CHECK_EQ(int(p.ep_square()), int(SQ_NONE));
  p.unmake_null_move();
  CHECK_EQ(p.fen(), fen);
  CHECK_EQ(p.key(), key);
}

TEST(Position, RepetitionDetected) {
  Position p;
  CHECK(!p.is_repetition());
  for (const char* m : {"g1f3", "g8f6", "f3g1"}) p.make_move(mv(p, m));
  CHECK(!p.is_repetition());
  p.make_move(mv(p, "f6g8"));
  CHECK(p.is_repetition());  // back to the start position
}

TEST(Position, RepetitionNotFoundAcrossIrreversibleMove) {
  Position p;
  for (const char* m : {"g1f3", "g8f6", "f3g1", "e7e6", "g1f3", "f6g8"}) p.make_move(mv(p, m));
  // e7e6 is a pawn move, so no earlier position can recur.
  CHECK(!p.is_repetition());
}

TEST(Position, InsufficientMaterial) {
  struct C { const char* fen; bool expect; };
  const C cases[] = {
      {"8/8/8/4k3/8/8/8/4K3 w - - 0 1", true},
      {"8/8/8/4k3/8/8/8/3NK3 w - - 0 1", true},
      {"8/8/8/4k3/8/8/8/3BK3 w - - 0 1", true},
      {"8/8/8/4k3/8/8/8/2NNK3 w - - 0 1", false},  // two knights: not automatically drawn here
      {"8/8/8/4k3/8/8/4P3/4K3 w - - 0 1", false},
      {"8/8/8/4k3/8/8/8/3RK3 w - - 0 1", false},
      {"8/8/8/4k3/8/8/8/3QK3 w - - 0 1", false},
  };
  for (const C& c : cases) {
    Position p;
    CHECK(p.set_fen(c.fen));
    CHECK_EQ(p.insufficient_material(), c.expect);
  }
}

TEST(Position, AttackedSquares) {
  Position p;
  CHECK(p.set_fen("4k3/8/8/8/8/2n5/8/R3K2R w KQ - 0 1"));
  CHECK(p.attacked(make_square(0, 7), WHITE));     // a8 seen by the a1 rook
  CHECK(!p.attacked(make_square(1, 3), WHITE));    // b4 not attacked by white
  CHECK(p.attacked(make_square(3, 0), BLACK));     // d1 attacked by the c3 knight
  CHECK(p.attacked(make_square(4, 0), BLACK) == false);  // e1: knight on c3 does not hit e1
  CHECK(p.attacked(make_square(4, 1), BLACK));     // e2 is hit by the knight
}
