"""A local server must not be a door for other websites. Two checks on every request:

* the Host header must be one of ours (a page on another domain that resolves to 127.0.0.1, "DNS rebinding", sends its own host name);
* a request that changes something (not GET/HEAD/OPTIONS) with an Origin header must come from our own origin.
Both answer 403. Requests without an Origin (command-line tools, the test client) are fine for the second check: browsers always send one."""
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

SAFE = {"GET", "HEAD", "OPTIONS"}


class LocalOnly:
    def __init__(self, app: ASGIApp, hosts: set[str], origins: set[str]):
        self.app, self.hosts, self.origins = app, hosts, origins

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] in ("http", "websocket"):
            headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
            if headers.get("host", "").lower() not in self.hosts:
                return await PlainTextResponse("Forbidden host", status_code=403)(scope, receive, send)
            origin = headers.get("origin")
            if scope["type"] == "http" and scope["method"] not in SAFE and origin is not None and origin.lower() not in self.origins:
                return await PlainTextResponse("Forbidden origin", status_code=403)(scope, receive, send)
        await self.app(scope, receive, send)


def allowed(host: str, port: int, extra_hosts=(), extra_origins=()):
    hosts = {f"{h}:{port}" for h in ("127.0.0.1", "localhost", "[::1]")} | set(extra_hosts)
    origins = {f"http://{h}" for h in hosts} | set(extra_origins)
    return hosts, origins
