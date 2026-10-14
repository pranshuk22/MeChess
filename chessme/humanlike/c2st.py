"""Classifier two-sample test: can a classifier tell human games from generated ones, given only the moves?

Human and generated games start from the SAME positions (`humanlike-humangames`, `humanlike-selfplay --starts-from`), so the two samples are paired by
start. Both are cut at the length of the human game (humans resign, generated games are played out; without the cut the length of a game would give the
answer away). The features describe the moves only, from the mover's point of view: what kind of move it is (piece, capture, check, castling,
promotion), how far it goes, whether it recaptures, whether the piece lands on an attacked square, the material balance and the phase. No clocks,
no thinking time (the time model is crude and would be found at once), no result, no ending, no model probabilities.

The lower the AUC, the harder the generated games are to tell from human ones (0.5: not at all). Per fold of a game-disjoint cross-validation (a start and
its two games always fall in the same fold), a linear model and a small neural network are fitted; the reported AUC is of the out-of-fold scores, with a
bootstrap over starts, and differences between generated sets are paired over the same starts. Two controls: human against human (different games,
random halves) must give 0.5, otherwise the features or the folds leak."""
import hashlib

import chess
import numpy as np
import torch
import torch.nn as nn

PIECE_VALUE = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}
MOVE_FEATURES = ["pawn", "knight", "bishop", "rook", "queen", "king", "capture", "check", "castle", "promotion", "distance", "forward", "file_change",
                 "centre", "recapture", "lands_attacked", "material_balance", "phase", "legal_moves", "in_check", "captured_value", "own_attackers_on_target"]


def _material(board, color):
    return sum(PIECE_VALUE[p.piece_type] for p in board.piece_map().values() if p.color == color)


def move_rows(record, plies=None):
    """One row of features per move of the record (the model's or the human's, after the start), up to `plies` half-moves in total."""
    board = chess.Board()
    for u in record["start"].split():
        board.push_uci(u)
    moves = record["moves"].split()
    if plies is not None:
        moves = moves[:max(0, plies - len(record["start"].split()))]
    rows, last_to = [], None
    for u in moves:
        move = chess.Move.from_uci(u)
        us, them = board.turn, not board.turn
        piece = board.piece_at(move.from_square)
        captured = board.piece_at(move.to_square)
        if board.is_en_passant(move):
            captured = chess.Piece(chess.PAWN, them)
        sign = 1 if us == chess.WHITE else -1
        df, dr = chess.square_file(move.to_square) - chess.square_file(move.from_square), chess.square_rank(move.to_square) - chess.square_rank(move.from_square)
        row = np.zeros(len(MOVE_FEATURES), dtype=np.float32)
        row[piece.piece_type - 1] = 1
        row[6] = captured is not None
        row[8] = board.is_castling(move)
        row[9] = move.promotion is not None
        row[10] = max(abs(df), abs(dr)) / 7
        row[11] = sign * dr / 7
        row[12] = abs(df) / 7
        row[13] = 1 - (abs(chess.square_file(move.to_square) - 3.5) + abs(chess.square_rank(move.to_square) - 3.5)) / 7
        row[14] = last_to is not None and move.to_square == last_to and captured is not None
        row[16] = float(np.clip((_material(board, us) - _material(board, them)) / 10, -1, 1))
        row[17] = sum(PIECE_VALUE[p.piece_type] for p in board.piece_map().values() if p.piece_type not in (chess.PAWN, chess.KING)) / 62
        row[18] = board.legal_moves.count() / 40
        row[19] = board.is_check()
        row[20] = 0 if captured is None else PIECE_VALUE[captured.piece_type] / 9
        row[21] = len(board.attackers(us, move.to_square)) / 4
        board.push(move)
        row[7] = board.is_check()
        row[15] = board.is_attacked_by(them, move.to_square) and not board.is_attacked_by(us, move.to_square)       # lands on a square only the opponent covers
        last_to = move.to_square
        rows.append(row)
    return np.array(rows, dtype=np.float32).reshape(len(rows), len(MOVE_FEATURES))


