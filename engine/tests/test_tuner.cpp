#include <cmath>
#include <cstdio>
#include <fstream>

#include "test_framework.h"
#include "../src/eval/eval.h"
#include "../src/movegen/movegen.h"
#include "../src/tune/tuner.h"

using namespace chess;

namespace {

constexpr double LN10_400 = 2.302585092994046 / 400.0;

std::vector<std::string> random_positions(int count, uint64_t seed, int max_plies = 76) {
  std::vector<std::string> out;
  uint64_t x = seed;
  auto rnd = [&]() { x ^= x << 13; x ^= x >> 7; x ^= x << 17; return x; };
  while (int(out.size()) < count) {
    Position p;
    const int plies = 6 + int(rnd() % (max_plies - 6));
    for (int i = 0; i < plies; ++i) {
      MoveList l;
      generate_legal(p, l);
      if (l.count == 0) break;
      p.make_move(l.moves[rnd() % l.count]);
    }
    MoveList l;
    generate_legal(p, l);
    if (l.count > 0) out.push_back(p.fen());
  }
  return out;
}

// White-point-of-view evaluation under the currently installed parameters.
double white_eval(const std::string& fen) {
  Position p;
  p.set_fen(fen);
  return (p.side_to_move() == WHITE ? 1 : -1) * double(evaluate(p));
}

// Soft labels: sigmoid(k * eval_under(hidden) / 400 * ln10), so the true parameters are known exactly.
TuneData labelled(const std::vector<std::string>& fens, const EvalParams& hidden, double k) {
  set_params(hidden);
  TuneData d;
  for (const auto& f : fens) {
    const double e = white_eval(f);
    d.add(f, 1.0 / (1.0 + std::exp(-k * LN10_400 * e)));
  }
  reset_params();
  return d;
}

}  // namespace

TEST(Tuner, RejectsInvalidFens) {
  TuneData d;
  CHECK(!d.add("garbage", 1.0));
  CHECK(d.add(Position::START_FEN, 0.5));
  CHECK_EQ(int(d.size()), 1);
}

TEST(Tuner, DefaultFrozenAnchorsPawnAndKing) {
  auto f = default_frozen();
  auto has = [&](int i) { return std::find(f.begin(), f.end(), i) != f.end(); };
  CHECK(has(P::MAT_MG + PAWN - 1) && has(P::MAT_EG + PAWN - 1));
  CHECK(has(P::MAT_MG + KING - 1) && has(P::MAT_EG + KING - 1));
  CHECK(!has(P::MAT_MG + QUEEN - 1));
}

TEST(Tuner, FitsTheSigmoidScaleFromData) {
  auto fens = random_positions(1500, 42);
  TuneData d = labelled(fens, default_params(), 1.3);
  EvalParams p = default_params();
  TuneConfig cfg;
  cfg.epochs = 0;  // K fit only
  TuneReport r = tune(d, p, cfg);
  CHECK(std::fabs(r.k - 1.3) < 0.06);
  CHECK(r.loss_before_train < 1e-4);  // labels are exactly the model's own predictions
}

TEST(Tuner, ValidationSplitIsDeterministicAndRoughlyTenPercent) {
  auto fens = random_positions(2000, 7);
  TuneData d = labelled(fens, default_params(), 1.0);
  EvalParams p = default_params();
  TuneConfig cfg;
  cfg.epochs = 0;
  TuneReport a = tune(d, p, cfg), b = tune(d, p, cfg);
  CHECK_EQ(int(a.train_positions + a.val_positions), 2000);
  CHECK(a.val_positions > 120 && a.val_positions < 280);
  CHECK_EQ(int(a.val_positions), int(b.val_positions));
}

namespace {
EvalParams hidden_material_params() {
  EvalParams hidden = default_params();
  hidden[P::MAT_MG + QUEEN - 1] += 220;
  hidden[P::MAT_EG + QUEEN - 1] += 220;
  hidden[P::MAT_MG + KNIGHT - 1] -= 60;
  hidden[P::MAT_EG + KNIGHT - 1] -= 60;
  return hidden;
}
}  // namespace

TEST(Tuner, RecoversHiddenMaterialValuesWhenOnlyMaterialIsFree) {
  // With everything else frozen the problem is identifiable, so the parameters themselves must be recovered.
  const EvalParams hidden = hidden_material_params();
  // long playouts so endgame-weighted positions (few pieces) are well represented too
  TuneData d = labelled(random_positions(5000, 99, 260), hidden, 1.0);

  EvalParams p = default_params();
  TuneConfig cfg;
  cfg.epochs = 500;
  cfg.lr = 3.0;
  cfg.k = 1.0;
  cfg.l2 = 0;
  for (int i = 0; i < P::COUNT; ++i) cfg.frozen.push_back(i);
  auto thaw = [&](int idx) { cfg.frozen.erase(std::remove(cfg.frozen.begin(), cfg.frozen.end(), idx), cfg.frozen.end()); };
  for (PieceType pt : {KNIGHT, BISHOP, ROOK, QUEEN}) thaw(P::MAT_MG + pt - 1), thaw(P::MAT_EG + pt - 1);
  TuneReport r = tune(d, p, cfg);

  CHECK(r.loss_after_train < 0.05 * r.loss_before_train);
  CHECK(std::abs(p[P::MAT_MG + QUEEN - 1] - hidden[P::MAT_MG + QUEEN - 1]) <= 20);
  CHECK(std::abs(p[P::MAT_EG + QUEEN - 1] - hidden[P::MAT_EG + QUEEN - 1]) <= 20);
  CHECK(std::abs(p[P::MAT_MG + KNIGHT - 1] - hidden[P::MAT_MG + KNIGHT - 1]) <= 20);
  CHECK_EQ(p[P::MAT_MG + PAWN - 1], default_params()[P::MAT_MG + PAWN - 1]);  // untouched
}

