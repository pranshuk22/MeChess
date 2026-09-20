#include <cmath>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <map>
#include <sstream>

#include "test_framework.h"
#include "../src/book/book.h"
#include "../src/movegen/movegen.h"
#include "../src/uci/uci.h"

using namespace chess;

namespace {

struct Raw {
  uint64_t key;
  uint8_t from, to, promo;
  float weight;
  uint16_t games = 1;
  uint16_t score = 500;
};

void put(std::string& s, uint64_t v, int bytes) {
  for (int i = 0; i < bytes; ++i) s.push_back(char((v >> (8 * i)) & 0xff));
}

std::string book_bytes(const std::vector<Raw>& entries, uint32_t version = 1, const char* magic = "CMBK") {
  std::string s(magic, 4);
  put(s, version, 4);
  put(s, entries.size(), 8);
  for (const Raw& e : entries) {
    put(s, e.key, 8);
    s.push_back(char(e.from));
    s.push_back(char(e.to));
    s.push_back(char(e.promo));
    s.push_back(0);
    uint32_t bits;
    std::memcpy(&bits, &e.weight, 4);
    put(s, bits, 4);
    put(s, e.games, 2);
    put(s, e.score, 2);
  }
  return s;
}

std::string write_file(const std::string& name, const std::string& bytes) {
  const std::string path = "/tmp/chessme_test_" + name;
  std::ofstream f(path, std::ios::binary);
  f.write(bytes.data(), std::streamsize(bytes.size()));
  return path;
}

Position from(const char* fen) {
  Position p;
  CHECK(p.set_fen(fen));
  return p;
}

// Standard opening book: start position -> e4 (3), d4 (1); after 1.e4 -> c5 (2), e5 (2).
std::string sample_book() {
  Position start, after_e4 = from("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1");
  std::vector<Raw> v = {
      {book_key(start), 12, 28, 0, 3.0f},   // e2e4
      {book_key(start), 11, 27, 0, 1.0f},   // d2d4
      {book_key(after_e4), 50, 34, 0, 2.0f},  // c7c5
      {book_key(after_e4), 52, 36, 0, 2.0f},  // e7e5
  };
  std::sort(v.begin(), v.end(), [](const Raw& a, const Raw& b) { return a.key < b.key; });
  return book_bytes(v);
}

std::string session(const std::string& script) {
  std::istringstream in(script);
  std::ostringstream out;
  Uci uci(in, out);
  uci.run();
  return out.str();
}
bool has(const std::string& hay, const std::string& needle) { return hay.find(needle) != std::string::npos; }

}  // namespace

// ---- keys ------------------------------------------------------------------------------------------------

TEST(BookKey, Fnv1aMatchesPublishedVectors) {
  CHECK_EQ(fnv1a64(""), 0xcbf29ce484222325ULL);
  CHECK_EQ(fnv1a64("a"), 0xaf63dc4c8601ec8cULL);
  CHECK_EQ(fnv1a64("foobar"), 0x85944171f73967e8ULL);
}

TEST(BookKey, MatchesTheValuesTheBuilderComputesInPython) {
  // Constants produced by chessme/book/keys.py: the two languages must agree or the book never matches.
  CHECK_EQ(book_key(Position()), 0x7bd6409c02270343ULL);
  CHECK_EQ(book_key(from("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1")), 0xdf98c55fc062adb4ULL);
}

TEST(BookKey, IgnoresMoveCountersAndEnPassantButNotSideOrCastling) {
  const uint64_t base = book_key(from("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"));
  CHECK_EQ(book_key(from("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 12 40")), base);
  CHECK(book_key(from("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 1")) != base);
  CHECK(book_key(from("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b Kkq - 0 1")) != base);
}

TEST(BookKey, TranspositionsShareAKey) {
  Position a, b;
  for (const char* m : {"g1f3", "g8f6", "b1c3", "b8c6"}) a.make_move(parse_uci_move(a, m));
  for (const char* m : {"b1c3", "b8c6", "g1f3", "g8f6"}) b.make_move(parse_uci_move(b, m));
  CHECK_EQ(book_key(a), book_key(b));
}

// ---- loading ---------------------------------------------------------------------------------------------

TEST(Book, LoadsAValidFile) {
  Book b;
  std::string err;
  CHECK(b.load(write_file("ok.bin", sample_book()), &err));
  CHECK_EQ(int(b.size()), 4);
  CHECK(!b.empty());
}

