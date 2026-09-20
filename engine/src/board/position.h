#pragma once
#include <string>
#include <vector>

#include "bitboard.h"
#include "types.h"

namespace chess {

struct StateInfo {
  Piece captured;
  uint8_t castling;
  Square ep;
  int halfmove;
  uint64_t key;
};

class Position {
 public:
  static constexpr const char* START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";

  Position() : Position(NoInit{}) { set_fen(START_FEN); }
  bool set_fen(const std::string& fen);  // false (position unchanged) on malformed input
  std::string fen() const;

  void make_move(Move m);
  void unmake_move(Move m);
  void make_null_move();  // pass the turn (used by null-move pruning); undo with unmake_null_move
  void unmake_null_move();

  Piece piece_on(Square s) const { return board_[s]; }
  Bitboard pieces(Piece p) const { return by_piece_[p]; }
  Bitboard pieces(Color c, PieceType pt) const { return by_piece_[make_piece(c, pt)]; }
  Bitboard occupied() const { return by_color_[WHITE] | by_color_[BLACK]; }
  Bitboard occupied(Color c) const { return by_color_[c]; }
  Color side_to_move() const { return side_; }
  uint8_t castling() const { return castling_; }
  Square ep_square() const { return ep_; }
  int halfmove_clock() const { return halfmove_; }
  int fullmove_number() const { return fullmove_; }
  Square king_square(Color c) const { return lsb(pieces(c, KING)); }
  uint64_t key() const { return key_; }
  uint64_t compute_key() const;  // from scratch; used to verify the incremental key

  // Is `s` attacked by any piece of colour `by`, given the current occupancy?
  bool attacked(Square s, Color by) const;
  bool in_check() const { return attacked(king_square(side_), ~side_); }

  // Draw detection used by search.
  bool is_repetition() const;        // current position occurred earlier (same side to move)
  bool insufficient_material() const;  // K v K, K+minor v K
  bool has_non_pawn_material(Color c) const {
    return pieces(c, KNIGHT) | pieces(c, BISHOP) | pieces(c, ROOK) | pieces(c, QUEEN);
  }

 private:
  struct NoInit {};
  explicit Position(NoInit);  // empty board; used for the scratch copy in set_fen
  void put_piece(Piece p, Square s);
  void remove_piece(Square s);
  void move_piece(Square from, Square to);
  uint64_t ep_key() const;  // zobrist contribution of the ep square (only if capturable)

  Piece board_[64];
  Bitboard by_piece_[PIECE_NB];
  Bitboard by_color_[COLOR_NB];
  Color side_ = WHITE;
  uint8_t castling_ = 0;
  Square ep_ = SQ_NONE;
  int halfmove_ = 0, fullmove_ = 1;
  uint64_t key_ = 0;
  std::vector<StateInfo> history_;
};

}  // namespace chess
