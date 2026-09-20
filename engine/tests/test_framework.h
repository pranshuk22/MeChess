// Minimal dependency-free unit-test harness.
//   TEST(suite, name) { CHECK(cond); CHECK_EQ(a, b); }
// Run:  test_unit [substring-filter]
#pragma once
#include <cstdio>
#include <cstring>
#include <functional>
#include <sstream>
#include <string>
#include <vector>

namespace testing {

struct TestCase {
  const char* suite;
  const char* name;
  std::function<void()> fn;
};

inline std::vector<TestCase>& registry() {
  static std::vector<TestCase> r;
  return r;
}
inline int& failures_in_current() {
  static int n = 0;
  return n;
}

struct Registrar {
  Registrar(const char* suite, const char* name, std::function<void()> fn) {
    registry().push_back({suite, name, std::move(fn)});
  }
};

template <typename A, typename B>
inline void check_eq(const A& a, const B& b, const char* ea, const char* eb, const char* file, int line) {
  if (!(a == b)) {
    std::ostringstream os;
    os << a << " != " << b;
    std::printf("    %s:%d: CHECK_EQ(%s, %s) failed: %s\n", file, line, ea, eb, os.str().c_str());
    ++failures_in_current();
  }
}

inline int run_all(int argc, char** argv) {
  std::string filter = argc > 1 ? argv[1] : "";
  int ran = 0, failed = 0;
  for (auto& t : registry()) {
    std::string full = std::string(t.suite) + "." + t.name;
    if (!filter.empty() && full.find(filter) == std::string::npos) continue;
    failures_in_current() = 0;
    t.fn();
    ++ran;
    if (failures_in_current()) {
      ++failed;
      std::printf("[FAIL] %s\n", full.c_str());
    } else {
      std::printf("[ ok ] %s\n", full.c_str());
    }
  }
  std::printf("\n%d tests, %d failed\n", ran, failed);
  return failed ? 1 : 0;
}

}  // namespace testing

#define TEST(suite, name)                                                   \
  static void test_##suite##_##name();                                      \
  static testing::Registrar reg_##suite##_##name(#suite, #name, test_##suite##_##name); \
  static void test_##suite##_##name()

#define CHECK(cond)                                                              \
  do {                                                                           \
    if (!(cond)) {                                                               \
      std::printf("    %s:%d: CHECK(%s) failed\n", __FILE__, __LINE__, #cond);  \
      ++testing::failures_in_current();                                          \
    }                                                                            \
  } while (0)

#define CHECK_EQ(a, b) testing::check_eq((a), (b), #a, #b, __FILE__, __LINE__)