TEST(Book, RejectsCorruptFiles) {
  Book b;
  std::string err;
  const std::string good = sample_book();
  CHECK(!b.load("/no/such/book.bin", &err));
  CHECK(err.find("cannot open") != std::string::npos);
  CHECK(!b.load(write_file("magic.bin", "XXXX" + good.substr(4)), &err));
  CHECK(err.find("magic") != std::string::npos);
  CHECK(!b.load(write_file("short.bin", good.substr(0, 10)), &err));
  CHECK(!b.load(write_file("trunc.bin", good.substr(0, good.size() - 5)), &err));
  CHECK(err.find("truncated") != std::string::npos);
  CHECK(!b.load(write_file("trail.bin", good + "x"), &err));
  CHECK(!b.load(write_file("ver.bin", book_bytes({}, 2)), &err));
  CHECK(err.find("version") != std::string::npos);
  CHECK(!b.load(write_file("sq.bin", book_bytes({{1, 64, 0, 0, 1.f}})), &err));          // square out of range
  CHECK(!b.load(write_file("promo.bin", book_bytes({{1, 8, 16, 1, 1.f}})), &err));       // promo type 1 = pawn
  CHECK(!b.load(write_file("w0.bin", book_bytes({{1, 8, 16, 0, 0.f}})), &err));          // zero weight
  CHECK(!b.load(write_file("wnan.bin", book_bytes({{1, 8, 16, 0, std::nanf("")}})), &err));
  CHECK(!b.load(write_file("uns.bin", book_bytes({{9, 8, 16, 0, 1.f}, {3, 8, 16, 0, 1.f}})), &err));
  CHECK(err.find("sorted") != std::string::npos);
}

TEST(Book, FailedLoadKeepsThePreviousBook) {
  Book b;
  CHECK(b.load(write_file("keep.bin", sample_book())));
  CHECK(!b.load("/no/such/file"));
  CHECK_EQ(int(b.size()), 4);
}

TEST(Book, EmptyBookIsValid) {
  Book b;
  CHECK(b.load(write_file("empty.bin", book_bytes({}))));
  CHECK(b.empty());
  Position p;
  std::mt19937_64 rng(1);
  CHECK(b.pick(p, 1.0, rng).is_null());
}

// ---- lookup and selection --------------------------------------------------------------------------------

TEST(Book, CandidatesAreTheLegalBookMoves) {
  Book b;
  CHECK(b.load(write_file("cand.bin", sample_book())));
  Position p;
  auto c = b.candidates(p);
  CHECK_EQ(int(c.size()), 2);
  std::map<std::string, float> got;
  for (auto& x : c) got[move_to_uci(x.move)] = x.weight;
  CHECK_EQ(got["e2e4"], 3.0f);
  CHECK_EQ(got["d2d4"], 1.0f);
}

TEST(Book, UnknownPositionsHaveNoCandidates) {
  Book b;
  CHECK(b.load(write_file("unk.bin", sample_book())));
  Position p = from("rnbqkbnr/pppppppp/8/8/8/5N2/PPPPPPPP/RNBQKB1R b KQkq - 1 1");
  CHECK(b.candidates(p).empty());
  std::mt19937_64 rng(1);
  CHECK(b.pick(p, 1.0, rng).is_null());
}

TEST(Book, IllegalEntriesAreIgnored) {
  // A hash collision or stale entry must never yield an illegal move: e2e5 is not legal at the start.
  Position start;
  Book b;
  CHECK(b.load(write_file("illegal.bin", book_bytes({{book_key(start), 12, 36, 0, 5.f}, {book_key(start), 12, 28, 0, 1.f}}))));
  auto c = b.candidates(start);
  CHECK_EQ(int(c.size()), 1);
  CHECK_EQ(move_to_uci(c[0].move), std::string("e2e4"));
}

TEST(Book, PromotionEntriesMatchThePromotionPiece) {
  Position p = from("8/P7/8/8/8/8/8/k6K w - - 0 1");
  Book b;
  // a7a8 promoting to knight (2) and queen (5); an entry with promo 0 (illegal: must promote) is dropped
  CHECK(b.load(write_file("promo_ok.bin", book_bytes({{book_key(p), 48, 56, 2, 1.f}, {book_key(p), 48, 56, 5, 2.f}, {book_key(p), 48, 56, 0, 9.f}}))));
  auto c = b.candidates(p);
  CHECK_EQ(int(c.size()), 2);
  std::map<std::string, float> got;
  for (auto& x : c) got[move_to_uci(x.move)] = x.weight;
  CHECK(got.count("a7a8n") && got.count("a7a8q") && !got.count("a7a8"));
}

TEST(Book, TemperatureZeroAlwaysPlaysTheHeaviestMove) {
  Book b;
  CHECK(b.load(write_file("t0.bin", sample_book())));
  Position p;
  std::mt19937_64 rng(5);
  for (int i = 0; i < 50; ++i) CHECK_EQ(move_to_uci(b.pick(p, 0.0, rng)), std::string("e2e4"));
}

TEST(Book, SamplingFollowsTheWeightsAtTemperatureOne) {
  Book b;
  CHECK(b.load(write_file("t1.bin", sample_book())));
  Position p;
  std::mt19937_64 rng(42);
  int e4 = 0;
  const int n = 4000;
  for (int i = 0; i < n; ++i) e4 += move_to_uci(b.pick(p, 1.0, rng)) == "e2e4";
  const double share = double(e4) / n;  // expected 3/4
  CHECK(share > 0.71 && share < 0.79);
}

