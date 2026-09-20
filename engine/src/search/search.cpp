#include "search.h"

#include <algorithm>
#include <chrono>
#include <cstring>

#include "../eval/eval.h"
#include "../movegen/movegen.h"

namespace chess {

namespace {

enum Bound : uint8_t { BOUND_NONE = 0, BOUND_UPPER = 1, BOUND_LOWER = 2, BOUND_EXACT = 3 };

int score_to_tt(int s, int ply) {
  if (s >= MATE_IN_MAX) return s + ply;
  if (s <= -MATE_IN_MAX) return s - ply;
  return s;
}
int score_from_tt(int s, int ply) {
  if (s >= MATE_IN_MAX) return s - ply;
  if (s <= -MATE_IN_MAX) return s + ply;
  return s;
}

int64_t now_ns() {
  return std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch())
      .count();
}

constexpr int HISTORY_MAX = 16384;

}  // namespace

Searcher::Searcher(size_t hash_mb) {
  set_hash_mb(hash_mb);
  clear();
}

void Searcher::set_hash_mb(size_t mb) {
  size_t entries = std::max<size_t>(1, mb * 1024 * 1024 / sizeof(TTEntry));
  size_t pow2 = 1;
  while (pow2 * 2 <= entries) pow2 *= 2;  // round down to a power of two
  tt_.assign(pow2, TTEntry{});
  tt_mask_ = pow2 - 1;
}

void Searcher::clear() {
  std::fill(tt_.begin(), tt_.end(), TTEntry{});
  std::memset(killers_, 0, sizeof(killers_));
  std::memset(history_, 0, sizeof(history_));
}

bool Searcher::is_excluded(Move m) const {
  for (int i = 0; i < n_excluded_; ++i)
    if (excluded_[i] == m) return true;
  return false;
}

int64_t Searcher::elapsed_ms() const { return (now_ns() - start_ns_) / 1000000; }

bool Searcher::out_of_time() {
  if (stop_->load(std::memory_order_relaxed)) return true;
  if (limits_.nodes && nodes_ >= limits_.nodes) return true;
  if (limits_.hard_ms && elapsed_ms() >= limits_.hard_ms) return true;
  return false;
}

// Move ordering: TT move, then promotions and captures (MVV-LVA), then killers, then history.
void Searcher::score_moves(const MoveList& list, int* scores, Move tt_move, int ply) const {
  const Position& pos = *pos_;
  const Color us = pos.side_to_move();
  for (int i = 0; i < list.count; ++i) {
    Move m = list.moves[i];
    int s;
    if (m == tt_move) {
      s = 1 << 30;
    } else if (m.is_promotion()) {
      s = 200000 + (m.is_capture() ? 1000 : 0) + int(m.promotion_type()) * 10;
    } else if (m.is_capture()) {
      PieceType victim = m.flags() == EP_CAPTURE ? PAWN : type_of(pos.piece_on(m.to()));
      PieceType attacker = type_of(pos.piece_on(m.from()));
      s = 100000 + 10 * int(victim) - int(attacker);
    } else if (m == killers_[ply][0]) {
      s = 90000;
    } else if (m == killers_[ply][1]) {
      s = 89000;
    } else {
      s = history_[us][m.from()][m.to()];
    }
    scores[i] = s;
  }
}

namespace {
// Selection sort step: move the best-scored remaining move to index `i`.
inline void pick_move(MoveList& list, int* scores, int i) {
  int best = i;
  for (int j = i + 1; j < list.count; ++j)
    if (scores[j] > scores[best]) best = j;
  std::swap(list.moves[i], list.moves[best]);
  std::swap(scores[i], scores[best]);
}
}  // namespace

int Searcher::qsearch(int alpha, int beta, int ply) {
  if ((++nodes_ & 2047) == 0 && out_of_time()) stopped_ = true;
  if (stopped_) return 0;
  Position& pos = *pos_;
  pv_len_[ply] = ply;

  if (pos.is_repetition() || pos.halfmove_clock() >= 100 || pos.insufficient_material()) return 0;
  if (ply >= MAX_PLY - 1) return evaluate(pos);

  const bool in_check = pos.in_check();
  int best = -INF;
  int stand = 0;
  if (!in_check) {
    stand = evaluate(pos);
    if (stand >= beta) return stand;
    if (stand > alpha) alpha = stand;
    best = stand;
  }

  MoveList list;
  generate_pseudo_legal(pos, list);
  int scores[256];
  score_moves(list, scores, Move(), ply);

  int legal = 0;
  for (int i = 0; i < list.count; ++i) {
    pick_move(list, scores, i);
    Move m = list.moves[i];
    if (!in_check) {
      if (!m.is_capture() && !m.is_promotion()) continue;
      // Delta pruning: even winning the victim outright can't lift us to alpha.
      if (!m.is_promotion()) {
        PieceType victim = m.flags() == EP_CAPTURE ? PAWN : type_of(pos.piece_on(m.to()));
        if (stand + PIECE_VALUE[victim] + 200 < alpha) continue;
      }
    }
    pos.make_move(m);
    if (!mover_is_safe(pos)) {
      pos.unmake_move(m);
      continue;
    }
    ++legal;
    int score = -qsearch(-beta, -alpha, ply + 1);
    pos.unmake_move(m);
    if (stopped_) return 0;
    if (score > best) {
      best = score;
      if (score > alpha) {
        alpha = score;
        if (alpha >= beta) break;
      }
    }
  }
  if (in_check && legal == 0) return -MATE + ply;
  return best;
}

