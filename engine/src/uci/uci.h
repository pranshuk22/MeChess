#pragma once
#include <atomic>
#include <istream>
#include <mutex>
#include <random>
#include <ostream>
#include <sstream>
#include <string>
#include <thread>

#include "../board/position.h"
#include "../book/book.h"
#include "../net/menet.h"
#include "../search/search.h"

namespace chess {

// UCI protocol front-end. Reads commands from `in`, writes replies to `out` (both injectable for tests).
class Uci {
 public:
  Uci(std::istream& in, std::ostream& out);
  ~Uci();
  void run();  // returns on "quit" or end of input

  // Search budget from `go` parameters (exposed for unit tests).
  struct GoParams {
    int depth = 0, movetime = 0, wtime = -1, btime = -1, winc = 0, binc = 0, movestogo = 0;
    uint64_t nodes = 0;
    bool infinite = false;
  };
  static Limits make_limits(const GoParams& go, Color side_to_move);

 private:
  bool handle(const std::string& line);  // false = quit
  void cmd_position(std::istringstream& is);
  void cmd_go(std::istringstream& is);
  void cmd_setoption(std::istringstream& is);
  void stop_and_join();
  void join_search();
  void send(const std::string& line);

  std::istream& in_;
  std::ostream& out_;
  std::mutex out_mutex_;
  Position pos_;
  Searcher searcher_;
  std::atomic<bool> stop_{false};
  std::thread search_thread_;
  bool infinite_running_ = false;

  // Opening book (off unless OwnBook is enabled and a BookFile is loaded).
  Book book_;
  bool own_book_ = false;
  int book_max_ply_ = 30;       // stop using the book after this many plies from the game start
  int multipv_ = 1;             // MultiPV option: number of lines to report
  int book_temperature_ = 100;  // percent: 100 = the player's own frequencies, 0 = always the most played move
  std::mt19937_64 book_rng_{std::random_device{}()};
  bool try_book_move();

  // The "me" network (loaded with the MeNetFile option). Ratings/platform are the inputs it is conditioned on.
  MeNet menet_;
  int me_rating_ = 1700, me_opp_rating_ = 0, me_platform_ = 0;  // opp 0 = same as me_rating_
};

std::string format_score(int score);  // "cp 34" or "mate -3"

}  // namespace chess
