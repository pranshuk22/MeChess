#pragma once
#include "types.h"

namespace chess {

constexpr Bitboard FILE_A = 0x0101010101010101ULL;
constexpr Bitboard FILE_H = FILE_A << 7;
constexpr Bitboard RANK_1 = 0xFFULL;
constexpr Bitboard RANK_8 = RANK_1 << 56;

inline int popcount(Bitboard b) { return __builtin_popcountll(b); }
inline Square lsb(Bitboard b) { return Square(__builtin_ctzll(b)); }
inline Square pop_lsb(Bitboard& b) {
  Square s = lsb(b);
  b &= b - 1;
  return s;
}

extern Bitboard PawnAttacks[COLOR_NB][64];  // squares attacked by a pawn of colour c standing on sq
extern Bitboard KnightAttacks[64];
extern Bitboard KingAttacks[64];

struct Magic {
  Bitboard mask;
  Bitboard magic;
  Bitboard* attacks;
  unsigned shift;
  unsigned index(Bitboard occ) const { return unsigned(((occ & mask) * magic) >> shift); }
};
extern Magic RookMagics[64];
extern Magic BishopMagics[64];

inline Bitboard rook_attacks(Square s, Bitboard occ) { return RookMagics[s].attacks[RookMagics[s].index(occ)]; }
inline Bitboard bishop_attacks(Square s, Bitboard occ) { return BishopMagics[s].attacks[BishopMagics[s].index(occ)]; }
inline Bitboard queen_attacks(Square s, Bitboard occ) { return rook_attacks(s, occ) | bishop_attacks(s, occ); }

// Builds all attack tables (magic numbers are found deterministically at startup). Idempotent.
void init_bitboards();

}  // namespace chess
