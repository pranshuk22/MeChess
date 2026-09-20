// perft: counts leaf nodes of the legal-move tree. Ground truth for move generation.
//
//   perft [--fen "<fen>"] [--divide] [--verify] <depth>
//   perft --suite [--deep] [--verify]     run the standard published suites, exit 1 on any mismatch
#include <chrono>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

#include "../src/board/position.h"
#include "../src/movegen/movegen.h"

using namespace chess;

static bool g_verify = false;
static bool g_verify_failed = false;

static uint64_t perft(Position& pos, int depth) {
  if (depth == 0) return 1;
  MoveList list;
  generate_pseudo_legal(pos, list);
  uint64_t nodes = 0;
  for (Move m : list) {
    uint64_t before = pos.key();
    std::string fen_before = g_verify ? pos.fen() : "";
    pos.make_move(m);
    if (g_verify && pos.key() != pos.compute_key()) {
      std::printf("KEY MISMATCH after %s from %s\n", move_to_uci(m).c_str(), fen_before.c_str());
      g_verify_failed = true;
    }
    if (mover_is_safe(pos)) nodes += depth == 1 ? 1 : perft(pos, depth - 1);
    pos.unmake_move(m);
    if (g_verify && (pos.key() != before || pos.fen() != fen_before)) {
      std::printf("UNMAKE MISMATCH for %s at %s\n", move_to_uci(m).c_str(), fen_before.c_str());
      g_verify_failed = true;
    }
  }
  return nodes;
}

struct Case {
  const char* name;
  const char* fen;
  std::vector<uint64_t> counts;       // index i = depth i+1
  std::vector<uint64_t> deep_counts;  // continues after `counts`
};

static const std::vector<Case> SUITE = {
    {"startpos", Position::START_FEN, {20, 400, 8902, 197281, 4865609}, {119060324}},
    {"kiwipete", "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1", {48, 2039, 97862, 4085603},
     {193690690}},
    {"position3", "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1", {14, 191, 2812, 43238, 674624, 11030083}, {}},
    {"position4", "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1", {6, 264, 9467, 422333, 15833292}, {}},
    {"position4-mirrored", "r2q1rk1/pP1p2pp/Q4n2/bbp1p3/Np6/1B3NBn/pPPP1PPP/R3K2R b KQ - 0 1",
     {6, 264, 9467, 422333, 15833292}, {}},
    {"position5", "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8", {44, 1486, 62379, 2103487}, {89941194}},
    {"position6", "r4rk1/1pp1qppp/p1np1n2/2b1p1B1/2B1P1b1/P1NP1N2/1PP1QPPP/R4RK1 w - - 0 10",
     {46, 2079, 89890, 3894594}, {164075551}},
};

static double now() {
  return std::chrono::duration<double>(std::chrono::steady_clock::now().time_since_epoch()).count();
}

static int run_suite(bool deep) {
  int failures = 0;
  uint64_t total_nodes = 0;
  double total_time = 0;
  for (const Case& c : SUITE) {
    Position pos;
    if (!pos.set_fen(c.fen)) {
      std::printf("%s: BAD FEN\n", c.name);
      return 1;
    }
    std::vector<uint64_t> expected = c.counts;
    if (deep) expected.insert(expected.end(), c.deep_counts.begin(), c.deep_counts.end());
    for (size_t d = 0; d < expected.size(); ++d) {
      double t0 = now();
      uint64_t got = perft(pos, int(d) + 1);
      double dt = now() - t0;
      total_nodes += got;
      total_time += dt;
      bool ok = got == expected[d];
      if (!ok) ++failures;
      std::printf("%-20s depth %zu  %12llu  %s%s  (%.2fs)\n", c.name, d + 1, (unsigned long long)got,
                  ok ? "ok" : "FAIL expected ", ok ? "" : std::to_string(expected[d]).c_str(), dt);
    }
  }
  std::printf("\n%llu nodes in %.2fs = %.1f Mnps\n", (unsigned long long)total_nodes, total_time,
              total_time > 0 ? total_nodes / total_time / 1e6 : 0.0);
  if (g_verify_failed) ++failures;
  std::printf(failures ? "FAILED (%d)\n" : "ALL PASSED\n", failures);
  return failures ? 1 : 0;
}

int main(int argc, char** argv) {
  init_bitboards();
  std::string fen = Position::START_FEN;
  bool divide = false, suite = false, deep = false;
  int depth = -1;
  for (int i = 1; i < argc; ++i) {
    if (!std::strcmp(argv[i], "--fen") && i + 1 < argc) fen = argv[++i];
    else if (!std::strcmp(argv[i], "--divide")) divide = true;
    else if (!std::strcmp(argv[i], "--suite")) suite = true;
    else if (!std::strcmp(argv[i], "--deep")) deep = true;
    else if (!std::strcmp(argv[i], "--verify")) g_verify = true;
    else depth = std::atoi(argv[i]);
  }
  if (suite) return run_suite(deep);
  if (depth < 1) {
    std::fprintf(stderr, "usage: perft [--fen FEN] [--divide] [--verify] <depth> | --suite [--deep] [--verify]\n");
    return 2;
  }
  Position pos;
  if (!pos.set_fen(fen)) {
    std::fprintf(stderr, "invalid FEN: %s\n", fen.c_str());
    return 2;
  }
  double t0 = now();
  uint64_t total = 0;
  if (divide) {
    MoveList legal;
    generate_legal(pos, legal);
    for (Move m : legal) {
      pos.make_move(m);
      uint64_t n = perft(pos, depth - 1);
      pos.unmake_move(m);
      std::printf("%s: %llu\n", move_to_uci(m).c_str(), (unsigned long long)n);
      total += n;
    }
  } else {
    total = perft(pos, depth);
  }
  double dt = now() - t0;
  std::printf("\nNodes: %llu  (%.2fs, %.1f Mnps)\n", (unsigned long long)total, dt, dt > 0 ? total / dt / 1e6 : 0.0);
  return g_verify_failed ? 1 : 0;
}
