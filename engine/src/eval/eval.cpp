#include "eval.h"

#include <cstring>

namespace chess {

const int PIECE_VALUE[PIECE_TYPE_NB] = {0, 100, 320, 330, 500, 900, 0};

namespace {

const int PHASE_WEIGHT[PIECE_TYPE_NB] = {0, 0, 1, 1, 2, 4, 0};

struct Masks {
  Bitboard passed[COLOR_NB][64];  // squares that must be free of enemy pawns for a pawn to be passed
  Bitboard adjacent_files[8];
  Bitboard file[8];
  Masks() {
    for (int f = 0; f < 8; ++f) {
      file[f] = FILE_A << f;
      adjacent_files[f] = (f > 0 ? FILE_A << (f - 1) : 0) | (f < 7 ? FILE_A << (f + 1) : 0);
    }
    for (Square s = 0; s < 64; ++s) {
      const int f = file_of(s), r = rank_of(s);
      const Bitboard files = file[f] | adjacent_files[f];
      Bitboard ahead_w = 0, ahead_b = 0;
      for (int rr = r + 1; rr < 8; ++rr) ahead_w |= RANK_1 << (8 * rr);
      for (int rr = 0; rr < r; ++rr) ahead_b |= RANK_1 << (8 * rr);
      passed[WHITE][s] = files & ahead_w;
      passed[BLACK][s] = files & ahead_b;
    }
  }
};
const Masks M;

inline Bitboard pawn_attacks_of(Color c, Bitboard pawns) {
  if (c == WHITE) return ((pawns & ~FILE_A) << 7) | ((pawns & ~FILE_H) << 9);
  return ((pawns & ~FILE_A) >> 9) | ((pawns & ~FILE_H) >> 7);
}

// Sinks receive every evaluation term as (mg index, eg index, signed count). The same walk over the
// position feeds both the fast direct evaluation and the tuner's feature trace, so they cannot diverge.
struct DirectSink {
  const int* p;
  int mg = 0, eg = 0;
  inline void term(int img, int ieg, int count) {
    mg += p[img] * count;
    eg += p[ieg] * count;
  }
};

struct TraceSink {
  EvalTrace* t;
  inline void term(int img, int ieg, int count) {
    if (count == 0) return;
    t->mg.emplace_back(img, count);
    t->eg.emplace_back(ieg, count);
  }
};

template <class Sink>
inline int walk(const Position& pos, Sink& sink) {
  int phase = 0;
  for (Color c : {WHITE, BLACK}) {
    const int sign = c == WHITE ? 1 : -1;
    const Color them = ~c;
    const Bitboard own = pos.occupied(c);
    const Bitboard occ = pos.occupied();
    const Bitboard my_pawns = pos.pieces(c, PAWN), their_pawns = pos.pieces(them, PAWN);
    const Bitboard their_pawn_att = pawn_attacks_of(them, their_pawns);

    for (int pt = PAWN; pt <= KING; ++pt) {
      Bitboard b = pos.pieces(c, PieceType(pt));
      while (b) {
        const Square s = pop_lsb(b);
        const int rel = c == WHITE ? s ^ 56 : s;  // square index as seen from the owner's side
        sink.term(P::MAT_MG + pt - 1, P::MAT_EG + pt - 1, sign);
        sink.term(P::PST_MG + (pt - 1) * 64 + rel, P::PST_EG + (pt - 1) * 64 + rel, sign);
        phase += PHASE_WEIGHT[pt];

        if (pt >= KNIGHT && pt <= QUEEN) {
          Bitboard att = pt == KNIGHT ? KnightAttacks[s]
                       : pt == BISHOP ? bishop_attacks(s, occ)
                       : pt == ROOK   ? rook_attacks(s, occ)
                                      : queen_attacks(s, occ);
          sink.term(P::MOB_MG + pt - 1, P::MOB_EG + pt - 1, sign * popcount(att & ~own & ~their_pawn_att));
        }
        if (pt == ROOK) {
          const Bitboard f = M.file[file_of(s)];
          if (!((my_pawns | their_pawns) & f)) sink.term(P::ROOK_OPEN_MG, P::ROOK_OPEN_EG, sign);
          else if (!(my_pawns & f)) sink.term(P::ROOK_SEMI_MG, P::ROOK_SEMI_EG, sign);
        }
        if (pt == PAWN) {
          const int rank_rel = c == WHITE ? rank_of(s) : 7 - rank_of(s);
          if (!(M.passed[c][s] & their_pawns)) sink.term(P::PASSED_MG + rank_rel, P::PASSED_EG + rank_rel, sign);
          if (!(M.adjacent_files[file_of(s)] & my_pawns)) sink.term(P::ISOLATED_MG, P::ISOLATED_EG, sign);
        }
      }
    }
    if (popcount(pos.pieces(c, BISHOP)) >= 2) sink.term(P::BISHOP_PAIR_MG, P::BISHOP_PAIR_EG, sign);
    for (int f = 0; f < 8; ++f) {
      const int n = popcount(my_pawns & M.file[f]);
      if (n > 1) sink.term(P::DOUBLED_MG, P::DOUBLED_EG, sign * (n - 1));
    }
  }
  return phase > TOTAL_PHASE ? TOTAL_PHASE : phase;
}

EvalParams g_params;
bool g_params_ready = false;

EvalParams build_defaults() {
  // Piece-square tables from the "Simplified Evaluation Function" (chessprogramming.org), from White's
  // point of view with rank 8 first, so a white piece on square s reads index s ^ 56.
  static const int PST[6][64] = {
      {0,  0,  0,  0,  0,  0,  0,  0,   50, 50, 50, 50, 50, 50, 50, 50, 10, 10, 20, 30, 30, 20, 10, 10,
       5,  5,  10, 25, 25, 10, 5,  5,   0,  0,  0,  20, 20, 0,  0,  0,  5,  -5, -10, 0, 0,  -10, -5, 5,
       5,  10, 10, -20, -20, 10, 10, 5, 0,  0,  0,  0,  0,  0,  0,  0},
      {-50, -40, -30, -30, -30, -30, -40, -50, -40, -20, 0,   0,   0,   0,   -20, -40, -30, 0,   10,  15,  15,  10,
       0,   -30, -30, 5,   15,  20,  20,  15,  5,   -30, -30, 0,   15,  20,  20,  15,  0,   -30, -30, 5,   10,  15,
       15,  10,  5,   -30, -40, -20, 0,   5,   5,   0,   -20, -40, -50, -40, -30, -30, -30, -30, -40, -50},
      {-20, -10, -10, -10, -10, -10, -10, -20, -10, 0,   0,   0,   0,   0,   0,   -10, -10, 0,   5,   10,  10,  5,
       0,   -10, -10, 5,   5,   10,  10,  5,   5,   -10, -10, 0,   10,  10,  10,  10,  0,   -10, -10, 10,  10,  10,
       10,  10,  10,  -10, -10, 5,   0,   0,   0,   0,   5,   -10, -20, -10, -10, -10, -10, -10, -10, -20},
      {0,  0,  0,  0,  0,  0,  0,  0,  5,  10, 10, 10, 10, 10, 10, 5,  -5, 0,  0,  0,  0,  0,  0,  -5,
       -5, 0,  0,  0,  0,  0,  0,  -5, -5, 0,  0,  0,  0,  0,  0,  -5, -5, 0,  0,  0,  0,  0,  0,  -5,
       -5, 0,  0,  0,  0,  0,  0,  -5, 0,  0,  0,  5,  5,  0,  0,  0},
      {-20, -10, -10, -5, -5, -10, -10, -20, -10, 0,  0,  0,  0,  0,  0,  -10, -10, 0,  5,  5,  5,  5,  0,  -10,
       -5,  0,   5,   5,  5,  5,   0,   -5,  0,   0,  5,  5,  5,  5,  0,  -5,  -10, 5,  5,  5,  5,  5,  0,  -10,
       -10, 0,   5,   0,  0,  0,   0,   -10, -20, -10, -10, -5, -5, -10, -10, -20},
      {-30, -40, -40, -50, -50, -40, -40, -30, -30, -40, -40, -50, -50, -40, -40, -30, -30, -40, -40, -50, -50, -40,
       -40, -30, -30, -40, -40, -50, -50, -40, -40, -30, -20, -30, -30, -40, -40, -30, -30, -20, -10, -20, -20, -20,
       -20, -20, -20, -10, 20,  20,  0,   0,   0,   0,   20,  20,  20,  30,  10,  0,   0,   10,  30,  20},
  };
  static const int KING_EG[64] = {
      -50, -40, -30, -20, -20, -30, -40, -50, -30, -20, -10, 0,   0,   -10, -20, -30, -30, -10, 20,  30,  30,  20,
      -10, -30, -30, -10, 30,  40,  40,  30,  -10, -30, -30, -10, 30,  40,  40,  30,  -10, -30, -30, -10, 20,  30,
      30,  20,  -10, -30, -30, -30, 0,   0,   0,   0,   -30, -30, -50, -30, -30, -30, -30, -30, -30, -50};

  EvalParams p{};
  for (int pt = 0; pt < 6; ++pt) {
    p[P::MAT_MG + pt] = p[P::MAT_EG + pt] = PIECE_VALUE[pt + 1];
    for (int s = 0; s < 64; ++s) {
      p[P::PST_MG + pt * 64 + s] = PST[pt][s];
      p[P::PST_EG + pt * 64 + s] = pt == 5 ? KING_EG[s] : PST[pt][s];
    }
  }
  p[P::BISHOP_PAIR_MG] = p[P::BISHOP_PAIR_EG] = 30;
  p[P::TEMPO] = 10;
  const int passed_mg[8] = {0, 0, 5, 10, 20, 35, 60, 0}, passed_eg[8] = {0, 0, 10, 20, 40, 70, 120, 0};
  for (int r = 0; r < 8; ++r) p[P::PASSED_MG + r] = passed_mg[r], p[P::PASSED_EG + r] = passed_eg[r];
  p[P::DOUBLED_MG] = -10; p[P::DOUBLED_EG] = -20;
  p[P::ISOLATED_MG] = -10; p[P::ISOLATED_EG] = -15;
  p[P::ROOK_OPEN_MG] = 20; p[P::ROOK_OPEN_EG] = 10;
  p[P::ROOK_SEMI_MG] = 10; p[P::ROOK_SEMI_EG] = 5;
  const int mob_mg[6] = {0, 4, 4, 2, 1, 0}, mob_eg[6] = {0, 4, 4, 4, 2, 0};
  for (int i = 0; i < 6; ++i) p[P::MOB_MG + i] = mob_mg[i], p[P::MOB_EG + i] = mob_eg[i];
  return p;
}

const EvalParams DEFAULTS = build_defaults();

inline const EvalParams& params() {
  if (!g_params_ready) {
    g_params = DEFAULTS;
    g_params_ready = true;
  }
  return g_params;
}

}  // namespace

const EvalParams& default_params() { return DEFAULTS; }
const EvalParams& current_params() { return params(); }
void set_params(const EvalParams& p) {
  g_params = p;
  g_params_ready = true;
}
void reset_params() { set_params(DEFAULTS); }

int evaluate(const Position& pos) {
  const EvalParams& p = params();
  DirectSink sink{p.data()};
  const int phase = walk(pos, sink);
  const int white_pov = (sink.mg * phase + sink.eg * (TOTAL_PHASE - phase)) / TOTAL_PHASE;
  return pos.side_to_move() == WHITE ? white_pov + p[P::TEMPO] : -white_pov + p[P::TEMPO];
}

void trace_eval(const Position& pos, EvalTrace& out) {
  out.mg.clear();
  out.eg.clear();
  TraceSink sink{&out};
  out.phase = walk(pos, sink);
  out.stm_sign = pos.side_to_move() == WHITE ? 1 : -1;
}

const std::vector<ParamGroup>& param_groups() {
  static const std::vector<ParamGroup> g = {
      {"mat_mg", P::MAT_MG, 6},       {"mat_eg", P::MAT_EG, 6},
      {"pst_mg", P::PST_MG, 6 * 64},  {"pst_eg", P::PST_EG, 6 * 64},
      {"bishop_pair_mg", P::BISHOP_PAIR_MG, 1}, {"bishop_pair_eg", P::BISHOP_PAIR_EG, 1},
      {"tempo", P::TEMPO, 1},
      {"passed_mg", P::PASSED_MG, 8}, {"passed_eg", P::PASSED_EG, 8},
      {"doubled_mg", P::DOUBLED_MG, 1}, {"doubled_eg", P::DOUBLED_EG, 1},
      {"isolated_mg", P::ISOLATED_MG, 1}, {"isolated_eg", P::ISOLATED_EG, 1},
      {"rook_open_mg", P::ROOK_OPEN_MG, 1}, {"rook_open_eg", P::ROOK_OPEN_EG, 1},
      {"rook_semi_mg", P::ROOK_SEMI_MG, 1}, {"rook_semi_eg", P::ROOK_SEMI_EG, 1},
      {"mob_mg", P::MOB_MG, 6},       {"mob_eg", P::MOB_EG, 6},
  };
  return g;
}

}  // namespace chess
