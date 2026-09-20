#include <cmath>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <sstream>

#include "test_framework.h"
#include "../src/movegen/movegen.h"
#include "../src/net/menet.h"
#include "../src/uci/uci.h"

using namespace chess;

namespace {

Position from(const char* fen) {
  Position p;
  CHECK(p.set_fen(fen));
  return p;
}

// Weight-file builder with the layout of chessme/model/export.py.
struct NetFile {
  int blocks, channels, dim;
  std::vector<float> f;
  size_t off_qk_w, off_qk_b, off_bias, off_under_w, off_under_b;

  NetFile(int b, int c, int d) : blocks(b), channels(c), dim(d) {
    size_t n = size_t(c) * ME_PLANES * 9 + c + size_t(b) * 2 * (size_t(c) * c * 9 + c);
    off_qk_w = n;
    n += 2 * size_t(d) * c;
    off_qk_b = n;
    n += 2 * size_t(d);
    off_bias = n;
    n += 4096;
    off_under_w = n;
    n += size_t(ME_POLICY - 4096) * c * 8;
    off_under_b = n;
    n += ME_POLICY - 4096;
    f.assign(n, 0.f);
  }
  std::string bytes(const char* magic = "CMNN", uint32_t version = 1) const {
    std::string s(magic, 4);
    for (uint32_t v : {version, uint32_t(blocks), uint32_t(channels), uint32_t(dim)})
      for (int i = 0; i < 4; ++i) s.push_back(char((v >> (8 * i)) & 0xff));
    s.append(reinterpret_cast<const char*>(f.data()), f.size() * sizeof(float));
    return s;
  }
};

std::string write_file(const std::string& name, const std::string& bytes) {
  const std::string path = "/tmp/chessme_menet_" + name;
  std::ofstream out(path, std::ios::binary);
  out.write(bytes.data(), std::streamsize(bytes.size()));
  return path;
}

std::string session(const std::string& script) {
  std::istringstream in(script);
  std::ostringstream out;
  Uci uci(in, out);
  uci.run();
  return out.str();
}

}  // namespace

// ---- move indexing (constants pinned to chessme/model/encoding.py) -------------------------------------------------

TEST(MeIndex, OrdinaryMovesUseFromTimesSixtyFourPlusTo) {
  Position p;
  CHECK_EQ(me_move_index(parse_uci_move(p, "e2e4"), WHITE), 12 * 64 + 28);
  CHECK_EQ(me_move_index(parse_uci_move(p, "g1f3"), WHITE), 6 * 64 + 21);
}

TEST(MeIndex, BlackMovesAreMirroredToTheSameSlots) {
  Position w, b = from("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR b KQkq - 0 1");
  CHECK_EQ(me_move_index(parse_uci_move(b, "e7e5"), BLACK), me_move_index(parse_uci_move(w, "e2e4"), WHITE));
  CHECK_EQ(me_move_index(parse_uci_move(b, "g8f6"), BLACK), me_move_index(parse_uci_move(w, "g1f3"), WHITE));
}

TEST(MeIndex, CastlingIsAnOrdinaryKingMove) {
  Position w = from("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1"), b = from("r3k2r/8/8/8/8/8/8/R3K2R b KQkq - 0 1");
  CHECK_EQ(me_move_index(parse_uci_move(w, "e1g1"), WHITE), 4 * 64 + 6);
  CHECK_EQ(me_move_index(parse_uci_move(b, "e8g8"), BLACK), 4 * 64 + 6);
  CHECK_EQ(me_move_index(parse_uci_move(w, "e1c1"), WHITE), 4 * 64 + 2);
}

TEST(MeIndex, PromotionSlots) {
  Position p = from("1n2k3/P7/8/8/8/8/8/4K3 w - - 0 1");
  CHECK_EQ(me_move_index(parse_uci_move(p, "a7a8q"), WHITE), 48 * 64 + 56);   // queen: ordinary slot
  CHECK_EQ(me_move_index(parse_uci_move(p, "a7a8n"), WHITE), 4096 + 0 * 24 + 0 * 3 + 1);
  CHECK_EQ(me_move_index(parse_uci_move(p, "a7a8b"), WHITE), 4096 + 1 * 24 + 0 * 3 + 1);
  CHECK_EQ(me_move_index(parse_uci_move(p, "a7a8r"), WHITE), 4096 + 2 * 24 + 0 * 3 + 1);
  CHECK_EQ(me_move_index(parse_uci_move(p, "a7b8n"), WHITE), 4096 + 0 * 24 + 0 * 3 + 2);  // capture towards the b-file
}

