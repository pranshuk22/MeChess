#pragma once
#include <atomic>
#include <cstdint>
#include <functional>
#include <vector>

#include "../board/position.h"

namespace chess {

struct MoveList;

constexpr int MAX_PLY = 128;
constexpr int INF = 32001;
constexpr int MATE = 32000;
constexpr int MATE_IN_MAX = MATE - MAX_PLY;  // scores beyond this are forced mates

struct Limits {
  int depth = 0;         // 0 = no depth limit
  uint64_t nodes = 0;    // 0 = no node limit
  int64_t soft_ms = 0;   // 0 = none; don't start a new iteration after ~half of this
  int64_t hard_ms = 0;   // 0 = none; abort the search at this point
  bool infinite = false; // search until stopped
  int multipv = 1;       // number of best root moves to report (each with its own exact score and line)
};

struct SearchInfo {
  int multipv = 1;  // which line this is (1 = best)
  int depth = 0;
  int score = 0;  // centipawns, or mate score (see is_mate_score)
  uint64_t nodes = 0;
  int64_t time_ms = 0;
  std::vector<Move> pv;
};

// One reported root move: its score is the exact value of the best move that is not in an earlier line.
struct RootLine {
  Move move;
  int score = 0;
  int depth = 0;
  std::vector<Move> pv;
};

struct SearchResult {
  std::vector<RootLine> lines;  // lines[0] is the best move; at most `multipv` entries (fewer if fewer legal moves)
  Move best_move;  // null only if the side to move has no legal move
  int score = 0;
  int depth = 0;
  uint64_t nodes = 0;
  std::vector<Move> pv;
};

inline bool is_mate_score(int s) { return s >= MATE_IN_MAX || s <= -MATE_IN_MAX; }

using InfoCallback = std::function<void(const SearchInfo&)>;

class Searcher {
 public:
  explicit Searcher(size_t hash_mb = 16);
  void set_hash_mb(size_t mb);
  void clear();  // forget the transposition table, killers and history (new game)

  // Searches `pos` (restored before returning). `stop` may be set from another thread.
  SearchResult search(Position& pos, const Limits& limits, std::atomic<bool>& stop, InfoCallback on_info = nullptr);

 private:
  struct TTEntry {
    uint64_t key = 0;
    int16_t score = 0;
    uint16_t move = 0;
    int8_t depth = 0;
    uint8_t bound = 0;  // 0 none, 1 upper, 2 lower, 3 exact
  };

  int negamax(int depth, int alpha, int beta, int ply, bool allow_null);
  int qsearch(int alpha, int beta, int ply);
  bool out_of_time();
  int64_t elapsed_ms() const;
  void score_moves(const MoveList& list, int* scores, Move tt_move, int ply) const;

  std::vector<TTEntry> tt_;
  uint64_t tt_mask_ = 0;

  // per-search state
  Position* pos_ = nullptr;
  Limits limits_;
  std::atomic<bool>* stop_ = nullptr;
  bool stopped_ = false;
  uint64_t nodes_ = 0;
  int64_t start_ns_ = 0;
  Move excluded_[64];  // root moves already reported in an earlier MultiPV line of this iteration
  int n_excluded_ = 0;
  bool is_excluded(Move m) const;
  Move killers_[MAX_PLY][2];
  int history_[COLOR_NB][64][64];
  Move pv_[MAX_PLY][MAX_PLY];
  int pv_len_[MAX_PLY];
};

}  // namespace chess
