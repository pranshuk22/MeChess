#include "position.h"

#include <cctype>
#include <sstream>

namespace chess {

std::string square_name(Square s) {
  return std::string{char('a' + file_of(s)), char('1' + rank_of(s))};
}

std::string move_to_uci(Move m) {
  if (m.is_null()) return "0000";
  std::string s = square_name(m.from()) + square_name(m.to());
  if (m.is_promotion()) s += "nbrq"[m.promotion_type() - KNIGHT];
  return s;
}

namespace {

struct Zobrist {
  uint64_t piece[PIECE_NB][64];
  uint64_t castling[16];
  uint64_t ep_file[8];
  uint64_t side;
  Zobrist() {
    uint64_t s = 1070372;  // fixed seed: keys are reproducible across runs and platforms
    auto next = [&s]() {
      s ^= s >> 12;
      s ^= s << 25;
      s ^= s >> 27;
      return s * 2685821657736338717ULL;
    };
    for (auto& row : piece) for (auto& k : row) k = next();
    for (auto& k : castling) k = next();
    for (auto& k : ep_file) k = next();
    side = next();
  }
};
const Zobrist Z;

// Squares whose occupation change removes castling rights.
struct CastleMask {
  uint8_t m[64];
  CastleMask() {
    for (auto& x : m) x = 15;
    m[0] &= ~WHITE_OOO;
    m[7] &= ~WHITE_OO;
    m[4] &= ~(WHITE_OO | WHITE_OOO);
    m[56] &= ~BLACK_OOO;
    m[63] &= ~BLACK_OO;
    m[60] &= ~(BLACK_OO | BLACK_OOO);
  }
};
const CastleMask CM;

const char PIECE_CHARS[] = " PNBRQK  pnbrqk";

}  // namespace

Position::Position(NoInit) {
  for (auto& b : board_) b = NO_PIECE;
  for (auto& b : by_piece_) b = 0;
  for (auto& b : by_color_) b = 0;
}

void Position::put_piece(Piece p, Square s) {
  board_[s] = p;
  by_piece_[p] |= bit(s);
  by_color_[color_of(p)] |= bit(s);
}

void Position::remove_piece(Square s) {
  Piece p = board_[s];
  by_piece_[p] &= ~bit(s);
  by_color_[color_of(p)] &= ~bit(s);
  board_[s] = NO_PIECE;
}

void Position::move_piece(Square from, Square to) {
  Piece p = board_[from];
  Bitboard ft = bit(from) | bit(to);
  by_piece_[p] ^= ft;
  by_color_[color_of(p)] ^= ft;
  board_[from] = NO_PIECE;
  board_[to] = p;
}

bool Position::attacked(Square s, Color by) const {
  Bitboard occ = occupied();
  return (PawnAttacks[~by][s] & pieces(by, PAWN)) || (KnightAttacks[s] & pieces(by, KNIGHT)) ||
         (KingAttacks[s] & pieces(by, KING)) ||
         (bishop_attacks(s, occ) & (pieces(by, BISHOP) | pieces(by, QUEEN))) ||
         (rook_attacks(s, occ) & (pieces(by, ROOK) | pieces(by, QUEEN)));
}

uint64_t Position::ep_key() const {
  // The ep square only matters for repetition/TT identity if a pawn can actually capture there.
  if (ep_ == SQ_NONE) return 0;
  if (PawnAttacks[~side_][ep_] & pieces(side_, PAWN)) return Z.ep_file[file_of(ep_)];
  return 0;
}

uint64_t Position::compute_key() const {
  uint64_t k = 0;
  for (Square s = 0; s < 64; ++s)
    if (board_[s]) k ^= Z.piece[board_[s]][s];
  k ^= Z.castling[castling_];
  k ^= ep_key();
  if (side_ == BLACK) k ^= Z.side;
  return k;
}

bool Position::set_fen(const std::string& fen) {
  init_bitboards();
  std::istringstream in(fen);
  std::string board, side, castling, ep;
  int half = 0, full = 1;
  if (!(in >> board >> side >> castling)) return false;
  if (!(in >> ep)) ep = "-";
  in >> half >> full;

  Position p{NoInit{}};  // build into a scratch copy so failure leaves *this untouched

  int file = 0, rank = 7;
  for (char c : board) {
    if (c == '/') {
      if (file != 8) return false;
      file = 0;
      --rank;
      if (rank < 0) return false;
    } else if (std::isdigit(static_cast<unsigned char>(c))) {
      file += c - '0';
      if (file > 8) return false;
    } else {
      const char* pos = std::char_traits<char>::find(PIECE_CHARS, sizeof(PIECE_CHARS) - 1, c);
      if (!pos || c == ' ' || file > 7) return false;
      p.put_piece(Piece(pos - PIECE_CHARS), make_square(file, rank));
      ++file;
    }
  }
  if (rank != 0 || file != 8) return false;
  if (popcount(p.pieces(WHITE, KING)) != 1 || popcount(p.pieces(BLACK, KING)) != 1) return false;

  if (side == "w") p.side_ = WHITE;
  else if (side == "b") p.side_ = BLACK;
  else return false;

  p.castling_ = 0;
  if (castling != "-") {
    for (char c : castling) {
      switch (c) {
        case 'K': p.castling_ |= WHITE_OO; break;
        case 'Q': p.castling_ |= WHITE_OOO; break;
        case 'k': p.castling_ |= BLACK_OO; break;
        case 'q': p.castling_ |= BLACK_OOO; break;
        default: return false;
      }
    }
  }
  p.ep_ = SQ_NONE;
  if (ep != "-") {
    if (ep.size() != 2 || ep[0] < 'a' || ep[0] > 'h' || ep[1] < '1' || ep[1] > '8') return false;
    p.ep_ = make_square(ep[0] - 'a', ep[1] - '1');
  }
  p.halfmove_ = half;
  p.fullmove_ = full < 1 ? 1 : full;
  // The side NOT to move must not be in check (illegal position).
  if (p.attacked(p.king_square(~p.side_), p.side_)) return false;
  p.key_ = p.compute_key();
  *this = p;
  return true;
}

std::string Position::fen() const {
  std::string s;
  for (int r = 7; r >= 0; --r) {
    int empty = 0;
    for (int f = 0; f < 8; ++f) {
      Piece p = board_[make_square(f, r)];
      if (!p) {
        ++empty;
        continue;
      }
      if (empty) s += char('0' + empty), empty = 0;
      s += PIECE_CHARS[p];
    }
    if (empty) s += char('0' + empty);
    if (r) s += '/';
  }
  s += side_ == WHITE ? " w " : " b ";
  if (!castling_) s += '-';
  if (castling_ & WHITE_OO) s += 'K';
  if (castling_ & WHITE_OOO) s += 'Q';
  if (castling_ & BLACK_OO) s += 'k';
  if (castling_ & BLACK_OOO) s += 'q';
  s += ' ';
  s += ep_ == SQ_NONE ? "-" : square_name(ep_);
  s += ' ' + std::to_string(halfmove_) + ' ' + std::to_string(fullmove_);
  return s;
}

void Position::make_move(Move m) {
  const Square from = m.from(), to = m.to();
  const uint16_t flags = m.flags();
  const Color us = side_, them = ~us;
  const Piece pc = board_[from];

  StateInfo st{NO_PIECE, castling_, ep_, halfmove_, key_};

  key_ ^= ep_key();  // remove old ep contribution (uses old ep_ / side_)

  if (flags == EP_CAPTURE) {
    Square cap = to + (us == WHITE ? -8 : 8);
    st.captured = board_[cap];
    key_ ^= Z.piece[st.captured][cap];
    remove_piece(cap);
  } else if (m.is_capture()) {
    st.captured = board_[to];
    key_ ^= Z.piece[st.captured][to];
    remove_piece(to);
  }

  if (m.is_promotion()) {
    Piece promo = make_piece(us, m.promotion_type());
    key_ ^= Z.piece[pc][from] ^ Z.piece[promo][to];
    remove_piece(from);
    put_piece(promo, to);
  } else {
    key_ ^= Z.piece[pc][from] ^ Z.piece[pc][to];
    move_piece(from, to);
  }

  if (flags == KING_CASTLE) {
    Square rf = to + 1, rt = to - 1;
    Piece rook = board_[rf];
    key_ ^= Z.piece[rook][rf] ^ Z.piece[rook][rt];
    move_piece(rf, rt);
  } else if (flags == QUEEN_CASTLE) {
    Square rf = to - 2, rt = to + 1;
    Piece rook = board_[rf];
    key_ ^= Z.piece[rook][rf] ^ Z.piece[rook][rt];
    move_piece(rf, rt);
  }

  ep_ = flags == DOUBLE_PUSH ? from + (us == WHITE ? 8 : -8) : SQ_NONE;

  key_ ^= Z.castling[castling_];
  castling_ &= CM.m[from] & CM.m[to];
  key_ ^= Z.castling[castling_];

  halfmove_ = (type_of(pc) == PAWN || m.is_capture()) ? 0 : halfmove_ + 1;
  if (us == BLACK) ++fullmove_;
  side_ = them;
  key_ ^= Z.side;
  key_ ^= ep_key();  // add new ep contribution (uses new ep_ / side_)

  history_.push_back(st);
}

void Position::unmake_move(Move m) {
  const StateInfo st = history_.back();
  history_.pop_back();

  side_ = ~side_;
  const Color us = side_;
  const Square from = m.from(), to = m.to();
  const uint16_t flags = m.flags();

  if (m.is_promotion()) {
    remove_piece(to);
    put_piece(make_piece(us, PAWN), from);
  } else {
    move_piece(to, from);
  }

  if (flags == KING_CASTLE) move_piece(to - 1, to + 1);
  else if (flags == QUEEN_CASTLE) move_piece(to + 1, to - 2);

  if (m.is_capture()) {
    Square cap = flags == EP_CAPTURE ? to + (us == WHITE ? -8 : 8) : to;
    put_piece(st.captured, cap);
  }

  castling_ = st.castling;
  ep_ = st.ep;
  halfmove_ = st.halfmove;
  key_ = st.key;
  if (us == BLACK) --fullmove_;
}

void Position::make_null_move() {
  history_.push_back(StateInfo{NO_PIECE, castling_, ep_, halfmove_, key_});
  key_ ^= ep_key();
  ep_ = SQ_NONE;
  side_ = ~side_;
  key_ ^= Z.side;
  ++halfmove_;
}

void Position::unmake_null_move() {
  const StateInfo st = history_.back();
  history_.pop_back();
  side_ = ~side_;
  ep_ = st.ep;
  halfmove_ = st.halfmove;
  key_ = st.key;
}

bool Position::is_repetition() const {
  const int n = int(history_.size());
  const int limit = halfmove_ < n ? halfmove_ : n;
  for (int i = 2; i <= limit; i += 2)
    if (history_[n - i].key == key_) return true;
  return false;
}

bool Position::insufficient_material() const {
  if (pieces(WHITE, PAWN) | pieces(BLACK, PAWN) | pieces(WHITE, ROOK) | pieces(BLACK, ROOK) |
      pieces(WHITE, QUEEN) | pieces(BLACK, QUEEN))
    return false;
  const int minors = popcount(pieces(WHITE, KNIGHT) | pieces(WHITE, BISHOP) | pieces(BLACK, KNIGHT) |
                              pieces(BLACK, BISHOP));
  return minors <= 1;
}

}  // namespace chess
