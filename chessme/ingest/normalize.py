"""Turn raw Lichess PGN / chess.com JSON into one row per game (data/processed/games.jsonl)."""
import io
import json
import re
from datetime import datetime, timezone

import chess.pgn

MIN_PLIES = 8  # shorter games carry no usable signal (aborts, instant resigns)
TC_ORDER = ["ultrabullet", "bullet", "blitz", "rapid", "classical", "correspondence"]


def _int(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def time_class_from_tc(tc):
    """Lichess rule: base + 40*increment seconds."""
    if not tc or "+" not in tc:
        return "correspondence"
    try:
        base, inc = tc.split("+")
        total = int(base) + 40 * int(inc)
    except ValueError:
        return "correspondence"
    for limit, name in [(30, "ultrabullet"), (120, "bullet"), (480, "blitz"), (1500, "rapid")]:
        if total < limit:
            return name
    return "classical"


def _played_at(h, fallback_epoch=None):
    d, t = h.get("UTCDate"), h.get("UTCTime")
    if d and t and "?" not in d:
        try:
            return datetime.strptime(f"{d} {t}", "%Y.%m.%d %H:%M:%S").replace(tzinfo=timezone.utc).isoformat()
        except ValueError:
            pass
    if fallback_epoch:
        return datetime.fromtimestamp(fallback_epoch, tz=timezone.utc).isoformat()
    return None


def _moves_and_clocks(game):
    sans, clocks = [], []
    board = game.board()
    for node in game.mainline():
        sans.append(board.san(node.move))
        board.push(node.move)
        c = node.clock()
        clocks.append(round(c, 1) if c is not None else None)
    return sans, clocks


def _row(game, *, platform, account, game_id, variant, time_class, rated, my_names, fallback_epoch=None,
         white_rating=None, black_rating=None, opening=None):
    h = game.headers
    white, black = h.get("White", "?"), h.get("Black", "?")
    color = "white" if white.lower() == account.lower() else "black"
    opp = black if color == "white" else white
    wr = white_rating if white_rating is not None else _int(h.get("WhiteElo"))
    br = black_rating if black_rating is not None else _int(h.get("BlackElo"))
    result = h.get("Result", "*")

    sans, clocks, parse_error = [], [], False
    reason = None
    custom_start = "FEN" in h or h.get("SetUp") == "1"
    if variant != "standard":
        reason = "variant"
    elif custom_start:
        reason = "custom_start_position"
    else:
        try:
            sans, clocks = _moves_and_clocks(game)
        except Exception:
            parse_error = True
            reason = "parse_error"
        if game.errors and not parse_error:
            reason, parse_error = "parse_error", True
    if reason is None:
        if len(sans) < MIN_PLIES:
            reason = "too_short"
        elif result == "*":
            reason = "unfinished"
        elif opp.lower() in my_names:
            reason = "vs_own_account"

    my_result = None
    if result in ("1-0", "0-1", "1/2-1/2"):
        if result == "1/2-1/2":
            my_result = "draw"
        else:
            my_result = "win" if (result == "1-0") == (color == "white") else "loss"

    return {
        "game_id": game_id,
        "platform": platform,
        "account": account,
        "color": color,
        "my_rating": wr if color == "white" else br,
        "opp_rating": br if color == "white" else wr,
        "opp_name": opp,
        "result": result,
        "my_result": my_result,
        "time_class": time_class,
        "time_control": h.get("TimeControl"),
        "rated": rated,
        "variant": variant,
        "played_at": _played_at(h, fallback_epoch),
        "eco": h.get("ECO"),
        "opening": opening,
        "termination": h.get("Termination"),
        "plies": len(sans),
        "moves": " ".join(sans),
        "clocks": clocks,
        "usable": reason is None,
        "unusable_reason": reason,
    }


def _lichess_rows(account, files, my_names):
    for path in sorted(files):
        with open(path, encoding="utf-8", errors="replace") as f:
            while True:
                game = chess.pgn.read_game(f)
                if game is None:
                    break
                h = game.headers
                gid = h.get("Site", "").rstrip("/").split("/")[-1]
                event = h.get("Event", "").lower()
                tc = next((n for n in TC_ORDER if n.replace("ultrabullet", "ultra") in event.replace(" ", "")), None)
                if tc is None:
                    tc = time_class_from_tc(h.get("TimeControl"))
                variant = h.get("Variant", "Standard").lower().replace(" ", "")
                variant = "standard" if variant == "standard" else variant
                yield _row(game, platform="lichess", account=account, game_id=f"lichess:{gid}",
                           variant=variant, time_class=tc, rated="rated" in event,
                           my_names=my_names, opening=h.get("Opening"))


def _chesscom_opening(h):
    url = h.get("ECOUrl")
    if not url:
        return None
    slug = url.rstrip("/").split("/")[-1]
    parts = []
    for tok in slug.split("-"):
        if re.search(r"\d", tok) or tok in ("...",):
            break
        parts.append(tok)
    return " ".join(parts) or None


def _chesscom_rows(account, files, my_names):
    for path in sorted(files):
        for g in json.loads(path.read_text()).get("games", []):
            pgn = g.get("pgn")
            if not pgn:
                continue
            game = chess.pgn.read_game(io.StringIO(pgn))
            if game is None:
                continue
            rules = g.get("rules", "chess")
            variant = "standard" if rules == "chess" else rules
            gid = g.get("uuid") or g.get("url", "").rstrip("/").split("/")[-1]
            yield _row(game, platform="chesscom", account=account, game_id=f"chesscom:{gid}",
                       variant=variant, time_class=g.get("time_class", "unknown"),
                       rated=bool(g.get("rated")), my_names=my_names,
                       fallback_epoch=g.get("end_time"),
                       white_rating=_int(g.get("white", {}).get("rating")),
                       black_rating=_int(g.get("black", {}).get("rating")),
                       opening=_chesscom_opening(game.headers))


def ingest(cfg):
    raw = cfg["_raw_dir"]
    my_names = {a["username"].lower() for a in cfg["accounts"]}
    rows, seen, dupes = [], set(), 0
    for acct in cfg["accounts"]:
        user, plat = acct["username"], acct["platform"]
        if plat == "lichess":
            files = list((raw / "lichess" / user).glob("games_*.pgn"))
            it = _lichess_rows(user, files, my_names)
        else:
            files = list((raw / "chesscom" / user).glob("*.json"))
            it = _chesscom_rows(user, files, my_names)
        n = 0
        for row in it:
            if row["game_id"] in seen:  # same game can appear under two of your accounts
                dupes += 1
                continue
            seen.add(row["game_id"])
            rows.append(row)
            n += 1
        print(f"  {plat}/{user}: {n} games")
    rows.sort(key=lambda r: r["played_at"] or "")
    out = cfg["_raw_dir"].parent / "processed"
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "games.jsonl", "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    usable = sum(r["usable"] for r in rows)
    print(f"wrote {len(rows)} games ({usable} usable, {dupes} duplicates dropped) -> {out / 'games.jsonl'}")
