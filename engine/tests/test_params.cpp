#include <cmath>
#include <cstdio>
#include <fstream>
#include <sstream>

#include "test_framework.h"
#include "../src/eval/eval.h"
#include "../src/movegen/movegen.h"

using namespace chess;

namespace {
Position from(const char* fen) {
  Position p;
  CHECK(p.set_fen(fen));
  return p;
}
int trace_dot(const Position& pos, const EvalParams& params) {
  EvalTrace t;
  trace_eval(pos, t);
  double mg = 0, eg = 0;
  for (auto [i, c] : t.mg) mg += double(params[i]) * c;
  for (auto [i, c] : t.eg) eg += double(params[i]) * c;
  double white_pov = (mg * t.phase + eg * (TOTAL_PHASE - t.phase)) / TOTAL_PHASE;
  return int(std::lround(t.stm_sign * white_pov + params[P::TEMPO]));
}
}  // namespace

TEST(Params, LayoutCoversEveryParameterExactlyOnce) {
  std::vector<int> seen(P::COUNT, 0);
  for (const ParamGroup& g : param_groups())
    for (int i = 0; i < g.count; ++i) ++seen[g.offset + i];
  for (int i = 0; i < P::COUNT; ++i) CHECK_EQ(seen[i], 1);
}

TEST(Params, FormatParseRoundTrip) {
  EvalParams p = default_params();
  p[P::TEMPO] = 17;
  p[P::PST_MG + 100] = -33;
  EvalParams q;
  std::string err;
  CHECK(parse_params(format_params(p), q, &err));
  CHECK(p == q);
}

TEST(Params, PartialFilesKeepDefaultsForOtherGroups) {
  EvalParams q;
  CHECK(parse_params("tempo 25\n# comment\n\nbishop_pair_mg 41\n", q));
  CHECK_EQ(q[P::TEMPO], 25);
  CHECK_EQ(q[P::BISHOP_PAIR_MG], 41);
  CHECK_EQ(q[P::MAT_MG + 1], default_params()[P::MAT_MG + 1]);
}

TEST(Params, RejectsBadInput) {
  EvalParams q;
  std::string err;
  CHECK(!parse_params("nonsense 1 2 3\n", q, &err));
  CHECK(err.find("unknown") != std::string::npos);
  CHECK(!parse_params("mat_mg 1 2 3\n", q, &err));  // wrong count
  CHECK(!parse_params("tempo abc\n", q, &err));
  CHECK(!load_params("/definitely/not/a/file.txt", q, &err));
}

TEST(Params, SaveLoadFile) {
  const char* path = "/tmp/chessme_params_test.txt";
  EvalParams p = default_params();
  p[P::ROOK_OPEN_MG] = 77;
  CHECK(save_params(path, p));
  EvalParams q;
  CHECK(load_params(path, q));
  CHECK(p == q);
  std::remove(path);
}

TEST(Params, SetParamsChangesEvaluationAndResetRestoresIt) {
  Position pos = from("4k3/8/8/8/8/8/4P3/4K3 w - - 0 1");
  const int before = evaluate(pos);
  EvalParams p = default_params();
  p[P::MAT_MG] += 50;
  p[P::MAT_EG] += 50;
  set_params(p);
  CHECK(evaluate(pos) > before);
  reset_params();
  CHECK_EQ(evaluate(pos), before);
}

TEST(Params, TraceReproducesEvaluateOnManyPositions) {
  // The tuner works on traces, so the trace must agree with the real evaluation everywhere.
  const char* fens[] = {
      Position::START_FEN,
      "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
      "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1",
      "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1",
      "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8",
      "8/8/8/4k3/8/8/4P3/4K3 b - - 0 1",
  };
  for (const char* f : fens) {
    Position p = from(f);
    // also visit descendants so we cover many structures, both colours to move
    MoveList l;
    generate_legal(p, l);
    CHECK(std::abs(trace_dot(p, default_params()) - evaluate(p)) <= 1);
    for (Move m : l) {
      p.make_move(m);
      CHECK(std::abs(trace_dot(p, default_params()) - evaluate(p)) <= 1);
      p.unmake_move(m);
    }
  }
}

TEST(Params, TraceAgreesForRandomizedParameters) {
  EvalParams p = default_params();
  uint64_t x = 1234567;
  for (int& v : p) {
    x ^= x << 13; x ^= x >> 7; x ^= x << 17;
    v += int(x % 41) - 20;
  }
  Position pos = from("r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1");
  set_params(p);
  CHECK(std::abs(trace_dot(pos, p) - evaluate(pos)) <= 1);
  reset_params();
}

// ---- individual evaluation terms -------------------------------------------------------------------------
// Terms are checked through the feature trace: it says exactly which terms fired, independent of PST noise.

namespace {
// Signed count (White's point of view) of the middlegame feature at `index` (or in [index, index+width)).
int feature(const char* fen, int index, int width = 1) {
  EvalTrace t;
  trace_eval(from(fen), t);
  int n = 0;
  for (auto [i, c] : t.mg)
    if (i >= index && i < index + width) n += c;
  return n;
}
}  // namespace

