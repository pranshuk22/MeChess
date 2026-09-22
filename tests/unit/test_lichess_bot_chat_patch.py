import importlib.util
import logging
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path("tools")))
import patch_lichess_bot_chat as P                    # noqa: E402

# A minimal stand-in for lichess-bot's lib/conversation.py: only the shape the patch relies on (the three places it edits).
CONVERSATION = '''"""Allows lichess-bot to send messages to the chat."""
import logging
logger = logging.getLogger(__name__)


class ChatLine:
    def __init__(self, message_info):
        self.room = message_info["room"]
        self.username = message_info["username"]
        self.text = message_info["text"]


class Conversation:
    def __init__(self, game, engine, li):
        self.game, self.engine, self.li = game, engine, li

    command_prefix = "!"

    def react(self, line):
        if line.text[0] == self.command_prefix:
            self.command(line, line.text[1:].lower())

    def command(self, line, cmd):
        if cmd in ("commands", "help"):
            self.send_reply(line,
                            "Supported commands: !wait (wait a minute for my first move), !name, "
                            "!eval (or any text starting with !eval), !queue")
        elif cmd == "wait" and self.game.is_abortable():
            self.send_reply(line, "Waiting 60 seconds...")
        elif cmd == "name":
            self.send_reply(line, "name")

    def send_reply(self, line: ChatLine, reply: str) -> None:
        self.li.chat(self.game.id, line.room, reply)
'''


@pytest.fixture
def bot_dir(tmp_path):
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "conversation.py").write_text(CONVERSATION)
    return tmp_path


def load(bot_dir):
    spec = importlib.util.spec_from_file_location("conversation_under_test", bot_dir / "lib" / "conversation.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Option:
    def __init__(self, default):
        self.default = default


class FakeEngine:
    def __init__(self, with_elo=True, fail=False):
        self.options = {"Elo": Option(1800)} if with_elo else {}          # 1800 is what the engine declares; the bot's config sets 1500
        self.protocol = types.SimpleNamespace(config={"Elo": 1500} if with_elo else {})
        self.fail, self.set = fail, []

    def configure(self, d):
        if self.fail:
            raise RuntimeError("engine gone")
        self.set.append(d)
        self.protocol.config.update(d)


class Chat:
    def __init__(self):
        self.sent = []

    def chat(self, game_id, room, text):
        self.sent.append(text)


def conversation(mod, engine):
    li = Chat()
    game = types.SimpleNamespace(id="g1", is_abortable=lambda: False)
    return mod.Conversation(game, types.SimpleNamespace(engine=engine), li), li


def say(mod, conv, text):
    conv.react(mod.ChatLine({"room": "player", "username": "someone", "text": text}))


def test_patch_adds_the_command_and_is_idempotent(bot_dir):
    P.main([str(bot_dir)])
    once = (bot_dir / "lib" / "conversation.py").read_text()
    assert "!elo N" in once and once.count(P.MARK) >= 3
    P.main([str(bot_dir)])                                                       # a second run changes nothing
    assert (bot_dir / "lib" / "conversation.py").read_text() == once
    assert (bot_dir / "lib" / "conversation.py.mechess-orig").read_text() == CONVERSATION


def test_revert_restores_the_original_file(bot_dir):
    P.main([str(bot_dir)])
    P.main([str(bot_dir), "--revert"])
    assert (bot_dir / "lib" / "conversation.py").read_text() == CONVERSATION
    assert not (bot_dir / "lib" / "conversation.py.mechess-orig").exists()


def test_an_unexpected_upstream_file_is_refused_and_left_alone(bot_dir):
    (bot_dir / "lib" / "conversation.py").write_text("class Conversation:\n    pass\n")
    with pytest.raises(SystemExit, match="does not look as expected"):
        P.main([str(bot_dir)])
    assert (bot_dir / "lib" / "conversation.py").read_text() == "class Conversation:\n    pass\n"
    assert not (bot_dir / "lib" / "conversation.py.mechess-orig").exists()


def test_patched_file_still_works_for_the_other_commands(bot_dir):
    P.main([str(bot_dir)])
    mod = load(bot_dir)
    conv, li = conversation(mod, FakeEngine())
    say(mod, conv, "!name")
    say(mod, conv, "!help")
    assert li.sent[0] == "name" and "!elo N" in li.sent[1] and "!wait" in li.sent[1]


def test_the_help_reply_fits_lichess_chat_limit(bot_dir):
    # Regression: the !elo addition used to push !help/!commands past lichess-bot's 140-char chat limit, so
    # lichess-bot silently dropped it (logged a warning, never sent it) - this failed before the HELP_ADDED fix.
    P.main([str(bot_dir)])
    mod = load(bot_dir)
    conv, li = conversation(mod, FakeEngine())
    say(mod, conv, "!help")
    assert len(li.sent[-1]) <= P.CHAT_LIMIT


def test_elo_sets_the_engine_option_and_answers(bot_dir):
    P.main([str(bot_dir)])
    mod = load(bot_dir)
    eng = FakeEngine()
    conv, li = conversation(mod, eng)
    say(mod, conv, "!elo 1300")
    assert eng.set == [{"Elo": 1300}] and "1300" in li.sent[-1]
    say(mod, conv, "!ELO")                                                       # lower-cased by the bot; alone it reports
    assert "1300" in li.sent[-1] and len(eng.set) == 1


def test_elo_is_clamped_to_the_measured_range_and_says_so(bot_dir):
    P.main([str(bot_dir)])
    mod = load(bot_dir)
    eng = FakeEngine()
    conv, li = conversation(mod, eng)
    say(mod, conv, "!elo 3000")
    say(mod, conv, "!elo 100")
    assert [d["Elo"] for d in eng.set] == [P.RANGE[1], P.RANGE[0]] and "nearest" in li.sent[-1]


def test_elo_reports_the_default_before_any_change(bot_dir):
    P.main([str(bot_dir)])
    mod = load(bot_dir)
    conv, li = conversation(mod, FakeEngine())
    say(mod, conv, "!elo")
    assert "1500" in li.sent[-1]


def test_elo_needs_a_number_and_a_limited_number_of_changes(bot_dir):
    P.main([str(bot_dir)])
    mod = load(bot_dir)
    eng = FakeEngine()
    conv, li = conversation(mod, eng)
    say(mod, conv, "!elo high")
    say(mod, conv, "!elo -5")
    assert eng.set == [] and "number" in li.sent[-1]
    for n in range(P.CHANGES + 2):
        say(mod, conv, f"!elo {1000 + n}")
    assert len(eng.set) == P.CHANGES and "enough changes" in li.sent[-1]


def test_engine_without_elo_option_or_a_failing_engine_is_handled(bot_dir, caplog):
    P.main([str(bot_dir)])
    mod = load(bot_dir)
    conv, li = conversation(mod, FakeEngine(with_elo=False))
    say(mod, conv, "!elo 1500")
    assert "no Elo setting" in li.sent[-1]
    conv, li = conversation(mod, FakeEngine(fail=True))
    with caplog.at_level(logging.ERROR):
        say(mod, conv, "!elo 1500")
    assert "could not change" in li.sent[-1]