int Searcher::negamax(int depth, int alpha, int beta, int ply, bool allow_null) {
  Position& pos = *pos_;
  pv_len_[ply] = ply;
  const bool root = ply == 0;
  const bool pv_node = beta - alpha > 1;
  const bool in_check = pos.in_check();

  if (depth <= 0 && !in_check) return qsearch(alpha, beta, ply);

  if ((++nodes_ & 2047) == 0 && out_of_time()) stopped_ = true;
  if (stopped_) return 0;

  if (!root) {
    if (pos.is_repetition() || pos.halfmove_clock() >= 100 || pos.insufficient_material()) return 0;
    if (ply >= MAX_PLY - 1) return evaluate(pos);
    // Mate-distance pruning: can't do better than mating now, or worse than being mated now.
    alpha = std::max(alpha, -MATE + ply);
    beta = std::min(beta, MATE - ply - 1);
    if (alpha >= beta) return alpha;
  }

  if (in_check) ++depth;  // check extension
  if (depth <= 0) depth = 1;

  // Transposition table probe.
  const uint64_t key = pos.key();
  TTEntry& slot = tt_[key & tt_mask_];
  Move tt_move;
  if (slot.key == key && slot.bound != BOUND_NONE) {
    tt_move = Move();
    tt_move.v = slot.move;
    if (!root && !pv_node && slot.depth >= depth) {
      int s = score_from_tt(slot.score, ply);
      if (slot.bound == BOUND_EXACT || (slot.bound == BOUND_LOWER && s >= beta) ||
          (slot.bound == BOUND_UPPER && s <= alpha))
        return s;
    }
  }

  const int static_eval = in_check ? -INF : evaluate(pos);
  const Color us = pos.side_to_move();

  if (!pv_node && !in_check && !root) {
    // Reverse futility: static eval is so far above beta that a shallow search won't change that.
    if (depth <= 4 && static_eval - 100 * depth >= beta && beta > -MATE_IN_MAX) return static_eval;

    // Null-move pruning: if passing still beats beta, a real move will too (unless zugzwang-prone).
    if (allow_null && depth >= 3 && static_eval >= beta && pos.has_non_pawn_material(us)) {
      const int R = 3 + depth / 6;
      pos.make_null_move();
      int s = -negamax(depth - 1 - R, -beta, -beta + 1, ply + 1, false);
      pos.unmake_null_move();
      if (stopped_) return 0;
      if (s >= beta) return s >= MATE_IN_MAX ? beta : s;
    }
  }

  MoveList list;
  generate_pseudo_legal(pos, list);
  int scores[256];
  score_moves(list, scores, tt_move, ply);

  const int orig_alpha = alpha;
  int best = -INF;
  Move best_move;
  int legal = 0;
  Move quiets_tried[64];
  int nquiets = 0;

  for (int i = 0; i < list.count; ++i) {
    pick_move(list, scores, i);
    Move m = list.moves[i];
    if (root && n_excluded_ && is_excluded(m)) continue;  // MultiPV: this move is already in an earlier line
    const bool quiet = !m.is_capture() && !m.is_promotion();

    pos.make_move(m);
    if (!mover_is_safe(pos)) {
      pos.unmake_move(m);
      continue;
    }
    ++legal;
    const bool gives_check = pos.in_check();

    // Futility pruning: a quiet move this late and this far below alpha is very unlikely to matter.
    if (!pv_node && !in_check && !gives_check && quiet && depth <= 3 && legal > 1 &&
        static_eval + 150 * depth <= alpha && alpha > -MATE_IN_MAX) {
      pos.unmake_move(m);
      continue;
    }

    const int new_depth = depth - 1;
    int score;
    if (legal == 1) {
      score = -negamax(new_depth, -beta, -alpha, ply + 1, true);
    } else {
      // Late-move reduction for quiet moves late in the ordering, then principal-variation search.
      int r = 0;
      if (depth >= 3 && legal > 3 && quiet && !in_check && !gives_check) {
        r = 1 + (depth >= 6) + (legal > 8);
        if (pv_node) --r;
        r = std::max(0, std::min(r, new_depth));
      }
      score = -negamax(new_depth - r, -alpha - 1, -alpha, ply + 1, true);
      if (score > alpha && r > 0) score = -negamax(new_depth, -alpha - 1, -alpha, ply + 1, true);
      if (score > alpha && score < beta) score = -negamax(new_depth, -beta, -alpha, ply + 1, true);
    }
    pos.unmake_move(m);
    if (stopped_) return 0;

    if (quiet && nquiets < 64) quiets_tried[nquiets++] = m;

    if (score > best) {
      best = score;
      best_move = m;
      if (score > alpha) {
        alpha = score;
        // Triangular PV update.
        pv_[ply][ply] = m;
        for (int j = ply + 1; j < pv_len_[ply + 1]; ++j) pv_[ply][j] = pv_[ply + 1][j];
        pv_len_[ply] = pv_len_[ply + 1] > ply + 1 ? pv_len_[ply + 1] : ply + 1;
        if (alpha >= beta) {
          if (quiet) {
            if (killers_[ply][0] != m) {
              killers_[ply][1] = killers_[ply][0];
              killers_[ply][0] = m;
            }
            const int bonus = std::min(depth * depth, 400);
            for (int q = 0; q < nquiets; ++q) {
              int& h = history_[us][quiets_tried[q].from()][quiets_tried[q].to()];
              int delta = quiets_tried[q] == m ? bonus : -bonus;
              h += delta - h * std::abs(delta) / HISTORY_MAX;  // "gravity": keeps values bounded
            }
          }
          break;
        }
      }
    }
  }

  if (legal == 0) return in_check ? -MATE + ply : 0;

  slot.key = key;
  slot.move = best_move.v;
  slot.score = int16_t(score_to_tt(best, ply));
  slot.depth = int8_t(depth);
  slot.bound = best >= beta ? BOUND_LOWER : (alpha > orig_alpha ? BOUND_EXACT : BOUND_UPPER);
  return best;
}

