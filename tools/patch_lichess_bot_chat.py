#!/usr/bin/env python3
"""Adds a chat command to a local lichess-bot checkout: `!elo N` changes the strength MeChess plays at, for that game, and `!elo` says what it is.

lichess-bot (AGPL-3.0) stays a separate program next to this repository; this script only edits your local copy of `lib/conversation.py` (a
backup is kept as `conversation.py.mechess-orig`), it is safe to run again, and an upgrade of lichess-bot that overwrites the file needs it once more.

    python3 tools/patch_lichess_bot_chat.py bot/lichess-bot            # apply
    python3 tools/patch_lichess_bot_chat.py bot/lichess-bot --revert   # restore the original

Who may change the strength: whoever is in the game's chat (in practice the opponent), at most CHANGES times per game, only within RANGE.
The handler runs in the same thread as the game loop, so the engine is idle when the option is set: it takes effect from the next move."""
import argparse
import shutil
import sys
from pathlib import Path

MARK = "# MeChess !elo"
RANGE = (900, 2400)          # about the range the dial was measured over
CHANGES = 5
CHAT_LIMIT = 140             # lib/lichess.py's MAX_CHAT_MESSAGE_LEN: lichess-bot silently drops (does not send) anything longer

# The upstream !help/!commands text (both adjacent string literals, concatenated) plus what we add for !elo. Built from
# pieces and length-checked below rather than hand-typed twice, so a longer HELP_ADDED can never silently ship
# a !help reply that lichess-bot drops for being over CHAT_LIMIT (github issue: this exact bug, fixed 2026-09-23).
HELP_BASE = ("Supported commands: !wait (wait a minute for my first move), !name, "
             "!eval (or any text starting with !eval), !queue")
HELP_ADDED = ", !elo N"
assert len(HELP_BASE + HELP_ADDED) <= CHAT_LIMIT, \
    f"the patched !help message would be {len(HELP_BASE + HELP_ADDED)} chars, over lichess-bot's {CHAT_LIMIT}-char chat limit " \
    "(it would be silently dropped, not sent) - shorten HELP_ADDED"

HELP_OLD = '"!eval (or any text starting with !eval), !queue")'
HELP_NEW = HELP_OLD[:-2] + HELP_ADDED + '")'
BRANCH_ANCHOR = '        elif cmd == "wait" and self.game.is_abortable():'
BRANCH = f'        elif cmd.split()[0] == "elo":  {MARK}\n            self.set_elo(line, cmd)\n'
METHOD_ANCHOR = "    def send_reply(self, line: ChatLine, reply: str) -> None:"
METHOD = f'''    MECHESS_ELO_RANGE = {RANGE}  {MARK}
    MECHESS_ELO_CHANGES = {CHANGES}

    def set_elo(self, line: ChatLine, cmd: str) -> None:  {MARK}
        """`!elo N` sets the engine's Elo option for this game; `!elo` alone reports it."""
        arg = cmd[3:].strip()
        engine = getattr(self.engine, "engine", None)
        options = getattr(engine, "options", None) or {{}}
        if "Elo" not in options:
            self.send_reply(line, "This engine has no Elo setting.")
            return
        lo, hi = self.MECHESS_ELO_RANGE
        current = getattr(self, "mechess_elo", None) or (getattr(getattr(engine, "protocol", None), "config", None) or {{}}).get("Elo") or options["Elo"].default
        if not arg:
            self.send_reply(line, f"I'm playing at about {{current}} Elo. Say !elo {{lo + 600}} to change it ({{lo}} to {{hi}}).")
            return
        if not arg.isdigit():
            self.send_reply(line, f"Say !elo followed by a number from {{lo}} to {{hi}}.")
            return
        if getattr(self, "mechess_changes", 0) >= self.MECHESS_ELO_CHANGES:
            self.send_reply(line, "That is enough changes for one game.")
            return
        elo = min(max(int(arg), lo), hi)
        try:
            engine.configure({{"Elo": elo}})
        except Exception:
            logger.exception("could not change the engine's Elo")
            self.send_reply(line, "Sorry, I could not change my strength.")
            return
        self.mechess_elo = elo
        self.mechess_changes = getattr(self, "mechess_changes", 0) + 1
        note = "" if elo == int(arg) else f" (that is the nearest I can do to {{arg}})"
        self.send_reply(line, f"OK, playing at about {{elo}} Elo from my next move{{note}}.")

'''


def patched(text):
    if MARK in text:
        return text
    for anchor in (HELP_OLD, BRANCH_ANCHOR, METHOD_ANCHOR):
        if text.count(anchor) != 1:
            raise SystemExit(f"this lichess-bot version does not look as expected (could not find one place for: {anchor.strip()[:60]!r}); nothing changed")
    text = text.replace(HELP_OLD, HELP_NEW).replace(BRANCH_ANCHOR, BRANCH + BRANCH_ANCHOR).replace(METHOD_ANCHOR, METHOD + METHOD_ANCHOR)
    return text


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("bot_dir"); p.add_argument("--revert", action="store_true")
    a = p.parse_args(argv)
    path = Path(a.bot_dir) / "lib" / "conversation.py"
    backup = path.with_name(path.name + ".mechess-orig")
    if not path.exists():
        sys.exit(f"{path} not found: give the lichess-bot folder")
    if a.revert:
        if not backup.exists():
            sys.exit("no backup to restore (the file was not patched by this script)")
        shutil.copy(backup, path)
        backup.unlink()
        print("restored", path)
        return
    text = path.read_text(encoding="utf-8")
    if MARK in text:
        print("already patched")
        return
    new = patched(text)
    shutil.copy(path, backup)
    path.write_text(new, encoding="utf-8")
    print(f"patched {path} (backup {backup.name}); restart the bot; in a game chat: !elo 1500")


if __name__ == "__main__":
    main()