TEST(EvalTerms, PassedPawnDetection) {
  CHECK_EQ(feature("4k3/8/8/4P3/8/8/8/4K3 w - - 0 1", P::PASSED_MG, 8), 1);   // nothing can stop it
  CHECK_EQ(feature("4k3/3p4/8/4P3/8/8/8/4K3 w - - 0 1", P::PASSED_MG, 8), 0); // d7 pawn guards e6: not passed
  CHECK_EQ(feature("4k3/4p3/8/4P3/8/8/8/4K3 w - - 0 1", P::PASSED_MG, 8), 0); // blocked on the same file
  CHECK_EQ(feature("4k3/8/8/8/3p4/8/4P3/4K3 w - - 0 1", P::PASSED_MG, 8), 0); // d4 pawn is *ahead* on an adjacent file
  CHECK_EQ(feature("4k3/8/8/8/8/3p4/4P3/4K3 w - - 0 1", P::PASSED_MG, 8), 0); // d3 and e2 block each other: neither is passed
}

TEST(EvalTerms, PassedPawnIsPerColourAndUsesRelativeRank) {
  // Black pawn on e3 is on its own 6th rank (relative index 5) and passed.
  EvalTrace t;
  trace_eval(from("4k3/8/8/8/8/4p3/8/4K3 w - - 0 1"), t);
  int idx = -1, sign = 0;
  for (auto [i, c] : t.mg)
    if (i >= P::PASSED_MG && i < P::PASSED_MG + 8) idx = i - P::PASSED_MG, sign = c;
  CHECK_EQ(idx, 5);
  CHECK_EQ(sign, -1);
}

TEST(EvalTerms, PassedPawnBonusGrowsWithRank) {
  const int r3 = evaluate(from("4k3/8/8/8/8/4P3/8/4K3 w - - 0 1"));
  const int r6 = evaluate(from("4k3/8/4P3/8/8/8/8/4K3 w - - 0 1"));
  CHECK(r6 > r3);
}

TEST(EvalTerms, DoubledPawnsAreCounted) {
  CHECK_EQ(feature("4k3/8/8/8/4P3/4P3/8/4K3 w - - 0 1", P::DOUBLED_MG), 1);
  CHECK_EQ(feature("4k3/8/8/4P3/4P3/4P3/8/4K3 w - - 0 1", P::DOUBLED_MG), 2);  // tripled = two extra
  CHECK_EQ(feature("4k3/8/8/8/4P3/3P4/8/4K3 w - - 0 1", P::DOUBLED_MG), 0);
  CHECK_EQ(feature("4k3/4p3/4p3/8/8/8/8/4K3 w - - 0 1", P::DOUBLED_MG), -1);  // black doubled pawns count against black
}

TEST(EvalTerms, IsolatedPawns) {
  CHECK_EQ(feature("4k3/8/8/8/8/8/P6P/4K3 w - - 0 1", P::ISOLATED_MG), 2);   // a2 and h2 have no neighbours
  CHECK_EQ(feature("4k3/8/8/8/8/8/PP6/4K3 w - - 0 1", P::ISOLATED_MG), 0);   // a2-b2 support each other
  CHECK_EQ(feature("4k3/8/8/8/8/8/P3P3/4K3 w - - 0 1", P::ISOLATED_MG), 2);  // gap of two files
}

TEST(EvalTerms, RookOpenAndSemiOpenFiles) {
  // d-file: no pawns at all -> open
  CHECK_EQ(feature("4k3/8/8/8/8/8/PPP2PPP/3RK3 w - - 0 1", P::ROOK_OPEN_MG), 1);
  CHECK_EQ(feature("4k3/8/8/8/8/8/PPP2PPP/3RK3 w - - 0 1", P::ROOK_SEMI_MG), 0);
  // own pawn on the file -> neither
  CHECK_EQ(feature("4k3/8/8/8/8/8/PPPP1PPP/3RK3 w - - 0 1", P::ROOK_OPEN_MG), 0);
  CHECK_EQ(feature("4k3/8/8/8/8/8/PPPP1PPP/3RK3 w - - 0 1", P::ROOK_SEMI_MG), 0);
  // only an enemy pawn on the file -> semi-open
  CHECK_EQ(feature("4k3/3p4/8/8/8/8/PPP2PPP/3RK3 w - - 0 1", P::ROOK_SEMI_MG), 1);
  CHECK_EQ(feature("4k3/3p4/8/8/8/8/PPP2PPP/3RK3 w - - 0 1", P::ROOK_OPEN_MG), 0);
}

TEST(EvalTerms, MobilityRewardsActivePieces) {
  const int active = evaluate(from("4k3/8/8/8/3B4/8/8/4K3 w - - 0 1"));  // central bishop
  const int passive = evaluate(from("4k3/8/8/8/8/8/8/B3K3 w - - 0 1"));  // corner bishop
  CHECK(active > passive);
}

TEST(EvalTerms, SquaresAttackedByEnemyPawnsDoNotCountAsMobility) {
  const int free_n = feature("4k3/8/8/8/3N4/8/8/4K3 w - - 0 1", P::MOB_MG + KNIGHT - 1);
  const int hemmed = feature("4k3/8/2p1p3/1p3p2/3N4/8/8/4K3 w - - 0 1", P::MOB_MG + KNIGHT - 1);
  CHECK_EQ(free_n, 8);
  CHECK(hemmed < free_n);
}

TEST(EvalTerms, BishopPairCounted) {
  CHECK_EQ(feature("4k3/8/8/8/8/8/8/2B1KB2 w - - 0 1", P::BISHOP_PAIR_MG), 1);
  CHECK_EQ(feature("4k3/8/8/8/8/8/8/2B1KN2 w - - 0 1", P::BISHOP_PAIR_MG), 0);
  CHECK_EQ(feature("2b1kb2/8/8/8/8/8/8/4K3 w - - 0 1", P::BISHOP_PAIR_MG), -1);
}
