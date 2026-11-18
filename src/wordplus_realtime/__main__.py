"""The package's command, for the first minutes of an app and for when something doesn't connect:

    wordplus-realtime init                your app's key and secret into .env, and a local key made for you
    wordplus-realtime check [address]     whether your keys work with WordPlus Cloud, and your routes at that address

``python -m wordplus_realtime`` is the same.
"""

from __future__ import annotations

import getpass
import hashlib
import hmac
import json
import os
import pathlib
import re
import secrets
import sys
import time
import urllib.error
import urllib.request
from typing import Dict, List, Optional, Tuple

from .realtime import API_SERVER, PUBLISH_LABEL

USAGE = """Usage:
  wordplus-realtime init [--app <key>] [--secret <secret>]   set your app up here
  wordplus-realtime check [address] [--base <path>]          see whether it works, such as http://localhost:8000"""
ENV = pathlib.Path(".env")


def _flags(args: List[str]) -> Dict[str, str]:
    """``--app value`` and ``--app=value``, as a dict."""
    out: Dict[str, str] = {}
    rest = iter(args)
    for arg in rest:
        match = re.fullmatch(r"--([a-z-]+)(?:=(.*))?", arg)
        if match:
            out[match[1]] = match[2] if match[2] is not None else next(rest, "")
    return out


def _env_of(path: pathlib.Path) -> Dict[str, str]:
    """What a .env file sets, as far as this command needs: ``NAME=value``, with quotes or not, a comment after a value left out."""
    if not path.exists():
        return {}
    out: Dict[str, str] = {}
    for line in path.read_text().splitlines():
        match = re.match(r"^\s*(?:export\s+)?([A-Z0-9_]+)\s*=\s*(.*)$", line)
        if match:
            out[match[1]] = re.sub(r"^(['\"])(.*)\1$", r"\2", re.sub(r"\s+#.*$", "", match[2]).strip())
    return out


def _ignored(name: str) -> bool:
    """Whether .gitignore covers a file, as far as its plain lines say: ``.env*`` and the like."""
    path = pathlib.Path(".gitignore")
    if not path.exists():
        return False
    for line in path.read_text().splitlines():
        pattern = line.strip().lstrip("/")
        if pattern and not pattern.startswith("#") and re.fullmatch(re.escape(pattern).replace(r"\*", ".*"), name):
            return True
    return False


def _ask(question: str, *, hidden: bool = False) -> str:
    if not sys.stdin.isatty():
        return ""
    return (getpass.getpass(question) if hidden else input(question)).strip()


def init(given: Dict[str, str]) -> int:
    have = _env_of(ENV)
    print("Your app's key and secret are on its page in your WordPlus Cloud account: Apps → your app.")
    print("Your subscription and its Apps page: https://www.wordplus.cloud/pricing#apps\n")

    values = {
        "WORDPLUS_SITE": have.get("WORDPLUS_SITE") or given.get("app") or _ask("App key (public, such as s1500000007): "),
        "WORDPLUS_SECRET": have.get("WORDPLUS_SECRET") or given.get("secret") or _ask("App secret (stays on your server): ", hidden=True),
        # It seals what goes through the cloud, which never sees it, so it is made here. A new one could not open what the old one sealed.
        "WORDPLUS_LOCAL_KEY": have.get("WORDPLUS_LOCAL_KEY") or secrets.token_hex(32),
    }

    missing = [name for name in values if name not in have]
    if missing:
        old = ENV.read_text() if ENV.exists() else ""
        lead = "\n" if old and not old.endswith("\n") else ""
        with ENV.open("a") as env:
            env.write(lead + "".join(name + "=" + values[name] + "\n" for name in missing))
        print("\n  wrote    " + ", ".join(missing) + " into .env")
    else:
        print("\n  kept     .env, which has all three")
    if "WORDPLUS_LOCAL_KEY" in missing:
        print("           Keep WORDPLUS_LOCAL_KEY as long as the app, the same on each of its servers: what it sealed needs it to open.")
    if not _ignored(".env"):
        ignore = pathlib.Path(".gitignore")
        old = ignore.read_text() if ignore.exists() else ""
        with ignore.open("a") as lines:
            lines.write(("\n" if old and not old.endswith("\n") else "") + ".env\n")
        print("  added    .env to .gitignore: the secret and the local key must stay out of git.")

    print("\nNext: declare your rooms and mount the routes, as the guide for your framework shows: https://docs.wordplus.cloud/")
    if not values["WORDPLUS_SITE"] or not values["WORDPLUS_SECRET"]:
        print("\nThen fill in what is empty in .env.")
    print("\nThen see that it all works, with your app running:\n\n  wordplus-realtime check http://localhost:8000\n")
    return 0


class _Checks:
    def __init__(self) -> None:
        self.failures = 0

    def passed(self, text: str) -> None:
        print("  ok    " + text)

    def failed(self, text: str) -> None:
        self.failures += 1
        print("  FAIL  " + text)


