import re
import subprocess


def run_uci(binary, commands, timeout=60):
    """Runs one UCI session: feeds `commands`, lets any finite search complete (end of input), returns stdout.

    Deliberately no trailing `quit`: quit would abort a search that is still running.
    """
    script = "\n".join(commands) + "\n"
    p = subprocess.run([str(binary)], input=script, capture_output=True, text=True, timeout=timeout)
    assert p.returncode == 0, p.stderr
    return p.stdout


def best_move(binary, fen, depth=3, moves=None, timeout=60):
    pos = f"position fen {fen}" + (f" moves {' '.join(moves)}" if moves else "")
    out = run_uci(binary, [pos, f"go depth {depth}"], timeout)
    m = re.search(r"^bestmove (\S+)", out, re.M)
    assert m, out
    return m.group(1), out


def last_score(out):
    """Last 'score cp N' / 'score mate N' from the engine's info lines, as ('cp'|'mate', int)."""
    found = re.findall(r"score (cp|mate) (-?\d+)", out)
    kind, val = found[-1]
    return kind, int(val)