TEST(MeIndex, LegalMovesAlwaysGetDistinctSlotsInRange) {
  const char* fens[] = {Position::START_FEN,
                        "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
                        "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1",
                        "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R b KQkq - 0 1",
                        "1n2k3/P7/8/8/8/8/p7/1N2K3 b - - 0 1"};
  for (const char* f : fens) {
    Position p = from(f);
    MoveList l;
    generate_legal(p, l);
    std::vector<int> idx;
    for (Move m : l) idx.push_back(me_move_index(m, p.side_to_move()));
    std::vector<int> sorted = idx;
    std::sort(sorted.begin(), sorted.end());
    CHECK(std::adjacent_find(sorted.begin(), sorted.end()) == sorted.end());
    CHECK(sorted.front() >= 0 && sorted.back() < ME_POLICY);
  }
}

// ---- input planes -------------------------------------------------------------------------------------------------

namespace {
float sum(const float* planes, int plane) {
  float s = 0;
  for (int i = 0; i < 64; ++i) s += planes[plane * 64 + i];
  return s;
}
}  // namespace

TEST(MePlanes, StartPosition) {
  float pl[ME_PLANES * 64];
  me_build_planes(Position(), 1700, 1700, 0, pl);
  CHECK_EQ(sum(pl, 0), 8.f);     // mover's pawns
  CHECK_EQ(sum(pl, 6), 8.f);     // opponent's pawns
  CHECK_EQ(sum(pl, 5), 1.f);     // mover's king
  CHECK_EQ(pl[5 * 64 + 4], 1.f); // on e1
  CHECK_EQ(pl[11 * 64 + 60], 1.f);  // opponent's king on e8
  for (int c = 12; c < 16; ++c) CHECK_EQ(sum(pl, c), 64.f);  // all castling rights
  CHECK_EQ(sum(pl, 16), 0.f);    // no en passant
  CHECK_EQ(sum(pl, 17), 0.f);    // rating 1700 -> 0
}

TEST(MePlanes, BlackToMoveIsMirrored) {
  Position p;
  p.make_move(parse_uci_move(p, "e2e4"));
  float pl[ME_PLANES * 64];
  me_build_planes(p, 1700, 1700, 0, pl);
  CHECK_EQ(pl[5 * 64 + 4], 1.f);     // mover (Black) king appears on canonical e1
  CHECK_EQ(pl[0 * 64 + 12], 1.f);    // Black's e-pawn is the mover's pawn on canonical e2
  CHECK_EQ(pl[6 * 64 + 36], 1.f);    // White's advanced e-pawn: opponent pawn on canonical e5
  CHECK_EQ(pl[6 * 64 + 28], 0.f);
  CHECK_EQ(sum(pl, 16), 0.f);        // e3 is the en-passant square, but no Black pawn can capture on it
}

TEST(MePlanes, EnPassantIsMarkedOnlyWhenACaptureIsPossible) {
  float pl[ME_PLANES * 64];
  // White pawn on e5 can capture the f5 pawn that just double-pushed: target f6
  me_build_planes(from("rnbqkbnr/ppp1p1pp/8/3pPp2/8/8/PPPP1PPP/RNBQKBNR w KQkq f6 0 3"), 1700, 1700, 0, pl);
  CHECK_EQ(sum(pl, 16), 1.f);
  CHECK_EQ(pl[16 * 64 + 5 * 8 + 5], 1.f);  // f6 in the canonical view of White
  // Black to move: the e4 pawn can capture on d3, which is d6 in Black's canonical view
  me_build_planes(from("rnbqkbnr/pppp1ppp/8/8/3Pp3/8/PPP1PPPP/RNBQKBNR b KQkq d3 0 3"), 1700, 1700, 0, pl);
  CHECK_EQ(sum(pl, 16), 1.f);
  CHECK_EQ(pl[16 * 64 + 5 * 8 + 3], 1.f);
  // the square is recorded in the FEN but no pawn attacks it
  me_build_planes(from("rnbqkbnr/pppp1ppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"), 1700, 1700, 0, pl);
  CHECK_EQ(sum(pl, 16), 0.f);
}

