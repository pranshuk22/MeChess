"""A plain-language style report (markdown) from the fitted comparison against the baseline population."""
from .axes import AXES

PHRASES = {  # feature -> (what "more than typical" means, what "less than typical" means)
    "capture": ("take material more readily", "avoid captures more"),
    "check": ("give checks more often", "give fewer checks"),
    "promotion": ("promote when possible more eagerly", "delay promotion more"),
    "castle_short": ("castle kingside sooner", "castle kingside later or less"),
    "castle_long": ("castle queenside more", "castle queenside less"),
    "sacrifice": ("sacrifice material more readily", "avoid sacrificing material"),
    "exchange_sacrifice": ("give the exchange (rook for minor piece) more often", "rarely give up the exchange"),
    "trade": ("trade pieces more readily", "keep pieces on the board more"),
    "queen_trade": ("trade queens more readily", "avoid queen trades"),
    "king_zone_delta": ("build pressure around the enemy king", "put less pressure on the enemy king"),
    "pawn_storm": ("push pawns at the enemy king", "rarely storm the enemy king with pawns"),
    "weakens_own_king": ("loosen your own king's pawn cover", "keep your king's pawn cover intact"),
    "pawn_break": ("play pawn breaks", "avoid pawn breaks"),
    "own_doubled_delta": ("accept doubled pawns", "avoid doubling your own pawns"),
    "own_isolated_delta": ("accept isolated pawns", "avoid isolated pawns"),
    "own_passed_delta": ("create passed pawns", "create fewer passed pawns"),
    "opp_doubled_delta": ("double the opponent's pawns", "rarely double the opponent's pawns"),
    "opp_isolated_delta": ("isolate the opponent's pawns", "rarely isolate the opponent's pawns"),
    "takes_bishop_pair": ("go for the opponent's bishop pair", "leave the opponent's bishop pair alone"),
    "concedes_bishop_pair": ("give up your own bishop pair", "protect your bishop pair"),
    "rook_open_file": ("put rooks on open files", "use open files less"),
    "rook_semi_open_file": ("put rooks on half-open files", "use half-open files less"),
    "rook_seventh": ("go for the seventh rank", "go to the seventh rank less"),
    "mobility_delta": ("choose moves that increase your piece mobility", "choose moves that reduce your mobility"),
    "to_center": ("put pieces on the four central squares", "keep pieces off the centre"),
    "pawn_push": ("push pawns", "push pawns less"),
    "retreat": ("pull pieces back", "rarely retreat pieces"),
    "king_move": ("move the king (without castling)", "keep the king still"),
}
AXIS_TEXT = {  # axis -> (high, low)
    "aggression": ("more attacking than typical", "less attacking than typical"),
    "risk_taking": ("takes more risks than typical", "plays safer than typical"),
    "simplification": ("simplifies more (trades, captures)", "keeps more tension and pieces"),
    "structural_care": ("cares more about pawn structure and files", "cares less about pawn structure"),
    "activity": ("plays more active, central moves", "plays more passive moves"),
}


def _strength(z):
    a = abs(z)
    return "clearly" if a >= 3 else "noticeably" if a >= 2 else "slightly" if a >= 1 else None


def _axis_line(axis, v):
    high, low = AXIS_TEXT[axis]
    s = _strength(v)
    return f"- **{axis.replace('_', ' ').title()}**: {'about typical' if s is None else f'{s} {high if v > 0 else low}'}  (score {v:+.1f})"


def render(*, player_label, n_player, n_base, rating, band, comparison, axis_scores, gains, held_out, loss_coef,
           caveats=()):
    """Markdown report.

    comparison: {"names", "z", "w_player", "w_base"}; axis_scores: {axis: value}; gains: [(lo, hi, n, d_nll, d_top1)];
    held_out: evaluate() output (style / loss_only / uniform) or None; loss_coef: the player's weight on strength."""
    z = dict(zip(comparison["names"], comparison["z"]))
    out = [f"# Playing style report: {player_label}", "",
           f"Based on {n_player:,} of your decisions (positions where several moves were about equally good, and you "
           f"picked one), compared with {n_base:,} decisions by other players rated {band[0]}-{band[1]} "
           f"(the comparison is made at your rating, about {rating:.0f}). A difference is only reported when it is "
           f"large compared with the noise.", "",
           "## In short", ""]
    out += [_axis_line(a, v) for a, v in axis_scores.items()]
    out += ["", "*These five axes are hypotheses (groups of move features chosen in advance); they have not yet been "
            "validated against famous players' games. Treat them as a description of your numbers, not a verdict.*", "",
            "## What you do differently from players of your rating", ""]
    notable = sorted(((n, v) for n, v in z.items() if abs(v) >= 2 and n in PHRASES), key=lambda t: -abs(t[1]))
    if notable:
        for n, v in notable[:10]:
            more, less = PHRASES[n]
            out.append(f"- You {more if v > 0 else less}, when the alternatives are about equally good "
                       f"({_strength(v)}; z = {v:+.1f}).")
    else:
        out.append("- No single habit differs from your rating group by more than the noise. Your choices look typical "
                   "of your rating in the features we measure.")
    out += ["", "## Where you are typical", ""]
    typical = [n for n, v in z.items() if abs(v) < 1 and n in PHRASES]
    out.append("- " + (", ".join(n.replace("_", " ") for n in typical) if typical else "none"))
    out += ["", "## How much does style explain?", ""]
    if held_out and held_out.get("n"):
        s, lo, u = held_out["style"], held_out["loss_only"], held_out["uniform"]
        out += [f"On your newest games (held out), among {held_out['n']} moves where several were about equally good:",
                f"- picking at random: {100 * u['top1']:.0f}% correct",
                f"- knowing only that you prefer stronger moves: {100 * lo['top1']:.0f}%",
                f"- adding your style preferences: **{100 * s['top1']:.0f}%**"]
    out.append(f"- Your care for move strength: weight {loss_coef:.1f} per 100 centipawns lost.")
    out += ["", "## Does style harden with rating?", "",
            "Extra accuracy that style features give over a strength-only model, by rating band (population data):", "",
            "| Rating band | Decisions | Gain in log-loss | Gain in top-1 |", "|---|---|---|---|"]
    for lo, hi, n, dn, dt in gains:
        out.append(f"| {lo}-{hi} | {n} | " + ("too few" if dn != dn else f"{dn:+.3f} | {100 * dt:+.1f} pts") + (" |" if dn == dn else " | |"))
    out += ["", "## Limits of this report", "",
            "- Style is measured only among moves the engine judges nearly equal; mistakes are a separate topic.",
            "- The feature set is a first version; it cannot see plans, prophylaxis or move-order ideas.",
            *[f"- {c}" for c in caveats]]
    return "\n".join(out) + "\n"
