#include "book.h"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <fstream>

#include "../movegen/movegen.h"

namespace chess {

uint64_t fnv1a64(const std::string& s) {
  uint64_t h = 14695981039346656037ULL;
  for (unsigned char c : s) {
    h ^= c;
    h *= 1099511628211ULL;
  }
  return h;
}

uint64_t book_key(const Position& pos) {
  const std::string fen = pos.fen();
  size_t end = 0;
  for (int spaces = 0; end < fen.size() && spaces < 3; ++end)
    if (fen[end] == ' ' && ++spaces == 3) break;
  return fnv1a64(fen.substr(0, end));
}

namespace {
constexpr size_t HEADER_BYTES = 16, ENTRY_BYTES = 20;

uint64_t rd64(const unsigned char* p) {
  uint64_t v = 0;
  for (int i = 7; i >= 0; --i) v = (v << 8) | p[i];
  return v;
}
uint32_t rd32(const unsigned char* p) { return uint32_t(p[0]) | uint32_t(p[1]) << 8 | uint32_t(p[2]) << 16 | uint32_t(p[3]) << 24; }
uint16_t rd16(const unsigned char* p) { return uint16_t(p[0] | p[1] << 8); }
}  // namespace

bool Book::load(const std::string& path, std::string* error) {
  auto fail = [&](const std::string& msg) {
    if (error) *error = msg;
    return false;
  };
  std::ifstream f(path, std::ios::binary);
  if (!f) return fail("cannot open " + path);
  std::vector<unsigned char> data((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>());
  if (data.size() < HEADER_BYTES || std::memcmp(data.data(), "CMBK", 4) != 0) return fail("not a chessme book (bad magic)");
  if (rd32(&data[4]) != 1) return fail("unsupported book version " + std::to_string(rd32(&data[4])));
  const uint64_t count = rd64(&data[8]);
  if (count > (data.size() - HEADER_BYTES) / ENTRY_BYTES || data.size() != HEADER_BYTES + count * ENTRY_BYTES)
    return fail("book file is truncated or has trailing bytes");

  std::vector<BookEntry> entries(count);
  for (uint64_t i = 0; i < count; ++i) {
    const unsigned char* p = &data[HEADER_BYTES + i * ENTRY_BYTES];
    BookEntry& e = entries[i];
    e.key = rd64(p);
    e.from = p[8];
    e.to = p[9];
    e.promo = p[10];
    const uint32_t bits = rd32(p + 12);
    std::memcpy(&e.weight, &bits, sizeof(float));
    e.games = rd16(p + 16);
    e.score_permille = rd16(p + 18);
    if (e.from > 63 || e.to > 63 || e.promo == 1 || e.promo > 5) return fail("book entry " + std::to_string(i) + " is invalid");
    if (!(e.weight > 0) || !std::isfinite(e.weight)) return fail("book entry " + std::to_string(i) + " has a bad weight");
    if (i > 0 && entries[i - 1].key > e.key) return fail("book entries are not sorted by key");
  }
  entries_ = std::move(entries);
  return true;
}

std::vector<Book::Candidate> Book::candidates(Position& pos) const {
  std::vector<Candidate> out;
  const uint64_t key = book_key(pos);
  auto lo = std::lower_bound(entries_.begin(), entries_.end(), key, [](const BookEntry& e, uint64_t k) { return e.key < k; });
  if (lo == entries_.end() || lo->key != key) return out;
  MoveList legal;
  generate_legal(pos, legal);
  for (auto it = lo; it != entries_.end() && it->key == key; ++it) {
    for (Move m : legal) {
      const int promo = m.is_promotion() ? int(m.promotion_type()) : 0;
      if (m.from() == it->from && m.to() == it->to && promo == it->promo) {
        out.push_back({m, it->weight, it->games});
        break;
      }
    }
  }
  return out;
}

Move Book::pick(Position& pos, double temperature, std::mt19937_64& rng) const {
  std::vector<Candidate> c = candidates(pos);
  if (c.empty()) return Move();
  if (temperature <= 0) {
    return std::max_element(c.begin(), c.end(), [](const Candidate& a, const Candidate& b) { return a.weight < b.weight; })->move;
  }
  std::vector<double> w(c.size());
  double total = 0;
  for (size_t i = 0; i < c.size(); ++i) total += (w[i] = std::pow(double(c[i].weight), 1.0 / temperature));
  double r = std::uniform_real_distribution<double>(0.0, total)(rng);
  for (size_t i = 0; i < c.size(); ++i) {
    if ((r -= w[i]) < 0) return c[i].move;
  }
  return c.back().move;
}

}  // namespace chess
