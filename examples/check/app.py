"""A plain Python app for @wordplus/realtime end-to-end check (its test/e2e/check.mjs, ``--app python``), on the
standard library HTTP server: ``.venv/bin/python examples/check/app.py 17421``. The same app as the Node and
PHP ones: the package routes for the user its page names (X-User, which a real app takes from its session), its page
and the two files it serves, and /check/emit for the check to emit through it."""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from wordplus_realtime import Realtime  # noqa: E402

realtime = Realtime.from_environment(
    server=os.environ.get("WORDPLUS_REALTIME_SERVER", "https://ws.wordplus.cloud"),
    api=os.environ.get("WORDPLUS_REALTIME_API", "https://rest.wordplus.cloud"),
    profile=lambda user: {"name": "User " + str(user)},
)
realtime.room("order:{id}", lambda user, p: str(user) == p["id"], history=10)
realtime.room("room:{id}", lambda user: user is not None, presence=True, emit=["typing"])
realtime.calls("support:{id}", lambda user: True)
# User 42 hosts the shop shows. Everyone else watches, a visitor who is not signed in too.
realtime.streams("show:{id}", lambda user: "host" if str(user) == "42" else "viewer", reactions=True)

STATIC = Path(os.environ.get("CHECK_STATIC", "."))
ASSETS = Path(os.environ.get("CHECK_ASSETS", "."))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        if os.environ.get("APP_LOG"):
            super().log_message(*args)

    def send(self, status, body, kind="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def body(self):
        return self.rfile.read(int(self.headers.get("Content-Length") or 0))

    def do_POST(self):
        path = self.path.split("?")[0]
        if path.startswith("/api/realtime/"):
            status, answer = realtime.answer_request("POST", self.headers.get("Content-Type", ""), path.rsplit("/", 1)[-1], self.body(), self.headers.get("X-User"))
            return self.send(status, json.dumps(answer, separators=(",", ":")).encode())
        if path == "/check/emit":
            event = json.loads(self.body())
            realtime.to(event.get("rooms", [])).to_user(event.get("users", [])).emit(event["event"], event.get("data"))
            return self.send(200, b'{"ok":true}')
        self.send(404, b"{}")

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/":
            file = STATIC / "index.html"
        elif path in ("/realtime-worker.js", "/realtime-rooms.min.js", "/realtime-rooms-e2ee.worker.js", "/realtime-ui.min.js"):
            file = ASSETS / path[1:]
        else:
            file = STATIC / path.lstrip("/").replace("..", "")
        if not file.is_file():
            return self.send(404, b"")
        self.send(200, file.read_bytes(), "text/html" if file.suffix == ".html" else "text/javascript")


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1]) if len(sys.argv) > 1 else 17421), Handler).serve_forever()
