#include "movegen.h"

namespace chess {

namespace {

void add_promotions(MoveList& out, Square from, Square to, bool capture) {
  uint16_t base = capture ? PROMO_CAP_N : PROMO_N;
  for (uint16_t i = 0; i < 4; ++i) out.add(Move(from, to, base + i));
}

void gen_piece_moves(const Position& pos, MoveList& out, Color us, PieceType pt, Bitboard occ, Bitboard own,
                     Bitboard theirs) {
  Bitboard pcs = pos.pieces(us, pt);
  while (pcs) {
    Square from = pop_lsb(pcs);
    Bitboard att;
    switch (pt) {
      case KNIGHT: att = KnightAttacks[from]; break;
      case BISHOP: att = bishop_attacks(from, occ); break;
      case ROOK: att = rook_attacks(from, occ); break;
      case QUEEN: att = queen_attacks(from, occ); break;
      default: att = KingAttacks[from]; break;
    }
    att &= ~own;
    while (att) {
      Square to = pop_lsb(att);
      out.add(Move(from, to, (theirs & bit(to)) ? CAPTURE : QUIET));
    }
  }
}

}  // namespace

void generate_pseudo_legal(const Position& pos, MoveList& out) {
  out.count = 0;
  const Color us = pos.side_to_move(), them = ~us;
  const Bitboard occ = pos.occupied(), own = pos.occupied(us), theirs = pos.occupied(them);

  // Pawns
  const int up = us == WHITE ? 8 : -8;
  const int start_rank = us == WHITE ? 1 : 6;
  const int promo_rank = us == WHITE ? 7 : 0;
  Bitboard pawns = pos.pieces(us, PAWN);
  while (pawns) {
    Square from = pop_lsb(pawns);
    Square one = from + up;
    if (!(occ & bit(one))) {
      if (rank_of(one) == promo_rank) {
        add_promotions(out, from, one, false);
      } else {
        out.add(Move(from, one, QUIET));
        if (rank_of(from) == start_rank && !(occ & bit(one + up))) out.add(Move(from, one + up, DOUBLE_PUSH));
      }
    }
    Bitboard caps = PawnAttacks[us][from] & theirs;
    while (caps) {
      Square to = pop_lsb(caps);
      if (rank_of(to) == promo_rank) add_promotions(out, from, to, true);
      else out.add(Move(from, to, CAPTURE));
    }
    if (pos.ep_square() != SQ_NONE && (PawnAttacks[us][from] & bit(pos.ep_square())))
      out.add(Move(from, pos.ep_square(), EP_CAPTURE));
  }

  gen_piece_moves(pos, out, us, KNIGHT, occ, own, theirs);
  gen_piece_moves(pos, out, us, BISHOP, occ, own, theirs);
  gen_piece_moves(pos, out, us, ROOK, occ, own, theirs);
  gen_piece_moves(pos, out, us, QUEEN, occ, own, theirs);
  gen_piece_moves(pos, out, us, KING, occ, own, theirs);

  // Castling: right present, squares between empty, king not in check and not passing through attack.
  const uint8_t cr = pos.castling();
  if (us == WHITE) {
    if ((cr & WHITE_OO) && !(occ & (bit(5) | bit(6))) && !pos.attacked(4, them) && !pos.attacked(5, them) &&
        !pos.attacked(6, them))
      out.add(Move(4, 6, KING_CASTLE));
    if ((cr & WHITE_OOO) && !(occ & (bit(1) | bit(2) | bit(3))) && !pos.attacked(4, them) &&
        !pos.attacked(3, them) && !pos.attacked(2, them))
      out.add(Move(4, 2, QUEEN_CASTLE));
  } else {
    if ((cr & BLACK_OO) && !(occ & (bit(61) | bit(62))) && !pos.attacked(60, them) && !pos.attacked(61, them) &&
        !pos.attacked(62, them))
      out.add(Move(60, 62, KING_CASTLE));
    if ((cr & BLACK_OOO) && !(occ & (bit(57) | bit(58) | bit(59))) && !pos.attacked(60, them) &&
        !pos.attacked(59, them) && !pos.attacked(58, them))
      out.add(Move(60, 58, QUEEN_CASTLE));
  }
}

void generate_legal(Position& pos, MoveList& out) {
  MoveList pseudo;
  generate_pseudo_legal(pos, pseudo);
  out.count = 0;
  for (Move m : pseudo) {
    pos.make_move(m);
    if (mover_is_safe(pos)) out.add(m);
    pos.unmake_move(m);
  }
}

Move parse_uci_move(Position& pos, const std::string& s) {
  MoveList legal;
  generate_legal(pos, legal);
  for (Move m : legal)
    if (move_to_uci(m) == s) return m;
  return Move();
}

}  // namespace chess
