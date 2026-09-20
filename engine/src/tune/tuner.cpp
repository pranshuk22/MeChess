#include "tuner.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <fstream>
#include <sstream>

#include "../eval/eval.h"

namespace chess {

std::vector<int> default_frozen() {
  return {P::MAT_MG + PAWN - 1, P::MAT_EG + PAWN - 1, P::MAT_MG + KING - 1, P::MAT_EG + KING - 1};
}

bool TuneData::add(const std::string& fen, double result, double weight) {
  Position p;
  if (!p.set_fen(fen)) return false;
  EvalTrace t;
  trace_eval(p, t);

  // Merge duplicate parameter indices into single (index, coefficient) entries, with the phase blend folded in,
  // so a position's white-point-of-view evaluation is simply sum(coef * param).
  static thread_local std::vector<double> dense(P::COUNT, 0.0);
  static thread_local std::vector<char> seen(P::COUNT, 0);
  std::vector<int> touched;
  auto add_term = [&](int idx, double c) {
    if (!seen[idx]) seen[idx] = 1, touched.push_back(idx);
    dense[idx] += c;
  };
  const double mg_w = double(t.phase) / TOTAL_PHASE, eg_w = double(TOTAL_PHASE - t.phase) / TOTAL_PHASE;
  for (auto [i, c] : t.mg) add_term(i, c * mg_w);
  for (auto [i, c] : t.eg) add_term(i, c * eg_w);
  add_term(P::TEMPO, t.stm_sign);  // tempo goes to the side to move: +1 / -1 from White's point of view

  Pos rec;
  rec.offset = uint32_t(entries_.size());
  for (int idx : touched) {
    if (std::fabs(dense[idx]) > 1e-12) entries_.push_back({uint16_t(idx), float(dense[idx])});
    dense[idx] = 0.0;
    seen[idx] = 0;
  }
  rec.count = uint16_t(entries_.size() - rec.offset);
  rec.result = float(result);
  rec.weight = float(weight);
  pos_.push_back(rec);
  return true;
}

namespace {

inline double sigmoid(double x) { return 1.0 / (1.0 + std::exp(-x)); }
constexpr double LN10_OVER_400 = 2.302585092994046 / 400.0;

}  // namespace

TuneReport tune(const TuneData& d, EvalParams& params, const TuneConfig& cfg) {
  using Entry = TuneData::Entry;
  const size_t n = d.pos_.size();
  TuneReport rep;
  rep.positions = n;
  if (n == 0) return rep;

  std::vector<double> p(params.begin(), params.end()), p0 = p;

  // Deterministic train / validation split.
  std::vector<char> is_val(n, 0);
  const uint32_t threshold = uint32_t(cfg.val_fraction * 1000.0);
  for (size_t i = 0; i < n; ++i) is_val[i] = ((uint32_t(i) * 2654435761u) >> 8) % 1000 < threshold;
  std::vector<size_t> train, val;
  for (size_t i = 0; i < n; ++i) (is_val[i] ? val : train).push_back(i);
  if (train.empty()) train.swap(val);
  rep.train_positions = train.size();
  rep.val_positions = val.size();

  auto eval_of = [&](size_t i, const std::vector<double>& w) {
    const auto& ps = d.pos_[i];
    double e = 0;
    const Entry* it = d.entries_.data() + ps.offset;
    for (int k = 0; k < ps.count; ++k) e += double(it[k].coef) * w[it[k].idx];
    return e;
  };
  auto weight_sum = [&](const std::vector<size_t>& set) {
    double s = 0;
    for (size_t i : set) s += d.pos_[i].weight;
    return s;
  };
  auto loss_with = [&](const std::vector<size_t>& set, const std::vector<double>& evals_or_empty, double a,
                       const std::vector<double>* w) {
    double l = 0;
    for (size_t j = 0; j < set.size(); ++j) {
      const size_t i = set[j];
      const double e = w ? eval_of(i, *w) : evals_or_empty[j];
      const double diff = d.pos_[i].result - sigmoid(a * e);
      l += d.pos_[i].weight * diff * diff;
    }
    const double ws = weight_sum(set);
    return ws > 0 ? l / ws : 0.0;
  };

  // Fit K (the sigmoid scale) with the starting parameters, by golden-section search on the training loss.
  double k = cfg.k;
  if (k <= 0) {
    std::vector<double> e0(train.size());
    for (size_t j = 0; j < train.size(); ++j) e0[j] = eval_of(train[j], p);
    double lo = 0.02, hi = 6.0;
    const double gr = 0.6180339887498949;
    double c = hi - gr * (hi - lo), dd = lo + gr * (hi - lo);
    double fc = loss_with(train, e0, c * LN10_OVER_400, nullptr), fd = loss_with(train, e0, dd * LN10_OVER_400, nullptr);
    for (int it = 0; it < 60; ++it) {
      if (fc < fd) hi = dd, dd = c, fd = fc, c = hi - gr * (hi - lo), fc = loss_with(train, e0, c * LN10_OVER_400, nullptr);
      else lo = c, c = dd, fc = fd, dd = lo + gr * (hi - lo), fd = loss_with(train, e0, dd * LN10_OVER_400, nullptr);
    }
    k = 0.5 * (lo + hi);
  }
  rep.k = k;
  const double a = k * LN10_OVER_400;

  auto rounded = [&](const std::vector<double>& w) {
    std::vector<double> r(w.size());
    for (size_t i = 0; i < w.size(); ++i) r[i] = std::round(w[i]);
    return r;
  };
  rep.loss_before_train = loss_with(train, {}, a, &p);
  rep.loss_before_val = val.empty() ? rep.loss_before_train : loss_with(val, {}, a, &p);

  std::vector<char> frozen(P::COUNT, 0);
  for (int f : cfg.frozen) frozen[f] = 1;

  std::vector<double> m(P::COUNT, 0.0), v(P::COUNT, 0.0), grad(P::COUNT), best = p;
  const double wsum_train = weight_sum(train);
  double best_val = rep.loss_before_val;
  int since_best = 0;
  const double beta1 = 0.9, beta2 = 0.999, eps = 1e-8;

  for (int epoch = 1; epoch <= cfg.epochs; ++epoch) {
    std::fill(grad.begin(), grad.end(), 0.0);
    for (size_t i : train) {
      const auto& ps = d.pos_[i];
      const double s = sigmoid(a * eval_of(i, p));
      const double g = 2.0 * ps.weight * (s - ps.result) * s * (1.0 - s) * a / wsum_train;
      const Entry* it = d.entries_.data() + ps.offset;
      for (int k2 = 0; k2 < ps.count; ++k2) grad[it[k2].idx] += g * double(it[k2].coef);
    }
    const double lr = cfg.lr * std::max(0.05, 0.5 * (1.0 + std::cos(3.141592653589793 * epoch / cfg.epochs)));
    for (int j = 0; j < P::COUNT; ++j) {
      if (frozen[j]) continue;
      double g = grad[j] + 2.0 * cfg.l2 * (p[j] - p0[j]);
      m[j] = beta1 * m[j] + (1 - beta1) * g;
      v[j] = beta2 * v[j] + (1 - beta2) * g * g;
      const double mh = m[j] / (1 - std::pow(beta1, epoch)), vh = v[j] / (1 - std::pow(beta2, epoch));
      p[j] -= lr * mh / (std::sqrt(vh) + eps);
    }
    rep.epochs_run = epoch;
    if (epoch % 5 == 0 || epoch == cfg.epochs) {
      std::vector<double> r = rounded(p);
      const double vl = loss_with(val.empty() ? train : val, {}, a, &r);
      if (cfg.verbose) std::fprintf(stderr, "epoch %4d  val loss %.6f\n", epoch, vl);
      if (vl < best_val - 1e-9) {
        best_val = vl;
        best = r;
        since_best = 0;
      } else if (++since_best >= cfg.patience) {
        break;
      }
    }
  }

  std::vector<double> final_p = best;
  for (int j = 0; j < P::COUNT; ++j) params[j] = int(final_p[j]);
  std::vector<double> fp(params.begin(), params.end());
  rep.loss_after_train = loss_with(train, {}, a, &fp);
  rep.loss_after_val = val.empty() ? rep.loss_after_train : loss_with(val, {}, a, &fp);
  return rep;
}

size_t load_positions(const std::string& path, TuneData& data, size_t max_positions, std::string* error) {
  std::ifstream f(path);
  if (!f) {
    if (error) *error = "cannot open " + path;
    return 0;
  }
  size_t added = 0;
  std::string line;
  while (std::getline(f, line)) {
    if (line.empty() || line[0] == '#') continue;
    std::vector<std::string> parts;
    std::stringstream ss(line);
    std::string part;
    while (std::getline(ss, part, '|')) {
      const size_t b = part.find_first_not_of(" \t\r"), e = part.find_last_not_of(" \t\r");
      parts.push_back(b == std::string::npos ? "" : part.substr(b, e - b + 1));
    }
    if (parts.size() < 2) continue;
    double result, weight = 1.0;
    try {
      result = std::stod(parts[1]);
      if (parts.size() >= 3) weight = std::stod(parts[2]);
    } catch (...) {
      continue;
    }
    if (result < 0 || result > 1 || weight <= 0) continue;
    if (data.add(parts[0], result, weight)) ++added;
    if (max_positions && added >= max_positions) break;
  }
  return added;
}

}  // namespace chess
