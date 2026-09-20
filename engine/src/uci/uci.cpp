#include "uci.h"

#include <algorithm>
#include <chrono>

#include "../eval/eval.h"
#include "../movegen/movegen.h"

namespace chess {

namespace {
constexpr int MOVE_OVERHEAD_MS = 20;  // safety margin for GUI/pipe latency
}

std::string format_score(int score) {
  if (is_mate_score(score)) {
    int moves = (MATE - std::abs(score) + 1) / 2;
    return "mate " + std::to_string(score > 0 ? moves : -moves);
  }
  return "cp " + std::to_string(score);
}

Uci::Uci(std::istream& in, std::ostream& out) : in_(in), out_(out) {}

Uci::~Uci() { stop_and_join(); }

void Uci::send(const std::string& line) {
  std::lock_guard<std::mutex> lock(out_mutex_);
  out_ << line << std::endl;  // flush every line: GUIs read line by line
}

Limits Uci::make_limits(const GoParams& go, Color stm) {
  Limits lim;
  lim.depth = go.depth;
  lim.nodes = go.nodes;
  lim.infinite = go.infinite;
  if (go.movetime > 0) {
    lim.hard_ms = lim.soft_ms = std::max(1, go.movetime - MOVE_OVERHEAD_MS);
    return lim;
  }
  const int my_time = stm == WHITE ? go.wtime : go.btime;
  const int inc = stm == WHITE ? go.winc : go.binc;
  if (my_time >= 0 && !go.infinite && go.depth == 0) {
    const int moves_left = go.movestogo > 0 ? go.movestogo + 1 : 30;
    int64_t alloc = my_time / moves_left + inc * 3 / 4;
    alloc = std::min<int64_t>(alloc, my_time / 2);
    lim.soft_ms = std::max<int64_t>(1, alloc);
    lim.hard_ms = std::max<int64_t>(1, std::min<int64_t>(alloc * 3, my_time - MOVE_OVERHEAD_MS));
  }
  return lim;
}

void Uci::run() {
  std::string line;
  while (std::getline(in_, line)) {
    if (!handle(line)) return;
  }
  // End of input: let a finite search finish and report; abort an infinite one.
  if (infinite_running_) stop_.store(true);
  join_search();
}

void Uci::join_search() {
  if (search_thread_.joinable()) search_thread_.join();
}

void Uci::stop_and_join() {
  stop_.store(true);
  join_search();
}

bool Uci::handle(const std::string& line) {
  std::istringstream is(line);
  std::string cmd;
  is >> cmd;
  if (cmd.empty()) return true;

  if (cmd == "uci") {
    send("id name chessme 0.1");
    send("id author chessme contributors");
    send("option name Hash type spin default 16 min 1 max 4096");
    send("option name Clear Hash type button");
    send("option name MultiPV type spin default 1 min 1 max 64");
    send("option name EvalFile type string default <empty>");
    send("option name OwnBook type check default false");
    send("option name BookFile type string default <empty>");
    send("option name BookMaxPly type spin default 30 min 0 max 400");
    send("option name BookTemperature type spin default 100 min 0 max 1000");
    send("option name BookSeed type spin default 0 min 0 max 2147483647");
    send("option name MeNetFile type string default <empty>");
    send("option name MeRating type spin default 1700 min 400 max 3000");
    send("option name MeOppRating type spin default 0 min 0 max 3000");
    send("option name MePlatform type spin default 0 min 0 max 1");
    send("uciok");
  } else if (cmd == "isready") {
    send("readyok");
  } else if (cmd == "ucinewgame") {
    stop_and_join();
    searcher_.clear();
    pos_.set_fen(Position::START_FEN);
  } else if (cmd == "setoption") {
    stop_and_join();
    cmd_setoption(is);
  } else if (cmd == "position") {
    stop_and_join();
    cmd_position(is);
  } else if (cmd == "go") {
    stop_and_join();
    cmd_go(is);
  } else if (cmd == "stop") {
    stop_.store(true);
    join_search();
  } else if (cmd == "quit") {
    stop_and_join();
    return false;
  } else if (cmd == "d") {
    send("Fen: " + pos_.fen());
  } else if (cmd == "eval") {
    send("eval cp " + std::to_string(evaluate(pos_)) + " (side to move)");
  } else if (cmd == "menet") {
    if (!menet_.loaded()) {
      send("menet unavailable");
    } else {
      std::ostringstream os;
      os << "menet";
      for (const auto& [m, p] : menet_.policy(pos_, me_rating_, me_opp_rating_ ? me_opp_rating_ : me_rating_, me_platform_))
        os << ' ' << move_to_uci(m) << ':' << p;
      send(os.str());
    }
  } else if (cmd == "bookkey") {
    std::ostringstream os;
    os << "bookkey " << std::hex << book_key(pos_);
    send(os.str());
  } else if (cmd == "bookmoves") {
    std::ostringstream os;
    os << "bookmoves";
    for (const auto& c : book_.candidates(pos_)) os << ' ' << move_to_uci(c.move) << ':' << c.weight;
    send(os.str());
  } else if (cmd == "perft") {
    int depth = 1;
    is >> depth;
    std::function<uint64_t(int)> perft = [&](int d) -> uint64_t {
      if (d == 0) return 1;
      MoveList list;
      generate_legal(pos_, list);
      if (d == 1) return uint64_t(list.count);
      uint64_t n = 0;
      for (Move m : list) {
        pos_.make_move(m);
        n += perft(d - 1);
        pos_.unmake_move(m);
      }
      return n;
    };
    send("nodes " + std::to_string(perft(depth)));
  }
  // Unknown commands are ignored, as the UCI spec requires.
  return true;
}

void Uci::cmd_setoption(std::istringstream& is) {
  std::string tok, name, value;
  is >> tok;  // "name"
  while (is >> tok && tok != "value") name += (name.empty() ? "" : " ") + tok;
  while (is >> tok) value += (value.empty() ? "" : " ") + tok;
  if (name == "Hash") {
    int mb = std::atoi(value.c_str());
    if (mb >= 1 && mb <= 4096) searcher_.set_hash_mb(size_t(mb));
  } else if (name == "Clear Hash") {
    searcher_.clear();
  } else if (name == "MultiPV") {
    multipv_ = std::max(1, std::min(64, std::atoi(value.c_str())));
  } else if (name == "OwnBook") {
    own_book_ = value == "true";
  } else if (name == "BookFile") {
    if (value.empty() || value == "<empty>") {
      book_.clear();
    } else {
      Book loaded;
      std::string err;
      if (loaded.load(value, &err)) {
        book_ = std::move(loaded);
        send("info string loaded book " + value + " (" + std::to_string(book_.size()) + " entries)");
      } else {
        send("info string BookFile error: " + err);
      }
    }
  } else if (name == "MeNetFile") {
    if (value.empty() || value == "<empty>") {
      menet_ = MeNet();
    } else {
      MeNet loaded;
      std::string err;
      if (loaded.load(value, &err)) {
        menet_ = std::move(loaded);
        send("info string loaded me-network " + value + " (" + std::to_string(menet_.blocks()) + " blocks, " +
             std::to_string(menet_.channels()) + " channels)");
      } else {
        send("info string MeNetFile error: " + err);
      }
    }
  } else if (name == "MeRating") {
    me_rating_ = std::atoi(value.c_str());
  } else if (name == "MeOppRating") {
    me_opp_rating_ = std::atoi(value.c_str());
  } else if (name == "MePlatform") {
    me_platform_ = std::atoi(value.c_str());
  } else if (name == "BookMaxPly") {
    book_max_ply_ = std::max(0, std::atoi(value.c_str()));
  } else if (name == "BookTemperature") {
    book_temperature_ = std::max(0, std::atoi(value.c_str()));
  } else if (name == "BookSeed") {
    const long seed = std::atol(value.c_str());
    book_rng_.seed(seed > 0 ? uint64_t(seed) : uint64_t(std::random_device{}()));
  } else if (name == "EvalFile") {
    if (value.empty() || value == "<empty>") {
      reset_params();
      searcher_.clear();  // cached scores came from the old parameters
    } else {
      EvalParams loaded;
      std::string err;
      if (load_params(value, loaded, &err)) {
        set_params(loaded);
        searcher_.clear();
        send("info string loaded evaluation parameters from " + value);
      } else {
        send("info string EvalFile error: " + err);
      }
    }
  }
}

void Uci::cmd_position(std::istringstream& is) {
  std::string tok;
  is >> tok;
  Position p;
  if (tok == "startpos") {
    p.set_fen(Position::START_FEN);
    is >> tok;  // "moves" or nothing
  } else if (tok == "fen") {
    std::string fen;
    while (is >> tok && tok != "moves") fen += (fen.empty() ? "" : " ") + tok;
    if (!p.set_fen(fen)) return;  // malformed FEN: keep the previous position
  } else {
    return;
  }
  if (tok == "moves") {
    while (is >> tok) {
      Move m = parse_uci_move(p, tok);
      if (m.is_null()) break;  // illegal move: stop applying, keep what we have
      p.make_move(m);
    }
  }
  pos_ = p;
}

bool Uci::try_book_move() {
  if (!own_book_ || book_.empty()) return false;
  const int ply = (pos_.fullmove_number() - 1) * 2 + (pos_.side_to_move() == BLACK ? 1 : 0);
  if (ply >= book_max_ply_) return false;
  Move m = book_.pick(pos_, book_temperature_ / 100.0, book_rng_);
  if (m.is_null()) return false;
  send("info string book move " + move_to_uci(m));
  send("bestmove " + move_to_uci(m));
  return true;
}

void Uci::cmd_go(std::istringstream& is) {
  GoParams go;
  std::string tok;
  while (is >> tok) {
    if (tok == "depth") is >> go.depth;
    else if (tok == "nodes") is >> go.nodes;
    else if (tok == "movetime") is >> go.movetime;
    else if (tok == "wtime") is >> go.wtime;
    else if (tok == "btime") is >> go.btime;
    else if (tok == "winc") is >> go.winc;
    else if (tok == "binc") is >> go.binc;
    else if (tok == "movestogo") is >> go.movestogo;
    else if (tok == "infinite") go.infinite = true;
  }
  // A bare "go" means: think forever.
  if (!go.depth && !go.nodes && !go.movetime && go.wtime < 0 && go.btime < 0) go.infinite = true;

  if (!go.infinite && try_book_move()) return;

  Limits limits = make_limits(go, pos_.side_to_move());
  limits.multipv = multipv_;
  infinite_running_ = limits.infinite;
  stop_.store(false);
  Position snapshot = pos_;  // the search thread works on its own copy
  search_thread_ = std::thread([this, snapshot, limits]() mutable {
    const int multipv = limits.multipv;
    SearchResult r = searcher_.search(snapshot, limits, stop_, [this, multipv](const SearchInfo& info) {
      std::ostringstream os;
      os << "info depth " << info.depth;
      if (multipv > 1) os << " multipv " << info.multipv;
      os << " score " << format_score(info.score) << " nodes " << info.nodes
         << " nps " << (info.time_ms > 0 ? info.nodes * 1000 / uint64_t(info.time_ms) : info.nodes) << " time "
         << info.time_ms << " pv";
      for (Move m : info.pv) os << ' ' << move_to_uci(m);
      send(os.str());
    });
    // An infinite search must not report until the GUI says "stop".
    while (limits.infinite && !stop_.load()) std::this_thread::sleep_for(std::chrono::milliseconds(1));
    send("bestmove " + move_to_uci(r.best_move));
  });
}

}  // namespace chess
