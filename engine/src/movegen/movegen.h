#pragma once
#include <string>

#include "../board/position.h"

namespace chess {

struct MoveList {
  Move moves[256];
  int count = 0;
  void add(Move m) { moves[count++] = m; }
  const Move* begin() const { return moves; }
  const Move* end() const { return moves + count; }
};

// Pseudo-legal moves: may leave the mover's king in check (filter with is_legal_after / generate_legal).
void generate_pseudo_legal(const Position& pos, MoveList& out);

// Fully legal moves. Uses make/unmake internally, so the position is taken by non-const reference
// but is restored before returning.
void generate_legal(Position& pos, MoveList& out);

// True if, after `m` has been made on `pos`, the side that just moved is not in check.
inline bool mover_is_safe(const Position& pos) { return !pos.attacked(pos.king_square(~pos.side_to_move()), pos.side_to_move()); }

// Parses "e2e4" / "e7e8q" against the legal moves of `pos`; returns a null Move if not legal.
Move parse_uci_move(Position& pos, const std::string& s);

}  // namespace chess