TEST(MePlanes, CastlingRightsAreRelativeToTheMover) {
  float pl[ME_PLANES * 64];
  me_build_planes(from("r3k2r/8/8/8/8/8/8/R3K2R w Kq - 0 1"), 1700, 1700, 0, pl);
  CHECK_EQ(sum(pl, 12), 64.f); CHECK_EQ(sum(pl, 13), 0.f); CHECK_EQ(sum(pl, 14), 0.f); CHECK_EQ(sum(pl, 15), 64.f);
  me_build_planes(from("r3k2r/8/8/8/8/8/8/R3K2R b Kq - 0 1"), 1700, 1700, 0, pl);
  CHECK_EQ(sum(pl, 12), 0.f); CHECK_EQ(sum(pl, 13), 64.f); CHECK_EQ(sum(pl, 14), 64.f); CHECK_EQ(sum(pl, 15), 0.f);
}

TEST(MePlanes, RatingAndPlatformPlanes) {
  float pl[ME_PLANES * 64];
  me_build_planes(Position(), 2200, 1200, 1, pl);
  CHECK_EQ(pl[17 * 64 + 5], 1.f);
  CHECK_EQ(pl[18 * 64 + 63], -1.f);
  CHECK_EQ(sum(pl, 19), 64.f);
}

// ---- loading ------------------------------------------------------------------------------------------------------

TEST(MeNet, LoadsAWellFormedFile) {
  NetFile nf(1, 4, 2);
  MeNet net;
  std::string err;
  CHECK(net.load(write_file("ok.bin", nf.bytes()), &err));
  CHECK(net.loaded() && net.blocks() == 1 && net.channels() == 4);
}

TEST(MeNet, RejectsBadFiles) {
  NetFile nf(1, 4, 2);
  MeNet net;
  std::string err;
  const std::string good = nf.bytes();
  CHECK(!net.load("/no/such/net.bin", &err));
  CHECK(err.find("cannot open") != std::string::npos);
  CHECK(!net.load(write_file("magic.bin", nf.bytes("XXXX")), &err));
  CHECK(err.find("magic") != std::string::npos);
  CHECK(!net.load(write_file("ver.bin", nf.bytes("CMNN", 9)), &err));
  CHECK(err.find("version") != std::string::npos);
  CHECK(!net.load(write_file("trunc.bin", good.substr(0, good.size() - 8)), &err));
  CHECK(err.find("truncated") != std::string::npos);
  CHECK(!net.load(write_file("trail.bin", good + "zz"), &err));
  CHECK(err.find("trailing") != std::string::npos);
  NetFile bad(0, 4, 2);
  bad.f.assign(10, 0.f);
  CHECK(!net.load(write_file("dims.bin", bad.bytes()), &err));
  CHECK(err.find("dimensions") != std::string::npos);
  NetFile nan_file(1, 4, 2);
  nan_file.f[nan_file.off_bias + 5] = std::nanf("");
  CHECK(!net.load(write_file("nan.bin", nan_file.bytes()), &err));
  CHECK(err.find("non-finite") != std::string::npos);
  CHECK(!net.loaded());  // failed loads never leave a half-loaded network
}

TEST(MeNet, FailedLoadKeepsThePreviousNetwork) {
  NetFile nf(1, 4, 2);
  MeNet net;
  CHECK(net.load(write_file("keep.bin", nf.bytes())));
  CHECK(!net.load("/no/such/file"));
  CHECK(net.loaded());
}

// ---- forward pass on a synthetic network -----------------------------------------------------------------------------

TEST(MeNet, ZeroWeightsGiveExactlyTheMoveBias) {
  NetFile nf(1, 4, 2);
  nf.f[nf.off_bias + 12 * 64 + 28] = 2.0f;  // e2e4
  MeNet net;
  CHECK(net.load(write_file("bias.bin", nf.bytes())));
  Position p;
  auto pol = net.policy(p, 1700, 1700, 0);
  CHECK_EQ(int(pol.size()), 20);
  CHECK_EQ(move_to_uci(pol[0].first), std::string("e2e4"));
  const double expected = std::exp(2.0) / (std::exp(2.0) + 19.0);
  CHECK(std::fabs(pol[0].second - expected) < 1e-5);
  double total = 0;
  for (auto& [m, pr] : pol) total += pr;
  CHECK(std::fabs(total - 1.0) < 1e-5);
  for (size_t i = 1; i < pol.size(); ++i) CHECK(pol[i - 1].second >= pol[i].second);  // sorted
}

