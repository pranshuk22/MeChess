#pragma once
// Evaluation parameters as one flat vector of ints (centipawns), so they can be tuned, saved, loaded
// and swapped at runtime without recompiling. Layout offsets are in namespace chess::P.
#include <array>
#include <string>
#include <utility>
#include <vector>

#include "../board/position.h"

namespace chess {
namespace P {
// Piece-indexed arrays use (piece type - 1): pawn=0 ... king=5.
constexpr int MAT_MG = 0;
constexpr int MAT_EG = MAT_MG + 6;
constexpr int PST_MG = MAT_EG + 6;            // 6 * 64, indexed [(pt-1)*64 + square from own side's view]
constexpr int PST_EG = PST_MG + 6 * 64;
constexpr int BISHOP_PAIR_MG = PST_EG + 6 * 64;
constexpr int BISHOP_PAIR_EG = BISHOP_PAIR_MG + 1;
constexpr int TEMPO = BISHOP_PAIR_EG + 1;      // single value (side to move), not phase-blended
constexpr int PASSED_MG = TEMPO + 1;           // by relative rank 0..7 (0 and 7 unused)
constexpr int PASSED_EG = PASSED_MG + 8;
constexpr int DOUBLED_MG = PASSED_EG + 8;      // per extra pawn on a file
constexpr int DOUBLED_EG = DOUBLED_MG + 1;
constexpr int ISOLATED_MG = DOUBLED_EG + 1;    // per isolated pawn
constexpr int ISOLATED_EG = ISOLATED_MG + 1;
constexpr int ROOK_OPEN_MG = ISOLATED_EG + 1;  // rook on a file with no pawns
constexpr int ROOK_OPEN_EG = ROOK_OPEN_MG + 1;
constexpr int ROOK_SEMI_MG = ROOK_OPEN_EG + 1; // rook on a file with only enemy pawns
constexpr int ROOK_SEMI_EG = ROOK_SEMI_MG + 1;
constexpr int MOB_MG = ROOK_SEMI_EG + 1;       // per safe square, by piece (pt-1); only N,B,R,Q used
constexpr int MOB_EG = MOB_MG + 6;
constexpr int COUNT = MOB_EG + 6;
}  // namespace P

using EvalParams = std::array<int, P::COUNT>;

struct ParamGroup {
  const char* name;
  int offset;
  int count;
};
const std::vector<ParamGroup>& param_groups();

const EvalParams& default_params();  // compiled-in defaults
const EvalParams& current_params();  // what evaluate() uses right now
void set_params(const EvalParams& p);  // not thread-safe: call only while no search is running
void reset_params();

// Text format: one line per group, "name v0 v1 ...". Starts from the defaults, so a file may list only some
// groups. Returns false (and fills *error) on unknown group names, wrong value counts or unreadable files.
bool load_params(const std::string& path, EvalParams& out, std::string* error = nullptr);
bool save_params(const std::string& path, const EvalParams& p);
bool parse_params(const std::string& text, EvalParams& out, std::string* error = nullptr);
std::string format_params(const EvalParams& p);

// Linear feature trace of one position, for tuning. evaluate(pos) equals
//   sign * (sum_mg * phase + sum_eg * (24 - phase)) / 24 + tempo_sign * params[TEMPO]
// where sum_mg / sum_eg are dot products of `mg` / `eg` (index, count) lists with the parameters.
struct EvalTrace {
  std::vector<std::pair<int, int>> mg, eg;  // (parameter index, signed count from White's point of view)
  int phase = 0;                            // 0..24
  int stm_sign = 1;                         // +1 White to move, -1 Black
};
void trace_eval(const Position& pos, EvalTrace& out);

constexpr int TOTAL_PHASE = 24;

}  // namespace chess
