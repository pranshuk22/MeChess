#include "menet.h"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <fstream>

#include "../movegen/movegen.h"

namespace chess {

int me_move_index(Move m, Color stm) {
  int f = m.from(), t = m.to();
  if (stm == BLACK) f ^= 56, t ^= 56;
  if (m.is_promotion() && m.promotion_type() != QUEEN) {
    const int kind = int(m.promotion_type()) - int(KNIGHT);  // N=0, B=1, R=2
    return 4096 + kind * 24 + (f & 7) * 3 + ((t & 7) - (f & 7) + 1);
  }
  return f * 64 + t;
}

void me_build_planes(const Position& pos, int mover_rating, int opp_rating, int platform, float* out) {
  std::memset(out, 0, sizeof(float) * ME_PLANES * 64);
  const Color us = pos.side_to_move(), them = ~us;
  auto canon = [&](Square s) { return us == WHITE ? s : (s ^ 56); };
  for (int pt = PAWN; pt <= KING; ++pt) {
    for (Bitboard b = pos.pieces(us, PieceType(pt)); b;) out[(pt - 1) * 64 + canon(pop_lsb(b))] = 1.f;
    for (Bitboard b = pos.pieces(them, PieceType(pt)); b;) out[(6 + pt - 1) * 64 + canon(pop_lsb(b))] = 1.f;
  }
  const uint8_t cr = pos.castling();
  const bool bits[4] = {
      bool(cr & (us == WHITE ? WHITE_OO : BLACK_OO)), bool(cr & (us == WHITE ? WHITE_OOO : BLACK_OOO)),
      bool(cr & (them == WHITE ? WHITE_OO : BLACK_OO)), bool(cr & (them == WHITE ? WHITE_OOO : BLACK_OOO))};
  for (int i = 0; i < 4; ++i)
    if (bits[i]) std::fill(out + (12 + i) * 64, out + (13 + i) * 64, 1.f);
  // En passant is marked only if a pawn of the mover attacks the target square (see chessme/model/encoding.py).
  if (pos.ep_square() != SQ_NONE && (PawnAttacks[them][pos.ep_square()] & pos.pieces(us, PAWN)))
    out[16 * 64 + canon(pos.ep_square())] = 1.f;
  std::fill(out + 17 * 64, out + 18 * 64, (float(mover_rating) - 1700.f) / 500.f);
  std::fill(out + 18 * 64, out + 19 * 64, (float(opp_rating) - 1700.f) / 500.f);
  std::fill(out + 19 * 64, out + 20 * 64, float(platform));
}

namespace {

constexpr int PAD = 10, PAD_AREA = PAD * PAD;

// Activations live in zero-padded 10x10 planes so a 3x3 convolution needs no bounds checks.
inline int at(int y, int x) { return (y + 1) * PAD + (x + 1); }

// out = conv3x3(in, w) + b for `cin` padded input planes; output planes get a zero border.
void conv3x3(const float* in, int cin, const float* w, const float* b, int cout, float* out) {
  for (int oc = 0; oc < cout; ++oc) {
    float* o = out + oc * PAD_AREA;
    std::fill(o, o + PAD_AREA, 0.f);
    for (int y = 0; y < 8; ++y)
      for (int x = 0; x < 8; ++x) o[at(y, x)] = b[oc];
    for (int ic = 0; ic < cin; ++ic) {
      const float* src = in + ic * PAD_AREA;
      const float* k = w + (size_t(oc) * cin + ic) * 9;
      for (int dy = 0; dy < 3; ++dy)
        for (int dx = 0; dx < 3; ++dx) {
          const float wt = k[dy * 3 + dx];
          for (int y = 0; y < 8; ++y) {
            const float* s = src + (y + dy) * PAD + dx;
            float* d = o + at(y, 0);
            for (int x = 0; x < 8; ++x) d[x] += wt * s[x];
          }
        }
    }
  }
}

void relu(float* a, int planes) {
  for (int i = 0; i < planes * PAD_AREA; ++i) a[i] = a[i] > 0.f ? a[i] : 0.f;  // borders stay 0
}

bool read_floats(std::ifstream& f, std::vector<float>& v, size_t n) {
  v.resize(n);
  f.read(reinterpret_cast<char*>(v.data()), std::streamsize(n * sizeof(float)));
  return bool(f);
}

}  // namespace

bool MeNet::load(const std::string& path, std::string* error) {
  auto fail = [&](const std::string& msg) {
    if (error) *error = msg;
    return false;
  };
  std::ifstream f(path, std::ios::binary);
  if (!f) return fail("cannot open " + path);
  char magic[4];
  uint32_t hdr[4];
  f.read(magic, 4);
  f.read(reinterpret_cast<char*>(hdr), sizeof(hdr));
  if (!f || std::memcmp(magic, "CMNN", 4) != 0) return fail("not a chessme network file (bad magic)");
  if (hdr[0] != 1) return fail("unsupported network version " + std::to_string(hdr[0]));
  const int blocks = int(hdr[1]), channels = int(hdr[2]), dim = int(hdr[3]);
  if (blocks < 1 || blocks > 64 || channels < 1 || channels > 1024 || dim < 1 || dim > 256) return fail("implausible network dimensions");

  MeNet n;
  n.blocks_ = blocks, n.channels_ = channels, n.dim_ = dim;
  const size_t C = size_t(channels);
  bool ok = read_floats(f, n.stem_.w, C * ME_PLANES * 9) && read_floats(f, n.stem_.b, C);
  n.c1_.resize(blocks);
  n.c2_.resize(blocks);
  for (int i = 0; ok && i < blocks; ++i)
    ok = read_floats(f, n.c1_[i].w, C * C * 9) && read_floats(f, n.c1_[i].b, C) && read_floats(f, n.c2_[i].w, C * C * 9) &&
         read_floats(f, n.c2_[i].b, C);
  ok = ok && read_floats(f, n.qk_w_, 2 * size_t(dim) * C) && read_floats(f, n.qk_b_, 2 * size_t(dim)) &&
       read_floats(f, n.bias_, 4096) && read_floats(f, n.under_w_, size_t(ME_POLICY - 4096) * C * 8) &&
       read_floats(f, n.under_b_, ME_POLICY - 4096);
  if (!ok) return fail("network file is truncated");
  if (f.peek() != std::char_traits<char>::eof()) return fail("network file has trailing bytes");
  for (const auto* v : {&n.stem_.w, &n.qk_w_, &n.bias_, &n.under_w_})
    for (float x : *v)
      if (!std::isfinite(x)) return fail("network file contains non-finite weights");
  *this = std::move(n);
  return true;
}

void MeNet::logits(const Position& pos, int mover_rating, int opp_rating, int platform, std::vector<float>& out) const {
  const int C = channels_;
  float in[ME_PLANES * 64];
  me_build_planes(pos, mover_rating, opp_rating, platform, in);

  std::vector<float> padded(size_t(ME_PLANES) * PAD_AREA, 0.f);
  for (int c = 0; c < ME_PLANES; ++c)
    for (int s = 0; s < 64; ++s) padded[c * PAD_AREA + at(s >> 3, s & 7)] = in[c * 64 + s];

  std::vector<float> x(size_t(C) * PAD_AREA), y(size_t(C) * PAD_AREA), z(size_t(C) * PAD_AREA);
  conv3x3(padded.data(), ME_PLANES, stem_.w.data(), stem_.b.data(), C, x.data());
  relu(x.data(), C);
  for (int i = 0; i < blocks_; ++i) {
    conv3x3(x.data(), C, c1_[i].w.data(), c1_[i].b.data(), C, y.data());
    relu(y.data(), C);
    conv3x3(y.data(), C, c2_[i].w.data(), c2_[i].b.data(), C, z.data());
    for (size_t j = 0; j < x.size(); ++j) x[j] = std::max(0.f, x[j] + z[j]);  // residual, then ReLU
  }

  // Policy head: per-square "from" (q) and "to" (k) embeddings, dot product, plus the per-move bias.
  const int D = dim_;
  std::vector<float> q(size_t(D) * 64), k(size_t(D) * 64);
  for (int d = 0; d < 2 * D; ++d) {
    float* dst = (d < D ? q.data() + size_t(d) * 64 : k.data() + size_t(d - D) * 64);
    for (int s = 0; s < 64; ++s) dst[s] = qk_b_[d];
    for (int c = 0; c < C; ++c) {
      const float w = qk_w_[size_t(d) * C + c];
      for (int s = 0; s < 64; ++s) dst[s] += w * x[c * PAD_AREA + at(s >> 3, s & 7)];
    }
  }
  out.assign(ME_POLICY, 0.f);
  const float inv = 1.f / std::sqrt(float(D));
  for (int f2 = 0; f2 < 64; ++f2)
    for (int t = 0; t < 64; ++t) {
      float acc = 0.f;
      for (int d = 0; d < D; ++d) acc += q[size_t(d) * 64 + f2] * k[size_t(d) * 64 + t];
      out[f2 * 64 + t] = acc * inv + bias_[f2 * 64 + t];
    }
  // Under-promotion head: reads the mover's 7th rank (rank index 6), features ordered channel * 8 + file.
  for (int j = 0; j < ME_POLICY - 4096; ++j) {
    float acc = under_b_[j];
    const float* w = under_w_.data() + size_t(j) * C * 8;
    for (int c = 0; c < C; ++c)
      for (int file = 0; file < 8; ++file) acc += w[c * 8 + file] * x[c * PAD_AREA + at(6, file)];
    out[4096 + j] = acc;
  }
}

std::vector<std::pair<Move, float>> MeNet::policy(Position& pos, int mover_rating, int opp_rating, int platform) const {
  std::vector<float> lg;
  logits(pos, mover_rating, opp_rating, platform, lg);
  MoveList legal;
  generate_legal(pos, legal);
  std::vector<std::pair<Move, float>> out;
  float mx = -1e30f;
  for (Move m : legal) mx = std::max(mx, lg[me_move_index(m, pos.side_to_move())]);
  double total = 0;
  for (Move m : legal) {
    const float e = std::exp(lg[me_move_index(m, pos.side_to_move())] - mx);
    out.emplace_back(m, e);
    total += e;
  }
  for (auto& p : out) p.second = float(p.second / total);
  std::sort(out.begin(), out.end(), [](const auto& a, const auto& b) { return a.second > b.second; });
  return out;
}

}  // namespace chess
