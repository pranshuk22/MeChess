#pragma once
// Opening book built from a player's own games (see chessme/book in the Python package).
//
// File format (little-endian): "CMBK" | u32 version=1 | u64 entry_count | entries...
// Entry (20 bytes): u64 key | u8 from | u8 to | u8 promo (0 or PieceType 2..5) | u8 reserved
//                   | f32 weight | u16 games | u16 score_permille
// Entries are sorted by key. Position key = FNV-1a 64 over "<board> <side> <castling>" (the first three FEN
// fields), so transpositions share entries and move counters / en-passant squares are ignored.
#include <cstdint>
#include <random>
#include <string>
#include <vector>

#include "../board/position.h"

namespace chess {

uint64_t fnv1a64(const std::string& s);
uint64_t book_key(const Position& pos);

struct BookEntry {
  uint64_t key = 0;
  uint8_t from = 0, to = 0, promo = 0;
  float weight = 0;
  uint16_t games = 0;
  uint16_t score_permille = 0;  // the player's average score with this move, 0..1000
};

class Book {
 public:
  struct Candidate {
    Move move;
    float weight;
    int games;
  };

  bool load(const std::string& path, std::string* error = nullptr);
  void clear() { entries_.clear(); }
  bool empty() const { return entries_.empty(); }
  size_t size() const { return entries_.size(); }

  // Legal moves the book has for `pos` (entries that are not legal here, e.g. hash collisions, are dropped).
  std::vector<Candidate> candidates(Position& pos) const;

  // temperature <= 0: always the heaviest move. Otherwise sample with probability ~ weight^(1/temperature),
  // so 1.0 reproduces the player's own frequencies and larger values flatten them.
  // Returns a null Move when the position is not in the book.
  Move pick(Position& pos, double temperature, std::mt19937_64& rng) const;

 private:
  std::vector<BookEntry> entries_;  // sorted by key
};

}  // namespace chess
