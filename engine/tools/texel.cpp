// texel: fit evaluation parameters to game results.
//   texel --data positions.txt --out tuned.txt [--params-in start.txt] [--epochs 300] [--lr 1.0]
//         [--l2 1e-8] [--val 0.1] [--max-positions N] [--k 0] [--freeze group1,group2] [--verbose]
// positions.txt: one "FEN | result [| weight]" per line; result = White's score (1, 0.5, 0).
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <sstream>
#include <string>

#include "../src/board/bitboard.h"
#include "../src/tune/tuner.h"

using namespace chess;

int main(int argc, char** argv) {
  init_bitboards();
  std::string data_path, out_path, in_path, freeze;
  size_t max_positions = 0;
  TuneConfig cfg;
  cfg.l2 = 1e-8;
  for (int i = 1; i < argc; ++i) {
    auto next = [&]() -> const char* { return i + 1 < argc ? argv[++i] : ""; };
    if (!std::strcmp(argv[i], "--data")) data_path = next();
    else if (!std::strcmp(argv[i], "--out")) out_path = next();
    else if (!std::strcmp(argv[i], "--params-in")) in_path = next();
    else if (!std::strcmp(argv[i], "--epochs")) cfg.epochs = std::atoi(next());
    else if (!std::strcmp(argv[i], "--lr")) cfg.lr = std::atof(next());
    else if (!std::strcmp(argv[i], "--l2")) cfg.l2 = std::atof(next());
    else if (!std::strcmp(argv[i], "--val")) cfg.val_fraction = std::atof(next());
    else if (!std::strcmp(argv[i], "--k")) cfg.k = std::atof(next());
    else if (!std::strcmp(argv[i], "--max-positions")) max_positions = size_t(std::atoll(next()));
    else if (!std::strcmp(argv[i], "--freeze")) freeze = next();
    else if (!std::strcmp(argv[i], "--verbose")) cfg.verbose = true;
    else { std::fprintf(stderr, "unknown argument: %s\n", argv[i]); return 2; }
  }
  if (data_path.empty() || out_path.empty()) {
    std::fprintf(stderr, "usage: texel --data positions.txt --out tuned.txt [options]\n");
    return 2;
  }

  EvalParams params = default_params();
  if (!in_path.empty()) {
    std::string err;
    if (!load_params(in_path, params, &err)) { std::fprintf(stderr, "%s\n", err.c_str()); return 2; }
  }
  cfg.frozen = default_frozen();
  std::stringstream fs(freeze);
  std::string g;
  while (std::getline(fs, g, ',')) {
    bool found = false;
    for (const ParamGroup& pg : param_groups())
      if (g == pg.name) {
        found = true;
        for (int j = 0; j < pg.count; ++j) cfg.frozen.push_back(pg.offset + j);
      }
    if (!found && !g.empty()) { std::fprintf(stderr, "unknown group to freeze: %s\n", g.c_str()); return 2; }
  }

  TuneData data;
  std::string err;
  size_t n = load_positions(data_path, data, max_positions, &err);
  if (n == 0) { std::fprintf(stderr, "no positions loaded (%s)\n", err.c_str()); return 2; }
  std::printf("loaded %zu positions\n", n);

  const EvalParams start = params;
  TuneReport r = tune(data, params, cfg);
  std::printf("K = %.4f   train %zu / validation %zu positions, %d epochs\n", r.k, r.train_positions, r.val_positions,
              r.epochs_run);
  std::printf("train loss %.6f -> %.6f\n", r.loss_before_train, r.loss_after_train);
  std::printf("valid loss %.6f -> %.6f  (%.2f%% lower)\n", r.loss_before_val, r.loss_after_val,
              r.loss_before_val > 0 ? 100.0 * (r.loss_before_val - r.loss_after_val) / r.loss_before_val : 0.0);
  std::printf("\nlargest changes per group (mean |delta| in cp):\n");
  for (const ParamGroup& pg : param_groups()) {
    double s = 0;
    for (int j = 0; j < pg.count; ++j) s += std::abs(params[pg.offset + j] - start[pg.offset + j]);
    std::printf("  %-16s %6.1f\n", pg.name, s / pg.count);
  }
  if (!save_params(out_path, params)) { std::fprintf(stderr, "cannot write %s\n", out_path.c_str()); return 2; }
  std::printf("\nwrote %s\n", out_path.c_str());
  return 0;
}
