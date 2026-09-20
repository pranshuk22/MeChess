"""Small, realistic raw-data samples used across the tests (no network, no personal data)."""

def fill(template, white, black="opp"):
    return template.replace("@WHITE@", white).replace("@BLACK@", black)


LICHESS_GAME = """[Event "Rated Blitz game"]
[Site "https://lichess.org/abcd1234"]
[Date "2024.03.30"]
[White "@WHITE@"]
[Black "@BLACK@"]
[Result "1-0"]
[UTCDate "2024.03.30"]
[UTCTime "12:00:00"]
[WhiteElo "1900"]
[BlackElo "1850"]
[TimeControl "300+0"]
[ECO "B90"]
[Opening "Sicilian Defense: Najdorf Variation"]
[Termination "Normal"]
[Variant "Standard"]

1. e4 { [%clk 0:05:00] } c5 { [%clk 0:05:00] } 2. Nf3 { [%clk 0:04:58] } d6 { [%clk 0:04:57] } 3. d4 { [%clk 0:04:55] } cxd4 { [%clk 0:04:54] } 4. Nxd4 { [%clk 0:04:52] } Nf6 { [%clk 0:04:50] } 5. Nc3 { [%clk 0:04:49] } a6 { [%clk 0:04:47] } 1-0

"""

LICHESS_SHORT = LICHESS_GAME.replace("abcd1234", "short001").replace(
    "1. e4 { [%clk 0:05:00] } c5 { [%clk 0:05:00] } 2. Nf3 { [%clk 0:04:58] } d6 { [%clk 0:04:57] } 3. d4 { [%clk 0:04:55] } cxd4 { [%clk 0:04:54] } 4. Nxd4 { [%clk 0:04:52] } Nf6 { [%clk 0:04:50] } 5. Nc3 { [%clk 0:04:49] } a6 { [%clk 0:04:47] } 1-0",
    "1. e4 e5 2. Qh5 Nc6 1-0",
)

LICHESS_960 = """[Event "Rated Chess960 game"]
[Site "https://lichess.org/c960c960"]
[Date "2024.03.30"]
[White "@WHITE@"]
[Black "opp"]
[Result "1-0"]
[UTCDate "2024.03.30"]
[UTCTime "13:00:00"]
[WhiteElo "1900"]
[BlackElo "1850"]
[TimeControl "300+0"]
[Variant "Chess960"]
[SetUp "1"]
[FEN "bbqnnrkr/pppppppp/8/8/8/8/PPPPPPPP/BBQNNRKR w HFhf - 0 1"]

1. g3 g6 2. Nd3 Nd6 3. Nf4 Nf5 4. Ng2 Ng7 5. a3 a6 1-0

"""

CHESSCOM_PGN = (
    '[Event "Live Chess"]\n[Site "Chess.com"]\n[Date "2024.05.01"]\n[White "@WHITE@"]\n[Black "@BLACK@"]\n'
    '[Result "0-1"]\n[WhiteElo "1700"]\n[BlackElo "1720"]\n[TimeControl "600"]\n[ECO "D00"]\n'
    '[ECOUrl "https://www.chess.com/openings/Queens-Pawn-Opening-Accelerated-London-System-2...d5"]\n'
    '[UTCDate "2024.05.01"]\n[UTCTime "09:30:00"]\n\n'
    '1. d4 {[%clk 0:10:00.0]} 1... d5 {[%clk 0:10:00.0]} 2. Bf4 {[%clk 0:09:58.3]} 2... Nf6 {[%clk 0:09:57.1]} '
    '3. e3 {[%clk 0:09:55.0]} 3... c5 {[%clk 0:09:50.2]} 4. c3 {[%clk 0:09:45.0]} 4... Nc6 {[%clk 0:09:44.0]} 0-1'
)


def chesscom_game(white="example_user", black="someone", uuid="uuid-1", rules="chess", time_class="rapid", rated=True):
    return {
        "url": f"https://www.chess.com/game/live/{uuid}",
        "uuid": uuid,
        "pgn": fill(CHESSCOM_PGN, white, black),
        "time_class": time_class,
        "rules": rules,
        "rated": rated,
        "end_time": 1714555000,
        "white": {"username": white, "rating": 1700, "result": "resigned"},
        "black": {"username": black, "rating": 1720, "result": "win"},
    }


def make_row(**over):
    """A normalised game row as produced by chessme.ingest.normalize (for weights/audit tests)."""
    row = {
        "game_id": "lichess:x1", "platform": "lichess", "account": "me", "color": "white",
        "my_rating": 1800, "opp_rating": 1800, "opp_name": "opp", "result": "1-0", "my_result": "win",
        "time_class": "blitz", "time_control": "300+0", "rated": True, "variant": "standard",
        "played_at": "2024-01-01T00:00:00+00:00", "eco": "B20", "opening": "Sicilian Defense: Najdorf",
        "termination": "Normal", "plies": 40, "moves": "e4 c5 Nf3 d6", "clocks": [300.0, 300.0, 298.0, 297.0],
        "usable": True, "unusable_reason": None,
    }
    row.update(over)
    return row
