#include <iostream>

#include "board/bitboard.h"
#include "uci/uci.h"

int main() {
  chess::init_bitboards();
  chess::Uci uci(std::cin, std::cout);
  uci.run();
  return 0;
}
