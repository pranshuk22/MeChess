#include <cmath>
#include <atomic>
#include <chrono>
#include <thread>

#include "test_framework.h"
#include "../src/board/position.h"
#include "../src/movegen/movegen.h"
#include "../src/search/search.h"

using namespace chess;

static SearchResult run(const char* fen, int depth, Position* out_pos = nullptr, size_t hash_mb = 4) {
  Position p;
  CHECK(p.set_fen(fen));
  Searcher s(hash_mb);
  std::atomic<bool> stop{false};
  Limits lim;
  lim.depth = depth;
  SearchResult r = s.search(p, lim, stop);
  if (out_pos) *out_pos = p;
  return r;
}

static std::string best(const SearchResult& r) { return move_to_uci(r.best_move); }

TEST(Search, FindsMateInOne) {
  SearchResult r = run("6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1", 4);
  CHECK_EQ(best(r), std::string("d1d8"));
  CHECK_EQ(r.score, MATE - 1);
}

TEST(Search, FindsScholarsMate) {
  SearchResult r = run("r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4", 4);
  CHECK_EQ(best(r), std::string("h5f7"));
  CHECK(is_mate_score(r.score));
}

TEST(Search, FindsMateInTwo) {
  // Kc6-style ladder: 1.Ra7+ (or Rh7) Kg8?? not forced; use the classic KRK: white to mate in 2.
  SearchResult r = run("7k/8/5K2/8/8/8/8/1R6 w - - 0 1", 5);
  CHECK(is_mate_score(r.score));
  CHECK_EQ(r.score, MATE - 3);  // mate delivered on white's 2nd move = ply 3
}

TEST(Search, GetsMatedScoreForTheLosingSide) {
  // Black to move, mate in 1 for white after any move? Simply: black is already lost in 1 (ply 2).
  SearchResult r = run("7k/8/5K2/8/8/8/8/1R6 b - - 0 1", 5);
  CHECK(r.score <= -MATE_IN_MAX);
}

TEST(Search, MateScoreIsIndependentOfDepthAndHashState) {
  SearchResult shallow = run("6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1", 2);
  SearchResult deep = run("6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1", 8);
  CHECK_EQ(shallow.score, MATE - 1);
  CHECK_EQ(deep.score, MATE - 1);
}

TEST(Search, TakesAFreeQueen) {
  SearchResult r = run("4k3/8/8/3q4/8/8/8/3RK3 w - - 0 1", 4);
  CHECK_EQ(best(r), std::string("d1d5"));
  CHECK(r.score > 400);  // a rook up, with the enemy queen gone
}

TEST(Search, DoesNotHangItsQueen) {
  // Qxd5 loses the queen to the c6 pawn; a sane engine plays something else.
  SearchResult r = run("4k3/8/2p5/3p4/8/8/3Q4/4K3 w - - 0 1", 5);
  CHECK(best(r) != "d2d5");
}

TEST(Search, StalemateAndCheckmateRootsReturnNullMove) {
  SearchResult mated = run("7k/6Q1/6K1/8/8/8/8/8 b - - 0 1", 3);
  CHECK(mated.best_move.is_null());
  CHECK_EQ(mated.score, -MATE);
  SearchResult stale = run("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1", 3);
  CHECK(stale.best_move.is_null());
  CHECK_EQ(stale.score, 0);
}

TEST(Search, AvoidsStalematingWhenWinning) {
  // White is a queen up. Qb1-g6?? would be stalemate; the engine must keep the win instead.
  const char* fen = "7k/8/5K2/8/8/8/8/1Q6 w - - 0 1";
  SearchResult r = run(fen, 5);
  CHECK(r.score > 500);
  CHECK(best(r) != "b1g6");
  Position p;
  CHECK(p.set_fen(fen));
  p.make_move(r.best_move);
  MoveList l;
  generate_legal(p, l);
  CHECK(l.count > 0 || p.in_check());  // black has a move, or it is mate; never stalemate
}

TEST(Search, DrawnPositionsScoreZero) {
  CHECK_EQ(run("8/8/8/4k3/8/8/8/4K3 w - - 0 1", 4).score, 0);        // K v K
  CHECK_EQ(run("8/8/8/4k3/8/8/8/3NK3 w - - 0 1", 4).score, 0);       // K+N v K
}

TEST(Search, RootPositionIsRestored) {
  Position p;
  const char* fen = "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1";
  run(fen, 5, &p);
  CHECK_EQ(p.fen(), std::string(fen));
  Position q;
  CHECK(q.set_fen(fen));
  CHECK_EQ(p.key(), q.key());
}

TEST(Search, BestMoveIsAlwaysLegal) {
  const char* fens[] = {
      Position::START_FEN,
      "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
      "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1",
      "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1",
      "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8",
  };
  for (const char* f : fens) {
    Position p;
    CHECK(p.set_fen(f));
    SearchResult r = run(f, 4);
    MoveList l;
    generate_legal(p, l);
    bool found = false;
    for (Move m : l) found |= (m == r.best_move);
    CHECK(found);
  }
}

