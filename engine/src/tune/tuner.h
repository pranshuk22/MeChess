#pragma once
// Texel-style tuner: fits evaluation parameters so that sigmoid(eval) predicts game results.
// The evaluation is linear in its parameters, so each position is reduced once to a sparse feature vector
// and then fitted with Adam. Loss: mean over positions of weight * (result - sigmoid(K * eval / 400 * ln10))^2.
#include <cstdint>
#include <string>
#include <vector>

#include "../eval/params.h"

namespace chess {

struct TuneConfig {
  int epochs = 300;
  double lr = 1.0;             // Adam step size, in centipawns
  double l2 = 0.0;             // pull towards the starting parameters (per squared cp, relative to the loss scale)
  double val_fraction = 0.1;   // held-out share used for early stopping
  int patience = 12;           // stop after this many validation checks without improvement
  double k = 0.0;              // sigmoid scale; 0 = fit it from the data with the starting parameters
  std::vector<int> frozen;     // parameter indices that must not move
  bool verbose = false;
};

struct TuneReport {
  double k = 0;
  double loss_before_train = 0, loss_before_val = 0;
  double loss_after_train = 0, loss_after_val = 0;
  int epochs_run = 0;
  size_t positions = 0, train_positions = 0, val_positions = 0;
};

class TuneData {
 public:
  // Returns false if the FEN is invalid. `result` is White's score in [0,1]; soft labels are allowed.
  bool add(const std::string& fen, double result, double weight = 1.0);
  size_t size() const { return pos_.size(); }

 private:
  friend TuneReport tune(const TuneData&, EvalParams&, const TuneConfig&);
  struct Entry {
    uint16_t idx;
    float coef;
  };
  struct Pos {
    uint32_t offset;
    uint16_t count;
    float result;
    float weight;
  };
  std::vector<Entry> entries_;
  std::vector<Pos> pos_;
};

// Tunes `params` in place (starting from its current values). Returns before/after losses.
TuneReport tune(const TuneData& data, EvalParams& params, const TuneConfig& cfg);

// Parameters that should always stay fixed: king material (cancels out) and the pawn value (the scale anchor).
std::vector<int> default_frozen();

// Loads "FEN | result [| weight]" lines. Returns the number of positions added (bad lines are skipped).
size_t load_positions(const std::string& path, TuneData& data, size_t max_positions = 0, std::string* error = nullptr);

}  // namespace chess
