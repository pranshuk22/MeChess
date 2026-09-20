#include "test_framework.h"

#include "../src/board/bitboard.h"

int main(int argc, char** argv) {
  chess::init_bitboards();
  return testing::run_all(argc, argv);
}