def _request(url: str, *, method: str = "GET", headers: Optional[Dict[str, str]] = None, body: Optional[bytes] = None) -> Optional[Tuple[int, bytes]]:
    """A request's status and body, a refusal's too; None when nothing answers."""
    request = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310 (an address the developer gave, or the cloud's)
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        try:
            return error.code, error.read()
        except OSError:
            return error.code, b""
    except OSError:
        return None


def _json_of(raw: bytes) -> Dict[str, object]:
    try:
        answer = json.loads(raw)
    except ValueError:
        return {}
    return answer if isinstance(answer, dict) else {}


def _check_cloud(checks: _Checks, app: str, secret: str, api: str) -> None:
    """What the signed usage route answers says whether WordPlus Cloud knows this app and its secret, and it changes nothing."""
    print("\nWordPlus Cloud")
    path = "/wordplus/realtime/usage"
    timestamp = str(int(time.time()))
    key = hmac.new(secret.encode(), PUBLISH_LABEL.encode(), hashlib.sha256).digest()
    signature = hmac.new(key, (timestamp + "\nGET\n" + path + "\n" + hashlib.sha256(b"").hexdigest()).encode(), hashlib.sha256).hexdigest()

    answered = _request(api + path, headers={"X-WordPlus-Site": app, "X-WordPlus-Timestamp": timestamp, "X-WordPlus-Signature": signature})
    if answered is None:
        checks.failed("could not reach " + api + ". Check this machine's connection to it.")
        return
    status, raw = answered
    answer = _json_of(raw)
    if status == 200 and answer.get("ok"):
        connections = answer.get("connections") if isinstance(answer.get("connections"), dict) else {}
        now, limit = connections.get("now"), connections.get("limit")  # type: ignore[union-attr]
        told = "" if now is None else " (" + str(now) + " connected now" + (" of " + str(limit) if limit else "") + ")"
        checks.passed("it knows your app, and your secret is right" + told)
        return
    refusals = {
        "unknown_site": "it doesn't know this app key. Check WORDPLUS_SITE against your app's page in WordPlus Cloud (Apps).",
        "bad_signature": "your secret is wrong for this app. Check WORDPLUS_SECRET against your app's page in WordPlus Cloud (Apps).",
        "stale_signature": "this machine's clock is off by more than five minutes.",
        "not_included": "the plan of this app does not include realtime.",
    }
    error = answer.get("error")
    checks.failed(refusals.get(str(error)) or "it answered " + str(status) + (" (" + str(error) + ")" if error else "") + ".")


def _check_routes(checks: _Checks, address: str, app: str, base: str) -> None:
    """The routes as a page asks them, with no user: the keys route names the app, and GET serves the browser files."""
    print("\nYour routes at " + address + base)
    keys = _request(address + base + "/keys", method="POST", headers={"Content-Type": "application/json"}, body=b'{"labels":[]}')
    if keys is None:
        checks.failed("nothing answers at " + address + ". Is your app running there?")
        return
    status, raw = keys
    named = _json_of(raw).get("app")
    if status == 200 and named:
        if app and named != app:
            checks.failed("they name the app " + str(named) + ", and your keys here say " + app + ": your server reads other values than these.")
        else:
            checks.passed("the keys route answers, naming your app")
    elif status == 200:
        checks.failed("the keys route answers with no app key: update the package on your server.")
    elif status == 403 and b"CSRF" in raw:
        # Django's CSRF check, which a page passes with the token {% wordplus_realtime %} gives it, and this command has none.
        checks.passed("the keys route is there, behind Django's CSRF check, which your pages pass with {% wordplus_realtime %}")
    elif status in (401, 403):
        checks.failed("the keys route answered " + str(status) + ". Something in front of it asks for a sign-in: let " + base + "/* through with the session.")
    else:
        checks.failed("the keys route answered " + str(status) + ". Your framework's guide says where the routes go, under " + base + ": Django includes wordplus_realtime.django.routes, FastAPI wordplus_realtime.fastapi.router, Flask wordplus_realtime.flask.")

    file = _request(address + base + "/files/realtime-worker.js", method="HEAD")
    if file is not None and file[0] == 200:
        checks.passed("the browser files are served")
    else:
        checks.failed("the browser files answered " + (str(file[0]) if file else "nothing") + ". Your routes serve them on GET under " + base + "/files/. An app that serves them itself has `files=False`, and this one can pass.")


def check(address: Optional[str], base: str) -> int:
    env = {**_env_of(ENV), **os.environ}
    app = env.get("WORDPLUS_SITE", "")
    secret = env.get("WORDPLUS_SECRET", "")
    local_key = env.get("WORDPLUS_LOCAL_KEY", "")
    checks = _Checks()
    print("Your keys")

    if re.fullmatch(r"[A-Za-z0-9._-]{2,}", app):
        checks.passed("WORDPLUS_SITE is " + app)
    else:
        checks.failed("WORDPLUS_SITE is missing. It is your app's key, on its page in WordPlus Cloud (Apps).")
    if secret:
        checks.passed("WORDPLUS_SECRET is there")
    else:
        checks.failed("WORDPLUS_SECRET is missing. It is your app's secret, on its page in WordPlus Cloud (Apps).")
    if re.fullmatch(r"[0-9a-f]{64}", local_key):
        checks.passed("WORDPLUS_LOCAL_KEY is 64 hex characters")
    else:
        checks.failed(("WORDPLUS_LOCAL_KEY is missing." if not local_key else "WORDPLUS_LOCAL_KEY isn't 64 hex characters.") + " Make one with `openssl rand -hex 32`, and keep it as long as the app.")

    if app and secret:
        _check_cloud(checks, app, secret, (env.get("WORDPLUS_REALTIME_API") or API_SERVER).rstrip("/"))
    if address:
        _check_routes(checks, address.rstrip("/"), app, base)
    else:
        print("\nGive the address your app runs on to check your routes too: wordplus-realtime check http://localhost:8000")

    print("\n" + str(checks.failures) + " to fix." if checks.failures else "\nAll good.")
    return 1 if checks.failures else 0


def main(argv: Optional[List[str]] = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    command = args[0] if args else None
    rest = args[1:]
    if command in ("help", "--help", "-h") or "--help" in rest or "-h" in rest:
        print(USAGE)
        return 0
    if command == "init":
        return init(_flags(rest))
    if command == "check":
        return check(rest[0] if rest and not rest[0].startswith("--") else None, _flags(rest).get("base", "/api/realtime"))
    print(USAGE)
    return 0 if command is None else 1


if __name__ == "__main__":
    sys.exit(main())