def game_vector(rows):
    """Per-game features: the mean of every move feature over the whole stretch, over its first half and over its second half."""
    if len(rows) == 0:
        return np.zeros(3 * len(MOVE_FEATURES), dtype=np.float32)
    half = max(1, len(rows) // 2)
    return np.concatenate([rows.mean(0), rows[:half].mean(0), rows[half:].mean(0) if len(rows) > half else rows.mean(0)]).astype(np.float32)


def feature_table(human, generated):
    """Game vectors of the human games and of each generated set, for the starts present in all of them, cut at the length of the human game.
    `human` is a list of records, `generated` a dict name -> list of records. Returns (gids, X_human, {name: X})."""
    by = {name: {r["gid"]: r for r in rs} for name, rs in generated.items()}
    gids = [r["gid"] for r in human if all(r["gid"] in d for d in by.values())]
    h = {r["gid"]: r for r in human}
    X_h = np.stack([game_vector(move_rows(h[g])) for g in gids])
    X = {name: np.stack([game_vector(move_rows(d[g], plies=h[g]["plies"])) for g in gids]) for name, d in by.items()}
    return gids, X_h, X


def auc(scores, labels):
    """Area under the ROC curve (the chance that a random positive scores above a random negative; ties count half)."""
    scores, labels = np.asarray(scores, dtype=np.float64), np.asarray(labels)
    pos, neg = scores[labels == 1], scores[labels == 0]
    if len(pos) == 0 or len(neg) == 0:
        raise ValueError("both classes are needed")
    order = np.argsort(np.concatenate([pos, neg]), kind="mergesort")
    allv = np.concatenate([pos, neg])[order]
    ranks = np.empty(len(allv))
    i = 0
    while i < len(allv):                                         # average ranks over ties
        j = i
        while j + 1 < len(allv) and allv[j + 1] == allv[i]:
            j += 1
        ranks[i:j + 1] = (i + j) / 2 + 1
        i = j + 1
    r = np.empty(len(allv))
    r[order] = ranks
    return float((r[:len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


def fold_of(gid, folds, seed):
    return int.from_bytes(hashlib.sha256(f"{seed}:fold:{gid}".encode()).digest()[:4], "big") % folds


def fit_predict(X_train, y_train, X_test, hidden=0, epochs=60, seed=0, weight_decay=1e-3):
    """Logistic regression (`hidden=0`) or a one-hidden-layer network on standardised features; returns the logits of `X_test`."""
    torch.manual_seed(seed)
    mu, sd = X_train.mean(0), X_train.std(0) + 1e-6
    xt, xs = torch.tensor((X_train - mu) / sd), torch.tensor((X_test - mu) / sd)
    yt = torch.tensor(y_train, dtype=torch.float32)
    net = nn.Linear(xt.shape[1], 1) if hidden == 0 else nn.Sequential(nn.Linear(xt.shape[1], hidden), nn.ReLU(), nn.Dropout(0.2), nn.Linear(hidden, 1))
    opt = torch.optim.AdamW(net.parameters(), lr=3e-3, weight_decay=weight_decay)
    gen = torch.Generator().manual_seed(seed)
    for _ in range(epochs):
        net.train()
        perm = torch.randperm(len(xt), generator=gen)
        for i in range(0, len(xt), 256):
            b = perm[i:i + 256]
            loss = nn.functional.binary_cross_entropy_with_logits(net(xt[b]).squeeze(-1), yt[b])
            opt.zero_grad()
            loss.backward()
            opt.step()
    net.eval()
    with torch.no_grad():
        return net(xs).squeeze(-1).numpy()


def out_of_fold_scores(X0, X1, gids, folds=5, seed=0, hidden=0, **kw):
    """Scores of every game of class 0 (`X0`, human) and class 1 (`X1`, generated) from a model that never saw its start. Returns (s0, s1)."""
    fold = np.array([fold_of(g, folds, seed) for g in gids])
    s0, s1 = np.zeros(len(gids)), np.zeros(len(gids))
    for f in range(folds):
        tr, te = fold != f, fold == f
        X = np.concatenate([X0[tr], X1[tr]])
        y = np.concatenate([np.zeros(tr.sum()), np.ones(tr.sum())])
        scores = fit_predict(X, y, np.concatenate([X0[te], X1[te]]), hidden=hidden, seed=seed + f, **kw)
        s0[te], s1[te] = scores[:te.sum()], scores[te.sum():]
    return s0, s1


def paired_auc(s0, s1):
    return auc(np.concatenate([s0, s1]), np.concatenate([np.zeros(len(s0)), np.ones(len(s1))]))


def bootstrap_auc(s0, s1, boot=500, seed=0, other=None):
    """95% interval of the AUC by resampling starts (a start brings both its games). With `other=(t0, t1)`: of the difference AUC(s) - AUC(t) on the same starts."""
    rng = np.random.default_rng(seed)
    n, vals = len(s0), []
    for _ in range(boot):
        idx = rng.integers(0, n, n)
        a = paired_auc(s0[idx], s1[idx])
        vals.append(a - paired_auc(other[0][idx], other[1][idx]) if other else a)
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


def null_auc(X_human, gids, folds=5, seed=0, hidden=0, **kw):
    """Human against human: the starts are split at random into two halves, one half is class 0 and the other class 1 (different games). Must be 0.5."""
    rng = np.random.default_rng(seed)
    half = rng.permutation(len(gids)) < len(gids) // 2
    a, b = X_human[half], X_human[~half]
    n = min(len(a), len(b))
    ids = [g for g, h in zip(gids, half) if h][:n]
    s0, s1 = out_of_fold_scores(a[:n], b[:n], ids, folds=folds, seed=seed, hidden=hidden, **kw)
    return paired_auc(s0, s1)


def run(human, generated, folds=5, seed=0, boot=500, hidden=32, **kw):
    """The whole test. Returns a dict with the AUC of every generated set against the human games (linear and network), the paired differences
    between the sets and the human-against-human control."""
    gids, X_h, X = feature_table(human, generated)
    out = {"starts": len(gids), "models": {}, "pairs": [], "null": {}}
    scores = {}
    for kind, hid in (("linear", 0), ("network", hidden)):
        out["null"][kind] = null_auc(X_h, gids, folds=folds, seed=seed, hidden=hid, **kw)
        for name, Xg in X.items():
            s0, s1 = out_of_fold_scores(X_h, Xg, gids, folds=folds, seed=seed, hidden=hid, **kw)
            scores[(kind, name)] = (s0, s1)
            lo, hi = bootstrap_auc(s0, s1, boot=boot, seed=seed)
            out["models"].setdefault(name, {})[kind] = {"auc": paired_auc(s0, s1), "ci": (lo, hi)}
        names = list(X)
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                a, b = scores[(kind, names[i])], scores[(kind, names[j])]
                lo, hi = bootstrap_auc(*a, boot=boot, seed=seed, other=b)
                out["pairs"].append({"kind": kind, "a": names[i], "b": names[j], "diff": paired_auc(*a) - paired_auc(*b), "ci": (lo, hi)})
    return out


def report(result):
    lines = [f"Human against generated games from the same {result['starts']:,} starts (cut at the length of the human game; moves only: no clocks, results or model probabilities). "
             "AUC 0.5: the classifier cannot tell them apart; 1.0: it always can. 95% intervals by resampling starts.\n",
             "| generated games | linear model AUC | network AUC |", "|---|---|---|"]
    for name, m in result["models"].items():
        lines.append(f"| {name} | " + " | ".join(f"{m[k]['auc']:.3f} [{m[k]['ci'][0]:.3f}, {m[k]['ci'][1]:.3f}]" for k in ("linear", "network")) + " |")
    lines.append(f"| control: human against human | {result['null']['linear']:.3f} | {result['null']['network']:.3f} |")
    if result["pairs"]:
        lines += ["", "Paired differences in AUC on the same starts (negative: the first set is harder to tell from human games):", "", "| first | second | model | AUC difference |", "|---|---|---|---|"]
        for p in result["pairs"]:
            lines.append(f"| {p['a']} | {p['b']} | {p['kind']} | {p['diff']:+.3f} [{p['ci'][0]:+.3f}, {p['ci'][1]:+.3f}] |")
    return "\n".join(lines)
