"""The package's command, as an app runs it: in the app's folder, with no terminal to ask in."""

import hashlib
import hmac
import http.server
import json
import os
import re
import threading

import pytest

from wordplus_realtime.__main__ import main
from wordplus_realtime.realtime import PUBLISH_LABEL

KEYS = {"WORDPLUS_SITE": "s1500000007", "WORDPLUS_SECRET": "the-secret", "WORDPLUS_LOCAL_KEY": "ab" * 32}


@pytest.fixture(autouse=True)
def in_a_folder(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for name in list(os.environ):
        if name.startswith("WORDPLUS_"):
            monkeypatch.delenv(name)
    return tmp_path


def serve(answer):
    """A server answering ``answer(method, path, headers)`` with its status and body."""

    class Handler(http.server.BaseHTTPRequestHandler):
        def respond(self):
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            status, body = answer(self.command, self.path, self.headers)
            self.send_response(status)
            self.end_headers()
            if body is not None and self.command != "HEAD":
                self.wfile.write(json.dumps(body).encode())

        do_GET = do_POST = do_HEAD = respond

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return "http://127.0.0.1:" + str(server.server_address[1])


def test_init_writes_the_keys_and_a_local_key_made_for_the_app(in_a_folder, capsys):
    (in_a_folder / ".gitignore").write_text(".env\n")

    assert main(["init", "--app", "s1500000007", "--secret", "the-secret"]) == 0

    env = (in_a_folder / ".env").read_text()
    assert "WORDPLUS_SITE=s1500000007\n" in env
    assert "WORDPLUS_SECRET=the-secret\n" in env
    local = re.search(r"WORDPLUS_LOCAL_KEY=([0-9a-f]{64})\n", env)
    assert local
    out = capsys.readouterr().out
    assert "wordplus-realtime check" in out
    assert "the-secret" not in out and local[1] not in out
    assert "isn't in .gitignore" not in out


def test_init_changes_nothing_already_there_the_local_key_above_all(in_a_folder):
    before = "WORDPLUS_SITE=s1\nWORDPLUS_SECRET=old\nWORDPLUS_LOCAL_KEY=" + "ab" * 32 + "\n"
    (in_a_folder / ".env").write_text(before)

    main(["init", "--app", "s2", "--secret", "new"])

    assert (in_a_folder / ".env").read_text() == before


def test_init_adds_what_a_file_lacks_on_a_line_of_its_own(in_a_folder):
    (in_a_folder / ".env").write_text("OTHER=1")

    main(["init", "--app=s1", "--secret=x"])

    assert (in_a_folder / ".env").read_text().startswith("OTHER=1\nWORDPLUS_SITE=s1\nWORDPLUS_SECRET=x\nWORDPLUS_LOCAL_KEY=")


def test_init_keeps_the_secret_out_of_git_on_a_line_of_its_own_and_once(in_a_folder, capsys):
    (in_a_folder / ".gitignore").write_text("__pycache__")

    main(["init", "--app", "s1", "--secret", "x"])

    assert "added    .env to .gitignore" in capsys.readouterr().out
    assert (in_a_folder / ".gitignore").read_text() == "__pycache__\n.env\n"

    main(["init", "--app", "s1", "--secret", "x"])
    assert (in_a_folder / ".gitignore").read_text() == "__pycache__\n.env\n"


def test_init_starts_a_gitignore_where_there_is_none(in_a_folder):
    main(["init", "--app", "s1", "--secret", "x"])

    assert (in_a_folder / ".gitignore").read_text() == ".env\n"


def test_check_says_each_key_that_is_missing_or_wrong_and_what_to_do(monkeypatch, capsys):
    monkeypatch.setenv("WORDPLUS_LOCAL_KEY", "short")

    assert main(["check"]) == 1

    out = capsys.readouterr().out
    assert "WORDPLUS_SITE is missing" in out
    assert "WORDPLUS_SECRET is missing" in out
    assert "WORDPLUS_LOCAL_KEY isn't 64 hex characters" in out
    assert "openssl rand -hex 32" in out


def test_check_reads_the_env_file_a_quoted_value_and_a_comment_left_out(in_a_folder, capsys):
    (in_a_folder / ".env").write_text('WORDPLUS_SITE="s1"  # the key\n')

    main(["check"])

    assert "WORDPLUS_SITE is s1\n" in capsys.readouterr().out


def test_check_asks_the_cloud_with_a_signature_the_server_part_makes_and_never_says_the_secret(monkeypatch, capsys):
    asked = []

    def answer(method, path, headers):
        asked.append((method, path, headers))
        return 200, {"ok": True, "connections": {"now": 3, "limit": 1000}}

    monkeypatch.setenv("WORDPLUS_REALTIME_API", serve(answer))
    for name, value in KEYS.items():
        monkeypatch.setenv(name, value)

    assert main(["check"]) == 0

    method, path, headers = asked[0]
    assert (method, path) == ("GET", "/wordplus/realtime/usage")
    key = hmac.new(KEYS["WORDPLUS_SECRET"].encode(), PUBLISH_LABEL.encode(), hashlib.sha256).digest()
    line = headers["X-WordPlus-Timestamp"] + "\nGET\n/wordplus/realtime/usage\n" + hashlib.sha256(b"").hexdigest()
    assert headers["X-WordPlus-Signature"] == hmac.new(key, line.encode(), hashlib.sha256).hexdigest()
    out = capsys.readouterr().out
    assert "3 connected now of 1000" in out
    assert "the-secret" not in out


@pytest.mark.parametrize("error, word", [("unknown_site", "WORDPLUS_SITE"), ("bad_signature", "WORDPLUS_SECRET"), ("stale_signature", "clock"), ("not_included", "plan")])
def test_check_says_what_a_refusal_means(monkeypatch, capsys, error, word):
    monkeypatch.setenv("WORDPLUS_REALTIME_API", serve(lambda method, path, headers: (401, {"ok": False, "error": error})))
    for name, value in KEYS.items():
        monkeypatch.setenv(name, value)

    assert main(["check"]) == 1
    assert word in capsys.readouterr().out


def app_at(keys, file):
    def answer(method, path, headers):
        if path == "/wordplus/realtime/usage":
            return 200, {"ok": True}
        if method == "POST" and path == "/api/realtime/keys":
            return keys
        if path == "/api/realtime/files/realtime-worker.js":
            return file, None
        return 404, None

    return serve(answer)


def checked(monkeypatch, address):
    monkeypatch.setenv("WORDPLUS_REALTIME_API", address)
    for name, value in KEYS.items():
        monkeypatch.setenv(name, value)
    return main(["check", address])


def test_check_passes_routes_that_answer(monkeypatch, capsys):
    assert checked(monkeypatch, app_at((200, {"keys": [], "app": KEYS["WORDPLUS_SITE"]}), 200)) == 0

    out = capsys.readouterr().out
    assert "the keys route answers" in out
    assert "the browser files are served" in out


def test_check_passes_djangos_csrf_check_in_front_of_the_keys_route(monkeypatch, capsys):
    assert checked(monkeypatch, app_at((403, "CSRF verification failed. Request aborted."), 200)) == 0

    out = capsys.readouterr().out
    assert "behind Django's CSRF check" in out
    assert "asks for a sign-in" not in out


def test_check_says_where_the_routes_go_when_nothing_is_there(monkeypatch, capsys):
    assert checked(monkeypatch, app_at((404, None), 404)) == 1
    assert "wordplus_realtime.fastapi.router" in capsys.readouterr().out


def test_check_says_a_sign_in_in_front_of_the_routes(monkeypatch, capsys):
    checked(monkeypatch, app_at((401, None), 200))

    assert "asks for a sign-in" in capsys.readouterr().out


def test_check_says_when_the_server_reads_other_keys_than_these(monkeypatch, capsys):
    checked(monkeypatch, app_at((200, {"keys": [], "app": "s-other"}), 200))

    assert "your server reads other values" in capsys.readouterr().out


def test_check_looks_under_the_base_it_is_given(monkeypatch, capsys):
    asked = []

    def answer(method, path, headers):
        asked.append(path)
        return 200, {"ok": True, "app": KEYS["WORDPLUS_SITE"]}

    address = serve(answer)
    monkeypatch.setenv("WORDPLUS_REALTIME_API", address)
    for name, value in KEYS.items():
        monkeypatch.setenv(name, value)

    assert main(["check", address, "--base", "/hooks/rt"]) == 0
    assert "/hooks/rt/keys" in asked and "/hooks/rt/files/realtime-worker.js" in asked


def test_with_no_command_it_says_what_it_does_and_fails_on_one_it_does_not_know(capsys):
    assert main([]) == 0
    assert "wordplus-realtime init" in capsys.readouterr().out
    assert main(["nonsense"]) == 1


@pytest.mark.parametrize("args", [["--help"], ["-h"], ["help"], ["init", "--help"], ["check", "-h"]])
def test_help_says_what_it_does_and_does_nothing(in_a_folder, capsys, args):
    assert main(args) == 0

    assert "wordplus-realtime init" in capsys.readouterr().out
    assert list(in_a_folder.iterdir()) == []