TEST(Book, TemperatureShapesTheDistribution) {
  Book b;
  CHECK(b.load(write_file("temp.bin", sample_book())));
  Position p;
  auto share_at = [&](double t) {
    std::mt19937_64 rng(7);
    int e4 = 0;
    for (int i = 0; i < 3000; ++i) e4 += move_to_uci(b.pick(p, t, rng)) == "e2e4";
    return double(e4) / 3000;
  };
  CHECK(share_at(0.1) > 0.99);    // sharpened: essentially always the favourite
  CHECK(share_at(100.0) < 0.56);  // flattened: close to a coin flip
  CHECK(share_at(100.0) > 0.44);
}

TEST(Book, SameSeedGivesTheSameChoices) {
  Book b;
  CHECK(b.load(write_file("seed.bin", sample_book())));
  Position p;
  std::mt19937_64 r1(9), r2(9), r3(10);
  std::string s1, s2, s3;
  for (int i = 0; i < 40; ++i) {
    s1 += move_to_uci(b.pick(p, 1.0, r1));
    s2 += move_to_uci(b.pick(p, 1.0, r2));
    s3 += move_to_uci(b.pick(p, 1.0, r3));
  }
  CHECK_EQ(s1, s2);
  CHECK(s1 != s3);
}

// ---- UCI integration -------------------------------------------------------------------------------------

TEST(BookUci, PlaysBookMovesOnlyWhenEnabled) {
  const std::string path = write_file("uci.bin", sample_book());
  const std::string setup = "setoption name BookFile value " + path + "\nsetoption name BookTemperature value 0\nposition startpos\n";
  std::string off = session(setup + "go depth 2\n");
  CHECK(has(off, "loaded book") && !has(off, "book move"));  // OwnBook defaults to off
  std::string on = session("setoption name OwnBook value true\n" + setup + "go depth 2\n");
  CHECK(has(on, "info string book move e2e4"));
  CHECK(has(on, "bestmove e2e4"));
}

TEST(BookUci, FollowsTheLineAndFallsBackToSearchOutOfBook) {
  const std::string path = write_file("uci2.bin", sample_book());
  std::string base = "setoption name OwnBook value true\nsetoption name BookFile value " + path +
                     "\nsetoption name BookTemperature value 0\n";
  std::string in_book = session(base + "position startpos moves e2e4\ngo depth 2\n");
  CHECK(has(in_book, "book move"));
  std::string out_of_book = session(base + "position startpos moves e2e4 c7c5\ngo depth 2\n");
  CHECK(!has(out_of_book, "book move"));
  CHECK(has(out_of_book, "info depth 1"));  // fell back to a real search
  CHECK(has(out_of_book, "bestmove "));
}

TEST(BookUci, BookMaxPlyLimitsTheBook) {
  const std::string path = write_file("uci3.bin", sample_book());
  std::string base = "setoption name OwnBook value true\nsetoption name BookFile value " + path + "\n";
  CHECK(!has(session(base + "setoption name BookMaxPly value 0\nposition startpos\ngo depth 2\n"), "book move"));
  CHECK(has(session(base + "setoption name BookMaxPly value 1\nposition startpos\ngo depth 2\n"), "book move"));
  // after 1.e4 we are at ply 1, so a limit of 1 switches the book off
  CHECK(!has(session(base + "setoption name BookMaxPly value 1\nposition startpos moves e2e4\ngo depth 2\n"), "book move"));
}

TEST(BookUci, InfiniteAnalysisIgnoresTheBook) {
  const std::string path = write_file("uci4.bin", sample_book());
  std::string out = session("setoption name OwnBook value true\nsetoption name BookFile value " + path +
                            "\nposition startpos\ngo infinite\nstop\n");
  CHECK(!has(out, "book move"));
  CHECK(has(out, "bestmove "));
}

TEST(BookUci, ReportsBadBookFilesAndKeepsWorking) {
  std::string out = session("setoption name BookFile value /no/such/book.bin\nisready\n");
  CHECK(has(out, "BookFile error"));
  CHECK(has(out, "readyok"));
}

TEST(BookUci, BookKeyAndBookMovesDebugCommands) {
  const std::string path = write_file("uci5.bin", sample_book());
  std::string out = session("setoption name BookFile value " + path + "\nposition startpos\nbookkey\nbookmoves\n");
  CHECK(has(out, "bookkey 7bd6409c02270343"));
  CHECK(has(out, "e2e4:3"));
  CHECK(has(out, "d2d4:1"));
}

TEST(BookUci, ClearingTheBookFileDisablesIt) {
  const std::string path = write_file("uci6.bin", sample_book());
  std::string out = session("setoption name OwnBook value true\nsetoption name BookFile value " + path +
                            "\nsetoption name BookFile value\nposition startpos\ngo depth 2\n");
  CHECK(!has(out, "book move"));
}
