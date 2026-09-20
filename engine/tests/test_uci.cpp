#include <sstream>

#include "test_framework.h"
#include "../src/movegen/movegen.h"
#include "../src/uci/uci.h"

using namespace chess;

static std::string session(const std::string& script) {
  std::istringstream in(script);
  std::ostringstream out;
  Uci uci(in, out);
  uci.run();
  return out.str();
}
static bool contains(const std::string& hay, const std::string& needle) { return hay.find(needle) != std::string::npos; }

TEST(Uci, HandshakeAndOptions) {
  std::string out = session("uci\nisready\n");
  CHECK(contains(out, "id name chessme"));
  CHECK(contains(out, "option name Hash type spin"));
  CHECK(contains(out, "uciok"));
  CHECK(contains(out, "readyok"));
}

TEST(Uci, PositionStartposWithMoves) {
  std::string out = session("position startpos moves e2e4 e7e5 g1f3\nd\n");
  CHECK(contains(out, "Fen: rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2"));
}

TEST(Uci, PositionFenWithMoves) {
  std::string out = session("position fen 4k3/8/8/8/8/8/4P3/4K3 w - - 0 1 moves e2e4\nd\n");
  CHECK(contains(out, "Fen: 4k3/8/8/8/4P3/8/8/4K3 b - e3 0 1"));
}

TEST(Uci, IllegalMoveInListStopsApplyingButKeepsEarlierMoves) {
  std::string out = session("position startpos moves e2e4 e2e4 d7d5\nd\n");
  CHECK(contains(out, "Fen: rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"));
}

TEST(Uci, MalformedFenKeepsPreviousPosition) {
  std::string out = session("position startpos\nposition fen garbage\nd\n");
  CHECK(contains(out, std::string("Fen: ") + Position::START_FEN));
}

TEST(Uci, GoDepthReportsInfoAndLegalBestmove) {
  std::string out = session("position startpos\ngo depth 4\n");
  CHECK(contains(out, "info depth 1 "));
  CHECK(contains(out, "info depth 4 "));
  size_t p = out.find("bestmove ");
  CHECK(p != std::string::npos);
  std::string mv = out.substr(p + 9, 4);
  Position pos;
  CHECK(!parse_uci_move(pos, mv).is_null());
}

TEST(Uci, MateIsReportedAsMateScore) {
  std::string out = session("position fen 6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1\ngo depth 5\n");
  CHECK(contains(out, "score mate 1"));
  CHECK(contains(out, "bestmove d1d8"));
}

TEST(Uci, NoLegalMoveGivesNullBestmove) {
  std::string out = session("position fen 7k/6Q1/6K1/8/8/8/8/8 b - - 0 1\ngo depth 3\n");
  CHECK(contains(out, "bestmove 0000"));
}

TEST(Uci, SetOptionAndUnknownCommandsAreHarmless) {
  std::string out = session("setoption name Hash value 8\nsetoption name Clear Hash\nfoobar baz\nisready\n");
  CHECK(contains(out, "readyok"));
}

TEST(Uci, UcinewgameResetsPosition) {
  std::string out = session("position startpos moves e2e4\nucinewgame\nd\n");
  CHECK(contains(out, std::string("Fen: ") + Position::START_FEN));
}

TEST(Uci, PerftCommand) {
  CHECK(contains(session("position startpos\nperft 3\n"), "nodes 8902"));
}

TEST(Uci, FormatScore) {
  CHECK_EQ(format_score(34), std::string("cp 34"));
  CHECK_EQ(format_score(-120), std::string("cp -120"));
  CHECK_EQ(format_score(MATE - 1), std::string("mate 1"));
  CHECK_EQ(format_score(MATE - 3), std::string("mate 2"));
  CHECK_EQ(format_score(-MATE + 2), std::string("mate -1"));
}

TEST(Uci, LimitsFromMovetime) {
  Uci::GoParams g;
  g.movetime = 1000;
  Limits l = Uci::make_limits(g, WHITE);
  CHECK(l.hard_ms > 900 && l.hard_ms <= 1000);
  CHECK(!l.infinite);
}

TEST(Uci, LimitsFromClockUseTheRightSideAndStayInsideTheBudget) {
  Uci::GoParams g;
  g.wtime = 60000; g.btime = 10000; g.winc = 0; g.binc = 0;
  Limits w = Uci::make_limits(g, WHITE), b = Uci::make_limits(g, BLACK);
  CHECK(w.soft_ms > b.soft_ms);
  CHECK(w.hard_ms < 60000);
  CHECK(b.hard_ms < 10000);
  CHECK(w.soft_ms <= w.hard_ms);
}

TEST(Uci, LimitsNeverExceedRemainingTimeInScramble) {
  Uci::GoParams g;
  g.wtime = 50; g.btime = 50;
  Limits l = Uci::make_limits(g, WHITE);
  CHECK(l.hard_ms >= 1 && l.hard_ms < 50);
}

TEST(Uci, BareGoSearchesUntilInputEndsThenReportsBestmove) {
  // A bare "go" is an infinite search; end-of-input acts as "stop" and must still yield a legal bestmove.
  std::string out = session("position startpos\ngo\n");
  CHECK(contains(out, "bestmove "));
}

TEST(Uci, StopCommandEndsInfiniteSearch) {
  std::string out = session("position startpos\ngo infinite\nstop\nisready\n");
  CHECK(contains(out, "bestmove "));
  CHECK(contains(out, "readyok"));
}

TEST(Uci, MultiPvOptionPrintsNumberedLines) {
  std::string out = session("setoption name MultiPV value 3\nposition startpos\ngo depth 4\n");
  CHECK(contains(out, "info depth 4 multipv 1 score"));
  CHECK(contains(out, "info depth 4 multipv 2 score"));
  CHECK(contains(out, "info depth 4 multipv 3 score"));
  CHECK(!contains(out, "multipv 4"));
  CHECK(contains(out, "bestmove "));
}

TEST(Uci, DefaultOutputHasNoMultipvField) {
  std::string out = session("position startpos\ngo depth 3\n");
  CHECK(!contains(out, "multipv"));
  CHECK(session("uci\n").find("option name MultiPV type spin default 1") != std::string::npos);
}

TEST(Uci, MultiPvBestmoveIsTheFirstLinesMove) {
  std::string out = session("setoption name MultiPV value 4\nposition fen 6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1\ngo depth 4\n");
  CHECK(contains(out, "multipv 1 score mate 1"));
  CHECK(contains(out, "bestmove d1d8"));
}
