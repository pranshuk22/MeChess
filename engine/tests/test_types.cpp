#include "test_framework.h"
#include "../src/board/types.h"

using namespace chess;

TEST(Types, MoveEncodingRoundTrips) {
  for (Square from : {0, 12, 63}) {
    for (Square to : {1, 28, 62}) {
      for (uint16_t flags = 0; flags < 16; ++flags) {
        Move m(from, to, flags);
        CHECK_EQ(m.from(), from);
        CHECK_EQ(m.to(), to);
        CHECK_EQ(m.flags(), flags);
      }
    }
  }
}

TEST(Types, MoveClassification) {
  CHECK(!Move(8, 16, QUIET).is_capture());
  CHECK(Move(8, 17, CAPTURE).is_capture());
  CHECK(Move(32, 41, EP_CAPTURE).is_capture());
  CHECK(!Move(8, 16, DOUBLE_PUSH).is_capture());
  CHECK(!Move(4, 6, KING_CASTLE).is_capture());
  CHECK(!Move(4, 6, KING_CASTLE).is_promotion());
  CHECK(Move(48, 56, PROMO_Q).is_promotion());
  CHECK(!Move(48, 56, PROMO_Q).is_capture());
  CHECK(Move(48, 57, PROMO_CAP_N).is_promotion());
  CHECK(Move(48, 57, PROMO_CAP_N).is_capture());
}

TEST(Types, PromotionTypeMapping) {
  CHECK_EQ(int(Move(48, 56, PROMO_N).promotion_type()), int(KNIGHT));
  CHECK_EQ(int(Move(48, 56, PROMO_B).promotion_type()), int(BISHOP));
  CHECK_EQ(int(Move(48, 56, PROMO_R).promotion_type()), int(ROOK));
  CHECK_EQ(int(Move(48, 56, PROMO_Q).promotion_type()), int(QUEEN));
  CHECK_EQ(int(Move(48, 57, PROMO_CAP_Q).promotion_type()), int(QUEEN));
}

TEST(Types, PieceEncoding) {
  Piece p = make_piece(BLACK, KNIGHT);
  CHECK_EQ(int(color_of(p)), int(BLACK));
  CHECK_EQ(int(type_of(p)), int(KNIGHT));
  CHECK_EQ(int(color_of(make_piece(WHITE, KING))), int(WHITE));
  CHECK_EQ(int(~WHITE), int(BLACK));
}

TEST(Types, SquareHelpers) {
  CHECK_EQ(make_square(0, 0), 0);
  CHECK_EQ(make_square(7, 7), 63);
  CHECK_EQ(file_of(28), 4);
  CHECK_EQ(rank_of(28), 3);
  CHECK_EQ(square_name(0), std::string("a1"));
  CHECK_EQ(square_name(63), std::string("h8"));
  CHECK_EQ(square_name(28), std::string("e4"));
}

TEST(Types, UciStrings) {
  CHECK_EQ(move_to_uci(Move(12, 28, DOUBLE_PUSH)), std::string("e2e4"));
  CHECK_EQ(move_to_uci(Move(52, 60, PROMO_Q)), std::string("e7e8q"));
  CHECK_EQ(move_to_uci(Move(52, 61, PROMO_CAP_N)), std::string("e7f8n"));
  CHECK_EQ(move_to_uci(Move()), std::string("0000"));
}