TEST(Search, PvStartsWithBestMoveAndIsLegal) {
  Position p;
  const char* fen = "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1";
  SearchResult r = run(fen, 5);
  CHECK(!r.pv.empty());
  CHECK(r.pv[0] == r.best_move);
  CHECK(p.set_fen(fen));
  for (Move m : r.pv) {
    MoveList l;
    generate_legal(p, l);
    bool ok = false;
    for (Move x : l) ok |= (x == m);
    CHECK(ok);
    if (!ok) break;
    p.make_move(m);
  }
}

TEST(Search, IsDeterministic) {
  const char* fen = "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1";
  SearchResult a = run(fen, 6), b = run(fen, 6);
  CHECK(a.best_move == b.best_move);
  CHECK_EQ(a.score, b.score);
  CHECK_EQ(a.nodes, b.nodes);
}

TEST(Search, NodeLimitIsRespected) {
  Position p;
  CHECK(p.set_fen(Position::START_FEN));
  Searcher s(4);
  std::atomic<bool> stop{false};
  Limits lim;
  lim.nodes = 20000;
  SearchResult r = s.search(p, lim, stop);
  CHECK(r.nodes <= 20000 + 4096);
  CHECK(!r.best_move.is_null());
}

TEST(Search, HardTimeLimitIsRespected) {
  Position p;
  CHECK(p.set_fen("r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1"));
  Searcher s(4);
  std::atomic<bool> stop{false};
  Limits lim;
  lim.hard_ms = 150;
  auto t0 = std::chrono::steady_clock::now();
  SearchResult r = s.search(p, lim, stop);
  auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - t0).count();
  CHECK(ms < 600);
  CHECK(!r.best_move.is_null());
}

TEST(Search, StopFlagEndsAnInfiniteSearch) {
  Position p;
  CHECK(p.set_fen(Position::START_FEN));
  Searcher s(4);
  std::atomic<bool> stop{false};
  Limits lim;
  lim.infinite = true;
  SearchResult r;
  std::thread t([&] { r = s.search(p, lim, stop); });
  std::this_thread::sleep_for(std::chrono::milliseconds(100));
  stop = true;
  t.join();
  CHECK(!r.best_move.is_null());
  CHECK(r.depth >= 1);
}

TEST(Search, InfoCallbackReportsIncreasingDepths) {
  Position p;
  CHECK(p.set_fen(Position::START_FEN));
  Searcher s(4);
  std::atomic<bool> stop{false};
  Limits lim;
  lim.depth = 5;
  int last = 0;
  bool increasing = true;
  int calls = 0;
  s.search(p, lim, stop, [&](const SearchInfo& i) {
    increasing &= i.depth == last + 1;
    last = i.depth;
    ++calls;
  });
  CHECK(increasing);
  CHECK_EQ(calls, 5);
}

TEST(Search, DeeperSearchNeverLosesMaterialOnATacticalPosition) {
  // Black threatens ...Qxg2#; a depth-4 search must see the threat and defend or counter.
  Position p;
  const char* fen = "r1bqk2r/pppp1ppp/2n2n2/2b1p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 6 5";
  SearchResult r = run(fen, 5);
  CHECK(!r.best_move.is_null());
  CHECK(r.score > -150);
}

TEST(Search, TranspositionTableGivesSameScoreAsSmallTable) {
  const char* fen = "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1";
  SearchResult small_tt = run(fen, 5, nullptr, 1);
  SearchResult big_tt = run(fen, 5, nullptr, 64);
  // Scores may differ slightly through TT collisions, but a sane search agrees on the big picture.
  CHECK(std::abs(small_tt.score - big_tt.score) < 100);
}

// ---- MultiPV ---------------------------------------------------------------------------------------------------

static SearchResult run_multipv(const char* fen, int depth, int lines) {
  Position p;
  CHECK(p.set_fen(fen));
  Searcher s(4);
  std::atomic<bool> stop{false};
  Limits lim;
  lim.depth = depth;
  lim.multipv = lines;
  return s.search(p, lim, stop);
}

TEST(MultiPv, ReturnsDistinctLegalMovesWithNonIncreasingScores) {
  const char* fens[] = {Position::START_FEN, "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1"};
  for (const char* f : fens) {
    Position p;
    CHECK(p.set_fen(f));
    SearchResult r = run_multipv(f, 5, 5);
    CHECK_EQ(int(r.lines.size()), 5);
    MoveList legal;
    generate_legal(p, legal);
    for (size_t i = 0; i < r.lines.size(); ++i) {
      bool ok = false;
      for (Move m : legal) ok |= (m == r.lines[i].move);
      CHECK(ok);
      CHECK(!r.lines[i].pv.empty() && r.lines[i].pv[0] == r.lines[i].move);
      CHECK_EQ(r.lines[i].depth, 5);
      for (size_t j = 0; j < i; ++j) CHECK(r.lines[i].move != r.lines[j].move);
      if (i) CHECK(r.lines[i].score <= r.lines[i - 1].score);
    }
    CHECK(r.best_move == r.lines[0].move && r.score == r.lines[0].score && r.pv == r.lines[0].pv);
  }
}

