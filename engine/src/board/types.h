#pragma once
#include <cstdint>
#include <string>

namespace chess {

using Bitboard = uint64_t;

enum Color : int { WHITE = 0, BLACK = 1, COLOR_NB = 2 };
constexpr Color operator~(Color c) { return Color(c ^ 1); }

enum PieceType : int { NO_PIECE_TYPE = 0, PAWN, KNIGHT, BISHOP, ROOK, QUEEN, KING, PIECE_TYPE_NB };

// Piece code = color * 8 + piece type, so it doubles as an array index (0..14).
enum Piece : int { NO_PIECE = 0, PIECE_NB = 16 };
constexpr Piece make_piece(Color c, PieceType pt) { return Piece(c * 8 + pt); }
constexpr Color color_of(Piece p) { return Color(p >> 3); }
constexpr PieceType type_of(Piece p) { return PieceType(p & 7); }

// Squares: a1 = 0, b1 = 1, ..., h8 = 63.
using Square = int;
constexpr Square SQ_NONE = 64;
constexpr int file_of(Square s) { return s & 7; }
constexpr int rank_of(Square s) { return s >> 3; }
constexpr Square make_square(int file, int rank) { return rank * 8 + file; }
constexpr Bitboard bit(Square s) { return 1ULL << s; }

// Castling rights bitmask.
enum : uint8_t { WHITE_OO = 1, WHITE_OOO = 2, BLACK_OO = 4, BLACK_OOO = 8 };

enum MoveFlag : uint16_t {
  QUIET = 0,
  DOUBLE_PUSH = 1,
  KING_CASTLE = 2,
  QUEEN_CASTLE = 3,
  CAPTURE = 4,
  EP_CAPTURE = 5,
  PROMO_N = 8, PROMO_B = 9, PROMO_R = 10, PROMO_Q = 11,
  PROMO_CAP_N = 12, PROMO_CAP_B = 13, PROMO_CAP_R = 14, PROMO_CAP_Q = 15,
};

// 16-bit move: from (6) | to (6) << 6 | flags (4) << 12.
struct Move {
  uint16_t v = 0;
  constexpr Move() = default;
  constexpr Move(Square from, Square to, uint16_t flags) : v(uint16_t(from | (to << 6) | (flags << 12))) {}
  constexpr Square from() const { return v & 63; }
  constexpr Square to() const { return (v >> 6) & 63; }
  constexpr uint16_t flags() const { return v >> 12; }
  constexpr bool is_capture() const { return flags() & 4; }
  constexpr bool is_promotion() const { return flags() & 8; }
  constexpr PieceType promotion_type() const { return PieceType((flags() & 3) + KNIGHT); }
  constexpr bool operator==(Move o) const { return v == o.v; }
  constexpr bool operator!=(Move o) const { return v != o.v; }
  constexpr bool is_null() const { return v == 0; }
};

std::string square_name(Square s);
std::string move_to_uci(Move m);

}  // namespace chess
