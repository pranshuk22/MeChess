#pragma once
#include "../board/position.h"
#include "params.h"

namespace chess {

// Static evaluation in centipawns from the point of view of the side to move.
// Handcrafted and linear in its parameters (see params.h): material, piece-square tables, bishop pair,
// pawn structure (passed/doubled/isolated), rooks on open files, mobility; tapered mid/endgame; tempo.
int evaluate(const Position& pos);

// Piece values (cp), indexed by PieceType. Fixed, used for move ordering and pruning margins only.
extern const int PIECE_VALUE[PIECE_TYPE_NB];

}  // namespace chess
