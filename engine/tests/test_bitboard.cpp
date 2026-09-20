#include "test_framework.h"
#include "../src/board/bitboard.h"

using namespace chess;

TEST(Bitboard, PopcountLsb) {
  CHECK_EQ(popcount(0ULL), 0);
  CHECK_EQ(popcount(~0ULL), 64);
  Bitboard b = bit(3) | bit(40) | bit(63);
  CHECK_EQ(lsb(b), 3);
  CHECK_EQ(pop_lsb(b), 3);
  CHECK_EQ(pop_lsb(b), 40);
  CHECK_EQ(pop_lsb(b), 63);
  CHECK_EQ(b, 0ULL);
}

TEST(Bitboard, KnightAttackCounts) {
  CHECK_EQ(popcount(KnightAttacks[0]), 2);    // a1
  CHECK_EQ(popcount(KnightAttacks[27]), 8);   // d4
  CHECK_EQ(popcount(KnightAttacks[7]), 2);    // h1
  CHECK(KnightAttacks[1] & bit(18));          // b1 -> c3
}

TEST(Bitboard, KingAttackCounts) {
  CHECK_EQ(popcount(KingAttacks[0]), 3);
  CHECK_EQ(popcount(KingAttacks[4]), 5);
  CHECK_EQ(popcount(KingAttacks[27]), 8);
}

TEST(Bitboard, PawnAttacksRespectEdgesAndColour) {
  CHECK_EQ(PawnAttacks[WHITE][make_square(0, 1)], bit(make_square(1, 2)));           // a2 -> b3 only
  CHECK_EQ(PawnAttacks[WHITE][make_square(7, 1)], bit(make_square(6, 2)));           // h2 -> g3 only
  CHECK_EQ(PawnAttacks[WHITE][make_square(4, 1)], bit(make_square(3, 2)) | bit(make_square(5, 2)));
  CHECK_EQ(PawnAttacks[BLACK][make_square(4, 6)], bit(make_square(3, 5)) | bit(make_square(5, 5)));
  CHECK_EQ(PawnAttacks[WHITE][make_square(4, 7)], 0ULL);  // nothing beyond the last rank
  CHECK_EQ(PawnAttacks[BLACK][make_square(4, 0)], 0ULL);
}

TEST(Bitboard, RookAttacksEmptyBoard) {
  for (Square s = 0; s < 64; ++s) CHECK_EQ(popcount(rook_attacks(s, 0)), 14);
}

TEST(Bitboard, BishopAttacksEmptyBoardCorners) {
  CHECK_EQ(popcount(bishop_attacks(0, 0)), 7);
  CHECK_EQ(popcount(bishop_attacks(63, 0)), 7);
  CHECK_EQ(popcount(bishop_attacks(27, 0)), 13);  // d4
}

TEST(Bitboard, SlidersStopAtBlockersAndIncludeThem) {
  Bitboard occ = bit(make_square(3, 3)) | bit(make_square(3, 5)) | bit(make_square(5, 3));  // d4 rook, blockers d6, f4
  Bitboard att = rook_attacks(make_square(3, 3), occ);
  CHECK(att & bit(make_square(3, 5)));    // blocker square itself is attacked
  CHECK(!(att & bit(make_square(3, 6)))); // but not beyond it
  CHECK(att & bit(make_square(5, 3)));
  CHECK(!(att & bit(make_square(6, 3))));
  CHECK(att & bit(make_square(3, 0)));    // open direction reaches the edge
  CHECK(att & bit(make_square(0, 3)));
}

TEST(Bitboard, MagicLookupMatchesRayWalkOnRandomOccupancy) {
  // Independent reference: walk the rays by hand.
  auto walk = [](bool rook, Square s, Bitboard occ) {
    const int rd[4][2] = {{1, 0}, {-1, 0}, {0, 1}, {0, -1}}, bd[4][2] = {{1, 1}, {1, -1}, {-1, 1}, {-1, -1}};
    Bitboard a = 0;
    for (int d = 0; d < 4; ++d) {
      int df = rook ? rd[d][0] : bd[d][0], dr = rook ? rd[d][1] : bd[d][1];
      for (int f = file_of(s) + df, r = rank_of(s) + dr; f >= 0 && f < 8 && r >= 0 && r < 8; f += df, r += dr) {
        a |= bit(make_square(f, r));
        if (occ & bit(make_square(f, r))) break;
      }
    }
    return a;
  };
  uint64_t x = 88172645463325252ULL;
  for (int i = 0; i < 20000; ++i) {
    x ^= x << 13; x ^= x >> 7; x ^= x << 17;
    Bitboard occ = x & (x >> 3);  // moderately sparse
    Square s = Square((x >> 40) & 63);
    if (rook_attacks(s, occ) != walk(true, s, occ)) { CHECK(false); return; }
    if (bishop_attacks(s, occ) != walk(false, s, occ)) { CHECK(false); return; }
  }
}