TEST(Tuner, ReproducesTheHiddenEvaluationWhenEverythingIsFree) {
  // With all parameters free, material and piece-square values can trade off, so we check the *evaluation*
  // on unseen positions rather than individual parameters.
  const EvalParams hidden = hidden_material_params();
  TuneData d = labelled(random_positions(6000, 123), hidden, 1.0);

  EvalParams p = default_params();
  TuneConfig cfg;
  cfg.epochs = 400;
  cfg.lr = 3.0;
  cfg.k = 1.0;
  cfg.l2 = 0;
  cfg.frozen = default_frozen();
  TuneReport r = tune(d, p, cfg);
  CHECK(r.loss_after_train < 0.3 * r.loss_before_train);
  CHECK(r.loss_after_val < 0.3 * r.loss_before_val);

  auto mean_abs_error = [&](const EvalParams& candidate, const std::vector<std::string>& fens) {
    double total = 0;
    for (const auto& f : fens) {
      set_params(hidden);
      const double truth = white_eval(f);
      set_params(candidate);
      total += std::fabs(white_eval(f) - truth);
    }
    reset_params();
    return total / fens.size();
  };
  const auto unseen = random_positions(800, 777);  // positions the tuner never saw
  CHECK(mean_abs_error(p, unseen) < 0.4 * mean_abs_error(default_params(), unseen));
}

TEST(Tuner, FrozenParametersDoNotMove) {
  auto fens = random_positions(1500, 5);
  EvalParams hidden = default_params();
  hidden[P::MAT_MG + QUEEN - 1] += 300;
  hidden[P::MAT_EG + QUEEN - 1] += 300;
  TuneData d = labelled(fens, hidden, 1.0);
  EvalParams p = default_params();
  TuneConfig cfg;
  cfg.epochs = 60;
  cfg.k = 1.0;
  cfg.frozen = default_frozen();
  cfg.frozen.push_back(P::MAT_MG + QUEEN - 1);
  cfg.frozen.push_back(P::MAT_EG + QUEEN - 1);
  tune(d, p, cfg);
  CHECK_EQ(p[P::MAT_MG + QUEEN - 1], default_params()[P::MAT_MG + QUEEN - 1]);
  CHECK_EQ(p[P::MAT_EG + QUEEN - 1], default_params()[P::MAT_EG + QUEEN - 1]);
}

TEST(Tuner, HeavyRegularisationKeepsParametersNearTheStart) {
  auto fens = random_positions(1500, 11);
  EvalParams hidden = default_params();
  hidden[P::MAT_MG + ROOK - 1] += 250;
  hidden[P::MAT_EG + ROOK - 1] += 250;
  TuneData d = labelled(fens, hidden, 1.0);
  EvalParams p = default_params();
  TuneConfig cfg;
  cfg.epochs = 100;
  cfg.k = 1.0;
  cfg.l2 = 1.0;  // enormous pull towards the start
  cfg.frozen = default_frozen();
  tune(d, p, cfg);
  int max_delta = 0;
  for (int i = 0; i < P::COUNT; ++i) max_delta = std::max(max_delta, std::abs(p[i] - default_params()[i]));
  CHECK(max_delta <= 3);
}

TEST(Tuner, TunedParametersImproveHeldOutPrediction) {
  // Fit on one set of positions, then check the loss on a different, unseen set of positions.
  EvalParams hidden = default_params();
  hidden[P::MAT_MG + BISHOP - 1] += 80;
  hidden[P::MAT_EG + BISHOP - 1] += 80;
  hidden[P::ROOK_OPEN_MG] += 30;
  TuneData train = labelled(random_positions(4000, 1), hidden, 1.0);
  TuneData unseen = labelled(random_positions(1500, 2), hidden, 1.0);

  EvalParams p = default_params();
  TuneConfig cfg;
  cfg.epochs = 300;
  cfg.lr = 2.0;
  cfg.k = 1.0;
  cfg.frozen = default_frozen();
  tune(train, p, cfg);

  TuneConfig probe;
  probe.epochs = 0;
  probe.k = 1.0;
  probe.val_fraction = 0.0;
  EvalParams before = default_params(), after = p;
  TuneReport rb = tune(unseen, before, probe), ra = tune(unseen, after, probe);
  CHECK(ra.loss_before_train < rb.loss_before_train);
}

TEST(Tuner, LoadPositionsParsesFilesAndSkipsBadLines) {
  const char* path = "/tmp/chessme_tuner_positions.txt";
  {
    std::ofstream f(path);
    f << "# header comment\n"
      << Position::START_FEN << " | 0.5\n"
      << "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1 | 1.0 | 2.5\n"
      << "not a fen | 1\n"
      << Position::START_FEN << " | 7\n"        // result out of range
      << Position::START_FEN << " | abc\n"      // unparsable
      << Position::START_FEN << " | 0.0 | -1\n" // bad weight
      << "\n";
  }
  TuneData d;
  CHECK_EQ(int(load_positions(path, d)), 2);
  CHECK_EQ(int(d.size()), 2);
  TuneData limited;
  CHECK_EQ(int(load_positions(path, limited, 1)), 1);
  std::string err;
  TuneData none;
  CHECK_EQ(int(load_positions("/no/such/file", none, 0, &err)), 0);
  CHECK(!err.empty());
  std::remove(path);
}