TEST(MeNet, BlackToMoveUsesTheMirroredSlot) {
  NetFile nf(1, 4, 2);
  nf.f[nf.off_bias + 12 * 64 + 28] = 3.0f;  // canonical e2e4, i.e. e7e5 for Black
  MeNet net;
  CHECK(net.load(write_file("black.bin", nf.bytes())));
  Position p = from("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR b KQkq - 0 1");
  CHECK_EQ(move_to_uci(net.policy(p, 1700, 1700, 0)[0].first), std::string("e7e5"));
}

TEST(MeNet, UnderpromotionHeadIsReadFromItsOwnSlots) {
  NetFile nf(1, 4, 2);
  nf.f[nf.off_under_b + 1] = 5.0f;  // slot 4096 + 1: a7a8n
  MeNet net;
  CHECK(net.load(write_file("under.bin", nf.bytes())));
  Position p = from("1n2k3/P7/8/8/8/8/8/4K3 w - - 0 1");
  auto pol = net.policy(p, 1700, 1700, 0);
  CHECK_EQ(move_to_uci(pol[0].first), std::string("a7a8n"));
}

TEST(MeNet, EmbeddingsContributeADotProduct) {
  // 1 block, 1 channel. Make the stem output a constant 1 everywhere (bias 1, no input weights), pass it through
  // the (zero) tower, and give the from/to embeddings constant values: logit(f,t) = q*k/sqrt(D) for every square pair.
  NetFile nf(1, 1, 1);
  nf.f[ME_PLANES * 9] = 1.0f;          // stem bias = 1 -> x = relu(1) = 1
  nf.f[nf.off_qk_w + 0] = 2.0f;        // q = 2 * x
  nf.f[nf.off_qk_w + 1] = 3.0f;        // k = 3 * x
  MeNet net;
  CHECK(net.load(write_file("emb.bin", nf.bytes())));
  std::vector<float> lg;
  net.logits(Position(), 1700, 1700, 0, lg);
  CHECK(std::fabs(lg[12 * 64 + 28] - 6.0f) < 1e-5);  // 2*3 / sqrt(1)
  CHECK(std::fabs(lg[0] - 6.0f) < 1e-5);
}

TEST(MeNet, ConvolutionsSeeTheBoardWithZeroPadding) {
  // A 3x3 kernel that copies the centre input of plane 5 (mover's king) with bias 0: q = k = king map, so the
  // logit of (king square, king square) is 1 and everything else 0.
  NetFile nf(1, 1, 1);
  nf.f[(5 * 9) + 4] = 1.0f;  // stem weight for input plane 5, centre tap -> x = relu(king map)
  nf.f[nf.off_qk_w + 0] = 1.0f;
  nf.f[nf.off_qk_w + 1] = 1.0f;
  MeNet net;
  CHECK(net.load(write_file("conv.bin", nf.bytes())));
  std::vector<float> lg;
  net.logits(Position(), 1700, 1700, 0, lg);
  CHECK(std::fabs(lg[4 * 64 + 4] - 1.0f) < 1e-5);  // e1 -> e1
  CHECK(std::fabs(lg[4 * 64 + 5]) < 1e-5);
  CHECK(std::fabs(lg[3 * 64 + 4]) < 1e-5);
}

// ---- UCI ----------------------------------------------------------------------------------------------------------

TEST(MeNetUci, LoadsTheNetworkAndPrintsAPolicy) {
  NetFile nf(1, 4, 2);
  nf.f[nf.off_bias + 12 * 64 + 28] = 4.0f;
  const std::string path = write_file("uci.bin", nf.bytes());
  std::string out = session("setoption name MeNetFile value " + path + "\nposition startpos\nmenet\n");
  CHECK(out.find("loaded me-network") != std::string::npos);
  CHECK(out.find("menet e2e4:") != std::string::npos);
}

TEST(MeNetUci, ReportsMissingNetworkAndBadFiles) {
  CHECK(session("position startpos\nmenet\n").find("menet unavailable") != std::string::npos);
  std::string out = session("setoption name MeNetFile value /no/such/file\nisready\n");
  CHECK(out.find("MeNetFile error") != std::string::npos && out.find("readyok") != std::string::npos);
}
