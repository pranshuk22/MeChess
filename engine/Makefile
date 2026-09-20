# Fallback build without CMake.
#   make            build engine, perft, unit tests into build/
#   make test       run unit tests + perft suite (fast, a few seconds)
#   make test-verify  perft suite with hash/unmake verification at every node (~1 min)
#   make test-deep  also run the deep perft suite
CXX ?= clang++
CXXFLAGS ?= -std=c++17 -O3 -Wall -Wextra -pthread
CORE = src/board/bitboard.cpp src/board/position.cpp src/movegen/movegen.cpp src/eval/eval.cpp src/eval/params_io.cpp src/tune/tuner.cpp src/book/book.cpp src/net/menet.cpp src/search/search.cpp src/uci/uci.cpp
HDRS = $(wildcard src/*/*.h)
TESTS = $(wildcard tests/test_*.cpp)

all: build/chessme-engine build/perft build/texel build/test_unit

build/chessme-engine: $(CORE) src/main.cpp $(HDRS)
	@mkdir -p build
	$(CXX) $(CXXFLAGS) $(CORE) src/main.cpp -o $@

build/perft: $(CORE) tools/perft.cpp $(HDRS)
	@mkdir -p build
	$(CXX) $(CXXFLAGS) $(CORE) tools/perft.cpp -o $@

build/texel: $(CORE) tools/texel.cpp $(HDRS)
	@mkdir -p build
	$(CXX) $(CXXFLAGS) $(CORE) tools/texel.cpp -o $@

build/test_unit: $(CORE) $(TESTS) tests/test_framework.h $(HDRS)
	@mkdir -p build
	$(CXX) $(CXXFLAGS) $(CORE) $(TESTS) -o $@

test: all
	./build/test_unit
	./build/perft --suite

# Same suite, but checks the incremental hash and make/unmake at every node (slow, ~1 min).
test-verify: all
	./build/perft --suite --verify

test-deep: all
	./build/perft --suite --deep

clean:
	rm -rf build
.PHONY: all test test-verify test-deep clean