SearchResult Searcher::search(Position& pos, const Limits& limits, std::atomic<bool>& stop, InfoCallback on_info) {
  pos_ = &pos;
  limits_ = limits;
  stop_ = &stop;
  stopped_ = false;
  nodes_ = 0;
  start_ns_ = now_ns();
  std::memset(killers_, 0, sizeof(killers_));
  std::memset(pv_len_, 0, sizeof(pv_len_));

  SearchResult result;
  MoveList root_moves;
  generate_legal(pos, root_moves);
  if (root_moves.count == 0) {
    result.score = pos.in_check() ? -MATE : 0;
    return result;
  }
  result.best_move = root_moves.moves[0];  // fallback so we always answer with a legal move

  const int max_depth = limits.depth > 0 ? std::min(limits.depth, MAX_PLY - 2) : MAX_PLY - 2;
  const int nlines = std::max(1, std::min({limits.multipv, root_moves.count, 64}));
  int prev_score = 0;

  for (int depth = 1; depth <= max_depth; ++depth) {
    std::vector<RootLine> lines;
    n_excluded_ = 0;
    bool complete = true;
    for (int k = 0; k < nlines; ++k) {
      int alpha = -INF, beta = INF, delta = 30;
      if (k == 0 && depth >= 5) {  // aspiration window around the previous best score
        alpha = std::max(-INF, prev_score - delta);
        beta = std::min(INF, prev_score + delta);
      }
      int score;
      for (;;) {
        score = negamax(depth, alpha, beta, 0, false);
        if (stopped_) break;
        if (score <= alpha) {
          alpha = std::max(-INF, score - delta);
        } else if (score >= beta) {
          beta = std::min(INF, score + delta);
        } else {
          break;
        }
        delta *= 2;
      }
      if (stopped_ || pv_len_[0] == 0) {
        complete = false;
        break;
      }
      RootLine line;
      line.move = pv_[0][0];
      line.score = score;
      line.depth = depth;
      line.pv.assign(pv_[0], pv_[0] + pv_len_[0]);
      lines.push_back(line);
      excluded_[n_excluded_++] = line.move;  // the next line searches the remaining moves
    }
    n_excluded_ = 0;
    if (!complete) break;  // discard the unfinished iteration; keep the last complete one

    // Reductions and pruning make a later line occasionally score above an earlier one (a quiet move searched
    // first in its own line gets full depth). Report the lines best-first, and let the best score decide the move.
    std::stable_sort(lines.begin(), lines.end(), [](const RootLine& a, const RootLine& b) { return a.score > b.score; });
    prev_score = lines[0].score;
    result.lines = lines;
    result.score = lines[0].score;
    result.depth = depth;
    result.pv = lines[0].pv;
    result.best_move = lines[0].move;
    result.nodes = nodes_;

    if (on_info) {
      for (size_t k = 0; k < lines.size(); ++k) {
        SearchInfo info;
        info.multipv = int(k) + 1;
        info.depth = depth;
        info.score = lines[k].score;
        info.nodes = nodes_;
        info.time_ms = elapsed_ms();
        info.pv = lines[k].pv;
        on_info(info);
      }
    }

    if (limits.infinite) continue;
    if (nlines == 1 && limits.depth == 0 && is_mate_score(result.score) && depth >= 2) break;  // mate found
    if (limits.soft_ms && elapsed_ms() * 2 >= limits.soft_ms) break;  // next iteration likely too long
  }
  result.nodes = nodes_;
  return result;
}

}  // namespace chess