TEST(MultiPv, FirstLineAgreesWithASingleLineSearchOnTactics) {
  const char* fens[] = {"6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1",           // mate in one
                        "4k3/8/8/3q4/8/8/8/3RK3 w - - 0 1",                // a free queen
                        "r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4"};
  for (const char* f : fens) {
    SearchResult one = run_multipv(f, 6, 1), many = run_multipv(f, 6, 4);
    CHECK_EQ(int(one.lines.size()), 1);
    CHECK(one.best_move == many.best_move);
    CHECK(std::abs(one.score - many.score) <= 30);
  }
}

TEST(MultiPv, NeverReportsMoreLinesThanThereAreLegalMoves) {
  SearchResult r = run_multipv("7k/8/8/8/8/8/q7/K7 w - - 0 1", 4, 10);  // only Kxa2 is legal
  CHECK_EQ(int(r.lines.size()), 1);
  SearchResult two = run_multipv("7k/8/8/8/8/8/5q2/6K1 w - - 0 1", 4, 10);  // Kxf2 and Kh1
  CHECK_EQ(int(two.lines.size()), 2);
}

TEST(MultiPv, NoLinesForMateOrStalemate) {
  CHECK(run_multipv("7k/6Q1/6K1/8/8/8/8/8 b - - 0 1", 3, 3).lines.empty());
  CHECK(run_multipv("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1", 3, 3).lines.empty());
}

TEST(MultiPv, TheWorstMoveScoresFarBelowTheBest) {
  // White can win a queen with Rxd5; any move that leaves it en prise scores much lower.
  SearchResult r = run_multipv("4k3/8/8/3q4/8/8/8/3RK3 w - - 0 1", 5, 8);
  CHECK_EQ(move_to_uci(r.lines[0].move), std::string("d1d5"));
  CHECK(r.lines[0].score - r.lines.back().score > 300);
}

TEST(MultiPv, MateScoresAreReportedPerLine) {
  // Two different mates in one: both must show the same mate score, and other moves must score lower.
  SearchResult r = run_multipv("6k1/8/6K1/8/8/8/8/R7 w - - 0 1", 4, 6);
  CHECK_EQ(r.lines[0].score, MATE - 1);
  CHECK(r.lines[1].score < r.lines[0].score);
}

TEST(MultiPv, StopFlagKeepsTheLastCompleteIteration) {
  Position p;
  CHECK(p.set_fen(Position::START_FEN));
  Searcher s(4);
  std::atomic<bool> stop{false};
  Limits lim;
  lim.infinite = true;
  lim.multipv = 3;
  SearchResult r;
  std::thread t([&] { r = s.search(p, lim, stop); });
  std::this_thread::sleep_for(std::chrono::milliseconds(150));
  stop = true;
  t.join();
  CHECK_EQ(int(r.lines.size()), 3);
  CHECK(r.lines[0].depth == r.lines[2].depth && r.lines[0].depth >= 1);  // all lines come from one finished depth
}

TEST(MultiPv, InfoCallbackReportsEachLineOncePerDepth) {
  Position p;
  CHECK(p.set_fen(Position::START_FEN));
  Searcher s(4);
  std::atomic<bool> stop{false};
  Limits lim;
  lim.depth = 4;
  lim.multipv = 3;
  std::vector<std::pair<int, int>> seen;
  s.search(p, lim, stop, [&](const SearchInfo& i) { seen.push_back({i.depth, i.multipv}); });
  CHECK_EQ(int(seen.size()), 12);
  for (size_t k = 0; k < seen.size(); ++k) {
    CHECK_EQ(seen[k].first, int(k / 3) + 1);
    CHECK_EQ(seen[k].second, int(k % 3) + 1);
  }
}

TEST(MultiPv, LinesAreSortedBestFirstEvenWhenSearchNoiseDisagreesWithTheOrderTheyWereFound) {
  // A noisy middlegame position where a quiet move (Qf4) found in a later line beats the first line at depth 5.
  SearchResult r = run_multipv("rn1qk1nr/pp2pp1p/3p4/2P2p2/2b4b/P3Q3/1P1KP1PP/RNB2BNR w kq - 5 11", 5, 4);
  for (size_t i = 1; i < r.lines.size(); ++i) CHECK(r.lines[i].score <= r.lines[i - 1].score);
  CHECK(r.best_move == r.lines[0].move && r.score == r.lines[0].score);
}
