#include "bitboard.h"

namespace chess {

Bitboard PawnAttacks[COLOR_NB][64];
Bitboard KnightAttacks[64];
Bitboard KingAttacks[64];
Magic RookMagics[64];
Magic BishopMagics[64];

namespace {

Bitboard RookTable[0x19000];
Bitboard BishopTable[0x1480];

struct PRNG {
  uint64_t s;
  explicit PRNG(uint64_t seed) : s(seed) {}
  uint64_t rand64() {
    s ^= s >> 12;
    s ^= s << 25;
    s ^= s >> 27;
    return s * 2685821657736338717ULL;
  }
  uint64_t sparse_rand() { return rand64() & rand64() & rand64(); }
};

Bitboard sliding_attack(bool rook, Square sq, Bitboard occ) {
  static const int rook_dirs[4][2] = {{1, 0}, {-1, 0}, {0, 1}, {0, -1}};
  static const int bishop_dirs[4][2] = {{1, 1}, {1, -1}, {-1, 1}, {-1, -1}};
  const int(*dirs)[2] = rook ? rook_dirs : bishop_dirs;
  Bitboard att = 0;
  for (int d = 0; d < 4; ++d) {
    int f = file_of(sq) + dirs[d][0], r = rank_of(sq) + dirs[d][1];
    while (f >= 0 && f < 8 && r >= 0 && r < 8) {
      Bitboard b = bit(make_square(f, r));
      att |= b;
      if (occ & b) break;
      f += dirs[d][0];
      r += dirs[d][1];
    }
  }
  return att;
}

void init_magics(bool rook, Bitboard table[], Magic magics[]) {
  static const uint64_t seeds[8] = {728, 10316, 55013, 32803, 12281, 15100, 16645, 255};
  Bitboard occupancy[4096], reference[4096];
  int epoch[4096] = {}, cnt = 0, size = 0;

  for (Square s = 0; s < 64; ++s) {
    Bitboard rank_bb = RANK_1 << (8 * rank_of(s)), file_bb = FILE_A << file_of(s);
    Bitboard edges = ((RANK_1 | RANK_8) & ~rank_bb) | ((FILE_A | FILE_H) & ~file_bb);
    Magic& m = magics[s];
    m.mask = sliding_attack(rook, s, 0) & ~edges;
    m.shift = 64 - popcount(m.mask);
    m.attacks = s == 0 ? table : magics[s - 1].attacks + size;

    // Enumerate all subsets of the mask (carry-rippler) with their true attack sets.
    Bitboard b = 0;
    size = 0;
    do {
      occupancy[size] = b;
      reference[size] = sliding_attack(rook, s, b);
      ++size;
      b = (b - m.mask) & m.mask;
    } while (b);

    PRNG rng(seeds[rank_of(s)]);
    for (int i = 0; i < size;) {
      for (m.magic = 0; popcount((m.magic * m.mask) >> 56) < 6;) m.magic = rng.sparse_rand();
      for (++cnt, i = 0; i < size; ++i) {
        unsigned idx = m.index(occupancy[i]);
        if (epoch[idx] < cnt) {
          epoch[idx] = cnt;
          m.attacks[idx] = reference[i];
        } else if (m.attacks[idx] != reference[i]) {
          break;
        }
      }
    }
  }
}

Bitboard step_attacks(Square s, const int (*steps)[2], int n) {
  Bitboard b = 0;
  for (int i = 0; i < n; ++i) {
    int f = file_of(s) + steps[i][0], r = rank_of(s) + steps[i][1];
    if (f >= 0 && f < 8 && r >= 0 && r < 8) b |= bit(make_square(f, r));
  }
  return b;
}

}  // namespace

void init_bitboards() {
  static bool done = false;
  if (done) return;
  done = true;

  static const int knight[8][2] = {{1, 2}, {2, 1}, {2, -1}, {1, -2}, {-1, -2}, {-2, -1}, {-2, 1}, {-1, 2}};
  static const int king[8][2] = {{1, 0}, {1, 1}, {0, 1}, {-1, 1}, {-1, 0}, {-1, -1}, {0, -1}, {1, -1}};
  static const int wpawn[2][2] = {{-1, 1}, {1, 1}};
  static const int bpawn[2][2] = {{-1, -1}, {1, -1}};
  for (Square s = 0; s < 64; ++s) {
    KnightAttacks[s] = step_attacks(s, knight, 8);
    KingAttacks[s] = step_attacks(s, king, 8);
    PawnAttacks[WHITE][s] = step_attacks(s, wpawn, 2);
    PawnAttacks[BLACK][s] = step_attacks(s, bpawn, 2);
  }
  init_magics(true, RookTable, RookMagics);
  init_magics(false, BishopTable, BishopMagics);
}

}  // namespace chess
