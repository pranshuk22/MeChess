"""A local server must not be a door for other websites. Two checks on every request:

* the Host header must be one of ours (a page on another domain that resolves to 127.0.0.1, "DNS rebinding", sends its own host name);
* a request that changes something (not GET/HEAD/OPTIONS) with an Origin header must come from our own origin.
Both answer 403. Requests without an Origin (command-line tools, the test client) are fine for the second check: browsers always send one."""
import hmac
from http.cookies import SimpleCookie

from starlette.responses import JSONResponse, PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

SAFE = {"GET", "HEAD", "OPTIONS"}


class LocalOnly:
    def __init__(self, app: ASGIApp, hosts: set[str], origins: set[str]):
        self.app, self.hosts, self.origins = app, hosts, origins

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] in ("http", "websocket"):
            headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
            if headers.get("host", "").lower() not in self.hosts:
                return await self._refuse(scope, receive, send, "Forbidden host")
            origin = headers.get("origin")
            changes = scope["type"] == "websocket" or scope["method"] not in SAFE                     # a WebSocket can send commands: its handshake is checked like a write
            if changes and origin is not None and origin.lower() not in self.origins:
                return await self._refuse(scope, receive, send, "Forbidden origin")
        await self.app(scope, receive, send)

    @staticmethod
    async def _refuse(scope, receive, send, text):
        if scope["type"] == "websocket":                                       # a WebSocket handshake is refused by closing it (a plain response is not allowed there)
            await receive()
            return await send({"type": "websocket.close", "code": 1008})
        return await PlainTextResponse(text, status_code=403)(scope, receive, send)


def allowed(host: str, port: int, extra_hosts=(), extra_origins=()):
    hosts = {f"{h}:{port}" for h in ("127.0.0.1", "localhost", "[::1]")} | set(extra_hosts)
    origins = {f"http://{h}" for h in hosts} | set(extra_origins)
    return hosts, origins


COOKIE = "mechess_session"
OPEN = ("/api/health", "/api/session")                                         # reachable without the key: the page needs them to ask for it
CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; "
       "frame-ancestors 'none'; base-uri 'none'; form-action 'self'")


def presented(headers: dict) -> str:
    """The key a request carries: the session cookie, or the X-MeChess-Token header (tools and tests)."""
    c = SimpleCookie()
    try:
        c.load(headers.get("cookie", ""))
    except Exception:
        pass
    return headers.get("x-mechess-token") or (c[COOKIE].value if COOKIE in c else "")


def key_ok(headers: dict, token: str | None) -> bool:
    return token is None or hmac.compare_digest(presented(headers).encode(), token.encode())


class TokenAuth:
    """A browser is kept out by the Host/Origin checks; another program on the same computer is kept out by a key. The key is made when the app starts, printed in the
    address that opens the app, and turned into an HttpOnly cookie by `POST /api/session`. Every other `/api` request (and the WebSocket) needs it."""

    def __init__(self, app: ASGIApp, token: str | None):
        self.app, self.token = app, token

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if self.token is not None and scope["type"] in ("http", "websocket") and scope["path"].startswith("/api") and scope["path"] not in OPEN:
            headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
            if not key_ok(headers, self.token):
                if scope["type"] == "websocket":
                    await receive()
                    return await send({"type": "websocket.close", "code": 1008})
                return await JSONResponse({"detail": "not signed in: open the address printed when MeChess started"}, status_code=401)(scope, receive, send)
        await self.app(scope, receive, send)


class SecurityHeaders:
    """No other site may frame the app (clickjacking of the import and delete buttons), and the page may only load its own files."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def wrapped(message):
            if message["type"] == "http.response.start":
                h = message.setdefault("headers", [])
                present = {k.lower() for k, _ in h}
                for k, v in ((b"content-security-policy", CSP.encode()), (b"x-frame-options", b"DENY"), (b"x-content-type-options", b"nosniff"), (b"referrer-policy", b"no-referrer")):
                    if k not in present:
                        h.append((k, v))
            await send(message)
        await self.app(scope, receive, wrapped)
