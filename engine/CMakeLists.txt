cmake_minimum_required(VERSION 3.16)
project(chessme_engine CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -Wall -Wextra -pthread")
set(CMAKE_CXX_FLAGS_RELEASE "-O3")

add_library(chessme_core
  src/board/bitboard.cpp
  src/board/position.cpp
  src/movegen/movegen.cpp
  src/eval/eval.cpp
  src/eval/params_io.cpp
  src/tune/tuner.cpp
  src/book/book.cpp
  src/net/menet.cpp
  src/search/search.cpp
  src/uci/uci.cpp)
target_include_directories(chessme_core PUBLIC src)

add_executable(chessme-engine src/main.cpp)
target_link_libraries(chessme-engine chessme_core)

add_executable(texel tools/texel.cpp)
target_link_libraries(texel chessme_core)

add_executable(perft tools/perft.cpp)
target_link_libraries(perft chessme_core)

file(GLOB TEST_SOURCES tests/test_*.cpp)
add_executable(test_unit ${TEST_SOURCES})
target_link_libraries(test_unit chessme_core)

enable_testing()
add_test(NAME unit COMMAND test_unit)
add_test(NAME perft_suite COMMAND perft --suite)
add_test(NAME perft_verify COMMAND perft --suite --verify)
