"""Start and stop the Lichess bot from the app. The bot itself is `lichess-bot` in a local checkout (docs/lichess-bot.md); the app only runs the launcher script that lives
beside it. **The token never passes through the app**: the launcher reads it from the environment variable `LICHESS_BOT_TOKEN` of the app's own process or from the macOS Keychain,
and the app neither stores nor shows it."""
import os
import shutil
import signal
import subprocess
import sys
import threading
from pathlib import Path


class BotService:
    def __init__(self, bot_dir: Path):
        self.dir = Path(bot_dir)
        self.proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

    @property
    def launcher(self) -> Path:
        return self.dir / "run-bot.sh"

    @property
    def log(self) -> Path:
        return self.dir / "logs" / "bot.log"

    def token_available(self) -> bool:
        if os.environ.get("LICHESS_BOT_TOKEN"):
            return True
        if sys.platform == "darwin" and shutil.which("security"):
            r = subprocess.run(["security", "find-generic-password", "-a", os.environ.get("USER", ""), "-s", "lichess-bot-token"], capture_output=True, timeout=10)
            return r.returncode == 0                                              # (without -w: only whether the item exists, the token is not read)
        return False

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def tail(self, n=40) -> list[str]:
        try:
            lines = self.log.read_text(errors="replace").splitlines()
        except OSError:
            return []
        return lines[-n:]

    def status(self) -> dict:
        installed = self.launcher.is_file() and os.access(self.launcher, os.X_OK)
        return {"installed": installed, "token": self.token_available() if installed else False, "running": self.running(), "log": self.tail(), "dir": str(self.dir)}

    def start(self) -> str | None:
        """Returns None when started, else the reason it was not."""
        with self._lock:
            if self.running():
                return "the bot is already running"
            if not (self.launcher.is_file() and os.access(self.launcher, os.X_OK)):
                return "the bot is not installed (see docs/lichess-bot.md)"
            if not self.token_available():
                return "no token: set LICHESS_BOT_TOKEN in the terminal where MeChess was started, or store it in the Keychain (docs/lichess-bot.md)"
            self.log.parent.mkdir(parents=True, exist_ok=True)
            self.proc = subprocess.Popen([str(self.launcher)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, start_new_session=True)
            return None

    def stop(self) -> bool:
        with self._lock:
            if not self.running():
                return False
            try:
                os.killpg(self.proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(self.proc.pid, signal.SIGKILL)
            return True

    def close(self):
        self.stop()
