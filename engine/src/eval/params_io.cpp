#include <fstream>
#include <sstream>

#include "params.h"

namespace chess {

std::string format_params(const EvalParams& p) {
  std::ostringstream os;
  for (const ParamGroup& g : param_groups()) {
    os << g.name;
    for (int i = 0; i < g.count; ++i) os << ' ' << p[g.offset + i];
    os << '\n';
  }
  return os.str();
}

bool parse_params(const std::string& text, EvalParams& out, std::string* error) {
  EvalParams p = default_params();
  std::istringstream in(text);
  std::string line;
  int lineno = 0;
  auto fail = [&](const std::string& msg) {
    if (error) *error = "line " + std::to_string(lineno) + ": " + msg;
    return false;
  };
  while (std::getline(in, line)) {
    ++lineno;
    if (line.empty() || line[0] == '#') continue;
    std::istringstream ls(line);
    std::string name;
    ls >> name;
    const ParamGroup* group = nullptr;
    for (const ParamGroup& g : param_groups())
      if (name == g.name) group = &g;
    if (!group) return fail("unknown parameter group '" + name + "'");
    std::vector<int> vals;
    int v;
    while (ls >> v) vals.push_back(v);
    if (!ls.eof()) return fail("non-integer value in '" + name + "'");
    if (int(vals.size()) != group->count)
      return fail("'" + name + "' needs " + std::to_string(group->count) + " values, got " + std::to_string(vals.size()));
    for (int i = 0; i < group->count; ++i) p[group->offset + i] = vals[i];
  }
  out = p;
  return true;
}

bool load_params(const std::string& path, EvalParams& out, std::string* error) {
  std::ifstream f(path);
  if (!f) {
    if (error) *error = "cannot open " + path;
    return false;
  }
  std::stringstream ss;
  ss << f.rdbuf();
  return parse_params(ss.str(), out, error);
}

bool save_params(const std::string& path, const EvalParams& p) {
  std::ofstream f(path);
  if (!f) return false;
  f << "# chessme evaluation parameters (centipawns)\n" << format_params(p);
  return bool(f);
}

}  // namespace chess
