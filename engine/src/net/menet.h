#pragma once
// Inference for the "me" network (a small residual conv net trained in Python, see chessme/model).
// The input encoding, move indexing and weight file format are specified in chessme/model/encoding.py and
// chessme/model/export.py; this code must stay in exact agreement with them (tests compare the two).
#include <string>
#include <utility>
#include <vector>

#include "../board/position.h"

namespace chess {

constexpr int ME_PLANES = 20;
constexpr int ME_POLICY = 4096 + 3 * 24;

// Policy slot of `m` for the side to move `stm` (canonical view: mirrored vertically when Black moves).
int me_move_index(Move m, Color stm);

// Fills out[20 * 64] with the canonical input planes (plane-major, square = rank * 8 + file).
void me_build_planes(const Position& pos, int mover_rating, int opp_rating, int platform, float* out);

class MeNet {
 public:
  bool load(const std::string& path, std::string* error = nullptr);
  bool loaded() const { return blocks_ > 0; }
  int blocks() const { return blocks_; }
  int channels() const { return channels_; }

  // Raw policy logits (ME_POLICY values) for the side to move.
  void logits(const Position& pos, int mover_rating, int opp_rating, int platform, std::vector<float>& out) const;

  // Probabilities over the legal moves (softmax of their logits), most probable first.
  std::vector<std::pair<Move, float>> policy(Position& pos, int mover_rating, int opp_rating, int platform) const;

 private:
  struct Conv {
    std::vector<float> w, b;
  };
  int blocks_ = 0, channels_ = 0, dim_ = 0;
  Conv stem_;
  std::vector<Conv> c1_, c2_;
  std::vector<float> qk_w_, qk_b_, bias_, under_w_, under_b_;
};

}  // namespace chess
