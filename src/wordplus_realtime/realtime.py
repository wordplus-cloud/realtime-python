"""WordPlus Cloud's realtime SDK for an app's own server in Python, outside WordPress: the rooms the app owns, declared
once by pattern with what they are; what the app's server sends them and its users; who is online; and the routes its
browsers ask. @wordplus/realtime's server part, answering the browser exactly as it does.

    realtime = Realtime.from_environment(profile=lambda user: {"name": name_of(user)})
    realtime.room("order:{id}", lambda user, p: owns_order(user, p["id"]), history=20)
    realtime.room("chat:{a}:{b}", lambda user, p: str(user) in (p["a"], p["b"]), presence=True, history=500, emit=["message", "typing"])

    # POST /api/realtime/auth, /calls, /keys and /webhook: answer_request(), or the Django and FastAPI routes.

    realtime.to("order:42").emit("updated", {"status": "paid"})
    realtime.to_user(42).emit("notice", {"text": "Your order shipped"})

A user is an id the app gives: an int or a str, or None for nobody. In calls, an id of digits is a number and any other
id of up to 64 characters, with no space, is taken as it is. Every rule and callback is called with as many of its arguments as it takes, so
``lambda user: …`` and ``lambda user, params, room: …`` both work.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import inspect
import json
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import warnings
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple, Union

from .keys import MAX_LABELS, RESERVED, GenerationStore, Keys, UserId, base64url, day_of, dumps, unbase64url, valid_label
from .patterns import Patterns, valid_room

# The browser files the package carries, synced from @wordplus/realtime (its scripts/sync-files.mjs), with files.json:
# their version, the folder they are served from, and each one's SHA-256.
FILES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "files")
_manifest: Optional[Dict[str, Any]] = None


def files_manifest() -> Dict[str, Any]:
    """The browser files' version and their names: ``{"version": …, "files": {name: sha256}}``."""
    global _manifest
    if _manifest is None:
        with open(os.path.join(FILES_DIR, "files.json"), encoding="utf-8") as f:
            _manifest = json.load(f)
    return _manifest

VERSION = "1.0.0"

SERVER = "https://ws.wordplus.cloud"
API_SERVER = "https://rest.wordplus.cloud"
PATH = "/websocket"

# The app's routes: the browser's three, then the one WordPlus Cloud posts its webhooks to.
ROUTES = ("auth", "calls", "keys", "webhook")

TOKEN_LABEL = "wordplus-realtime channels v1"
PUBLISH_LABEL = "wordplus-realtime publish v1"
WEBHOOK_LABEL = "wordplus-realtime webhook v1"
CALLS_LABEL = "wordplus-realtime calls v1"
CALL_KEY_LABEL = "wordplus-realtime call key v1"

# A live stream's grant: Easy Stream's key label and audience, its claims in this order (Easy Stream's protocol).
GRANT_KEY_LABEL = "easy-stream grant v1"
GRANT_AUDIENCE = "easy-stream"
# What a host does to someone else in a group call from its call screen: the calls route's ``moderate``.
MODERATION_ACTS = ("mute", "speak", "listen", "remove")

CLAIM_ORDER = ("iss", "aud", "str", "role", "sub", "name", "avatar", "chat", "mod", "src", "q", "stage", "offline", "links", "fresh", "people", "reactions", "org", "iat", "exp")
# A stream's grant lives ten minutes, as Easy Stream's do; the page asks for another as one runs out.
STREAM_TTL = 600
# A live stream's name: a room's without an underscore, as the cloud takes it in a grant's ``str``.
_STREAM_NAME = re.compile(r"^[A-Za-z0-9\-=@,.;:]{1,128}$")
_STREAM_USER = re.compile(r"^[\w.@-]{1,64}$", re.ASCII)

AUDIENCE = "wordplus-realtime"
CALL_AUDIENCE = "wordplus-realtime call"
LINE_AUDIENCE = "wordplus-realtime line"
ROOM_AUDIENCE = "wordplus-realtime room"
IDENTITY_AUDIENCE = "wordplus-realtime identity"

TOKEN_TTL = 21600
MAX_TTL = 86400
CALL_TTL = 21600
MAX_ROOMS = 100
# The cloud keeps at most this many events a room, for at most this many days: 5 minutes, for a page that reconnects.
MAX_HISTORY = 1000
MAX_HISTORY_DAYS = 5 / (24 * 60)
# Events in one batch request, and a webhook's signature's window.
BATCH = 100
WEBHOOK_WINDOW = 300

Http = Callable[[str, str, Dict[str, str], Optional[bytes]], Tuple[int, bytes]]

log = logging.getLogger("wordplus_realtime")


class RealtimeError(Exception):
    """A refusal from the realtime server, or a request that didn't reach it: ``code`` says which."""

    def __init__(self, code: str, status: int = 0) -> None:
        super().__init__("The realtime server refused the request: " + code)
        self.code = code
        self.status = status


def _path_of(address: str) -> str:
    """An address's path: itself without its query, or a full address's path part."""
    if re.match(r"^https?://", address, re.IGNORECASE):
        return urllib.parse.urlsplit(address).path
    return re.split(r"[?#]", address, maxsplit=1)[0]


def _known(user: Any) -> bool:
    """A user the app knows: any id but None, '' and 0."""
    return user is not None and user != "" and user != 0 and user != "0" and not isinstance(user, bool)


def _call_user(user: Any) -> Optional[UserId]:
    """A user as the realtime server's calls take them (its inc/calls/p2p/users.ts): a number for an id of digits, else
    the id of text the app gives, up to 64 characters with no space or control character. 0 is nobody."""
    if isinstance(user, bool):
        return None
    if isinstance(user, int):
        return user if user != 0 and abs(user) < 2**53 else None
    if not isinstance(user, str) or re.fullmatch(r"[^\s\x00-\x1f\x7f]{1,64}", user) is None:
        return None
    if re.fullmatch(r"-?[1-9][0-9]*", user) and abs(int(user)) < 2**53:
        return int(user)
    return None if user == "0" else user


def _id_part(user: UserId) -> str:
    """A user in what this server joins with ``|`` to make a key or a proof: a number as its digits, as always, and an id of
    text with its ``%`` and ``|`` escaped, so no two pairs of people make the same string, as the Node and PHP packages do."""
    return str(user) if isinstance(user, int) else user.replace("%", "%25").replace("|", "%7C")


def _valid_attempt(attempt: Any) -> bool:
    """An attempt at a call, as a page names it."""
    return isinstance(attempt, str) and re.fullmatch(r"[A-Za-z0-9_-]{8,64}", attempt) is not None


def _pair_of(pair: Any) -> Optional[Tuple[UserId, UserId]]:
    """A call's two people as a page names them: two different users, or None."""
    if not isinstance(pair, (list, tuple)) or len(pair) != 2:
        return None
    first, second = _call_user(pair[0]), _call_user(pair[1])
    return (first, second) if first is not None and second is not None and first != second else None


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, int(value)))


def _jwt(claims: Dict[str, Any], key: bytes) -> str:
    signing = base64url(b'{"alg":"HS256","typ":"JWT"}') + "." + base64url(dumps(claims).encode("utf-8"))
    return signing + "." + base64url(hmac.new(key, signing.encode("ascii"), hashlib.sha256).digest())


def stream_grant(claims: Dict[str, Any], key: bytes) -> str:
    """Easy Stream's grant: an HS256 JWT of the claims in the protocol's order (CLAIM_ORDER), none left None, so every
    language signs the same claims to the same token (spec/stream-grants.json, Easy Stream's own vectors)."""
    return _jwt({name: claims[name] for name in CLAIM_ORDER if claims.get(name) is not None}, key)


def _flexible(fn: Callable[..., Any]) -> Callable[..., Any]:
    """A callback called with as many of its arguments as it takes, as JavaScript and PHP call theirs."""
    try:
        parameters = list(inspect.signature(fn).parameters.values())
    except (TypeError, ValueError):
        return fn
    if any(p.kind == p.VAR_POSITIONAL for p in parameters):
        return fn
    count = sum(1 for p in parameters if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD))
    return lambda *args: fn(*args[:count])


def _names(value: Any) -> Union[str, List[str]]:
    """Event names a room's option lists: '*', or names."""
    if value == "*":
        return "*"
    return [str(name) for name in value] if isinstance(value, (list, tuple)) else []


def _days(value: Any) -> float:
    """How long a room keeps its history in days, a part of one as given, held to the cloud's limit, and the limit when not above 0."""
    try:
        days = float(value)
    except (TypeError, ValueError):
        return MAX_HISTORY_DAYS
    return min(days, MAX_HISTORY_DAYS) if days > 0 else MAX_HISTORY_DAYS


def _normalized(options: Dict[str, Any]) -> Dict[str, Any]:
    """A room's options as its rule gave them, with their defaults and the cloud's limits."""
    given = options.get("history")
    history = None
    if isinstance(given, int) and not isinstance(given, bool) and given > 0:
        history = {"last": min(given, MAX_HISTORY), "days": MAX_HISTORY_DAYS}
    elif isinstance(given, dict) and int(given.get("last") or 0) > 0:
        history = {"last": min(int(given["last"]), MAX_HISTORY), "days": _days(given.get("days"))}
    public = bool(options.get("public"))
    seal = options.get("seal")
    return {
        "presence": bool(options.get("presence")),
        "count": bool(options.get("count")) or bool(options.get("presence")),
        "public": public,
        "seal": (not public) if seal is None else bool(seal),
        "history": history,
        "emit": _names(options.get("emit")),
        "webhook": _names(options.get("webhook")),
    }


def _short(options: Dict[str, Any], read_only: bool) -> Dict[str, Any]:
    """A room's options as a token carries them: ``p``, ``c``, ``h``, ``e``, ``w``, ``ro``, only those set."""
    out: Dict[str, Any] = {}
    if options["presence"]:
        out["p"] = 1
    if options["count"] and not options["presence"]:
        out["c"] = 1
    if options["history"] is not None:
        out["h"] = [options["history"]["last"], options["history"]["days"]]
    if options["emit"] == "*" or options["emit"]:
        out["e"] = options["emit"]
    if options["webhook"] == "*" or options["webhook"]:
        out["w"] = options["webhook"]
    if read_only:
        out["ro"] = 1
    return out


def _pack(value: Any, depth: int = 0) -> Any:
    """Binary parts of an event as ``{"$b": base64}``, as the browser's client carries them in JSON."""
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"$b": base64.b64encode(bytes(value)).decode("ascii")}
    if depth > 16:
        return value
    if isinstance(value, (list, tuple)):
        return [_pack(item, depth + 1) for item in value]
    if isinstance(value, dict):
        return {key: _pack(item, depth + 1) for key, item in value.items()}
    return value


def _unpack(value: Any, depth: int = 0) -> Any:
    if depth > 16:
        return value
    if isinstance(value, list):
        return [_unpack(item, depth + 1) for item in value]
    if isinstance(value, dict):
        if len(value) == 1 and isinstance(value.get("$b"), str):
            raw = unbase64url(value["$b"].replace("+", "-").replace("/", "_").rstrip("="))
            return value if raw is None else raw
        return {key: _unpack(item, depth + 1) for key, item in value.items()}
    return value


def _header(headers: Any, name: str) -> str:
    """A request's header, any case, from a dict or a framework's headers."""
    value = headers.get(name) if hasattr(headers, "get") else None
    if value is None and hasattr(headers, "items"):
        value = next((v for k, v in headers.items() if str(k).lower() == name.lower()), None)
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    return "" if value is None else str(value)


class Emitter:
    """Where an emit goes: rooms and users, and a tab that doesn't get it back. ``emit()`` sends it."""

    def __init__(self, realtime: "Realtime") -> None:
        self._realtime = realtime
        self._rooms: List[str] = []
        self._users: List[str] = []
        self._skip: Optional[str] = None

    def to(self, rooms: Union[str, Iterable[str]]) -> "Emitter":
        for room in [rooms] if isinstance(rooms, str) else rooms:
            if str(room) not in self._rooms:
                self._rooms.append(str(room))
        return self

    def to_user(self, users: Union[UserId, Iterable[UserId]]) -> "Emitter":
        for user in [users] if isinstance(users, (str, int)) else users:
            if _known(user) and str(user) not in self._users:
                self._users.append(str(user))
        return self

    def except_tab(self, tab: Optional[str]) -> "Emitter":
        """The tab whose action made the event (the browser's ``rt.tab``, sent as X-Realtime-Tab), which doesn't get it
        back."""
        if tab:
            self._skip = str(tab)
        return self

    def emit(self, event: str, data: Any = None, *, seal: bool = True) -> Dict[str, str]:
        """Sends the event: a sealed room's data sealed with its key, a user's with theirs, kept where a room's rule keeps
        history. The kept events' ids, by room. Raises RealtimeError with the server's reason."""
        return self._realtime.emit_event({"rooms": self._rooms, "users": self._users, "event": event, "data": data, "except": self._skip, "seal": seal})

    async def aemit(self, event: str, data: Any = None, *, seal: bool = True) -> Dict[str, str]:
        """emit(), from async code (FastAPI, Starlette, Django's async views), on a worker thread."""
        return await asyncio.to_thread(self.emit, event, data, seal=seal)


class RoomQueries:
    """A room as the realtime server holds it."""

    def __init__(self, realtime: "Realtime", room: str) -> None:
        self._realtime = realtime
        self.room = room
        self._path = "/wordplus/realtime/rooms/" + urllib.parse.quote(room, safe="")

    def count(self) -> int:
        """How many are in it: a presence room's members, else its connections."""
        return int(self._realtime.request("GET", self._path).get("count") or 0)

    def members(self) -> Dict[str, Any]:
        """A presence room's members, their info opened: the first 1,000, the count, and ``next`` to page on."""
        answer = self._realtime.request("GET", self._path + "?members=1")
        members = dict(answer["members"]) if isinstance(answer.get("members"), dict) else {"count": 0, "list": []}
        members["count"] = int(members.get("count") or 0)
        members["list"] = [{"id": str(m.get("id", "")), "info": self._realtime.opened(m.get("info"))} for m in members.get("list") or [] if isinstance(m, dict)]
        return members

    def history(self, *, before: Optional[str] = None, after: Optional[str] = None, limit: Optional[int] = None, days: Optional[int] = None) -> Dict[str, Any]:
        """A page of the room's history, opened, oldest first: the newest ``limit`` (50), or those before or after an
        event's id."""
        ask = {name: value for name, value in (("before", before), ("after", after), ("limit", limit), ("days", days)) if value is not None}
        answer = self._realtime.request("GET", self._path + "/history" + ("?" + urllib.parse.urlencode(ask) if ask else ""))
        events = []
        for e in answer.get("events") or []:
            if not isinstance(e, dict):
                continue
            event = {"id": str(e.get("id", "")), "at": int(e.get("at") or 0), "event": str(e.get("event", "")), "data": self._realtime.opened(e.get("data"))}
            if e.get("from") is not None:
                event["from"] = str(e["from"])
            events.append(event)
        return {"events": events, "more": bool(answer.get("more"))}

    def forget(self, event_id: Optional[str] = None) -> int:
        """Erases the room's history: one event by its id, or all of it. How many were erased."""
        path = self._path + "/history" + ("" if event_id is None else "?id=" + urllib.parse.quote(event_id, safe=""))
        return int(self._realtime.request("DELETE", path).get("deleted") or 0)

    def kick(self, user: UserId) -> None:
        """Takes a user out of the room at once, refuses their tokens signed before, and moves the room's key on when
        keys have generations."""
        self._realtime.request("POST", self._path + "/kick", {"user": str(user)})
        try:
            self._realtime.rotate_room(self.room)
        except RuntimeError:
            # No generation store: the kick holds, and what the room carries next is still sealed with the key they had.
            pass


class OnlineQueries:
    """Who is online across the app, from the realtime server."""

    def __init__(self, realtime: "Realtime") -> None:
        self._realtime = realtime

    def states(self, users: Iterable[UserId]) -> List[Dict[str, Any]]:
        """Each user's status: online, or offline since when they were last seen."""
        ids = [urllib.parse.quote(str(user), safe="") for user in users]
        if not ids:
            return []
        return list(self._realtime.request("GET", "/wordplus/realtime/online?ids=" + ",".join(ids)).get("online") or [])

    def has(self, user: UserId) -> bool:
        states = self.states([user])
        return bool(states and states[0].get("online"))

    def count(self) -> int:
        return int(self._realtime.request("GET", "/wordplus/realtime/online?limit=1").get("count") or 0)

    def list(self, cursor: str = "0", limit: int = 1000) -> Dict[str, Any]:
        """A page of who is online: their ids, and the cursor of the next page ('0' after the last)."""
        answer = self._realtime.request("GET", "/wordplus/realtime/online?cursor=" + urllib.parse.quote(cursor, safe="") + "&limit=" + str(int(limit)))
        return {"ids": [str(i) for i in answer.get("ids") or []], "next": str(answer.get("next") or "0")}


def _outcome(answer: Dict[str, Any]) -> Dict[str, Any]:
    """What a webhook sent now did: taken (a 2xx), its status, and why not."""
    out: Dict[str, Any] = {"delivered": bool(answer.get("delivered")), "status": int(answer.get("status") or 0)}
    if answer.get("error"):
        out["error"] = str(answer["error"])
    return out


class UserQueries:
    """A user as the realtime server knows them."""

    def __init__(self, realtime: "Realtime", user: str) -> None:
        self._realtime = realtime
        self.id = user
        self._path = "/wordplus/realtime/users/" + urllib.parse.quote(user, safe="")

    def get(self) -> Dict[str, Any]:
        """Online, or offline since ``at``, and how many connections vouched for them are open."""
        return dict(self._realtime.request("GET", self._path).get("user") or {})

    def disconnect(self) -> None:
        """Takes the user out of everything at once: every room, their identity, their lines, group calls and live streams
        (a host stays). Their pages then ask your routes again, and the tokens signed before are refused, so your rules
        decide whether they come back: a user you signed out or blocked does not."""
        self._realtime.request("POST", self._path + "/disconnect")

    def ask(self, event: str, data: Any = None, *, timeout: Optional[int] = None, all: bool = False, seal: bool = True) -> List[Dict[str, Any]]:
        """Asks the pages of the user and waits for their replies: the first by default, every reply within ``timeout`` (ms,
        1,000 to 60,000, 10,000 by default) with ``all``. A page answers with ``rt.answer( event, handler )`` in the browser.
        ``data`` is sealed with the key of the user unless ``seal`` is False, and the replies are opened. No page answering is
        ``[]``."""
        body: Dict[str, Any] = {"event": event, "data": self._realtime.sealed_for(self.id, data, seal)}
        if timeout is not None:
            body["timeout"] = int(timeout)
        if all:
            body["all"] = True
        answer = self._realtime.request("POST", self._path + "/ask", body)
        return [{"data": self._realtime.opened(r.get("data")), "at": int(r.get("at") or 0)} for r in answer.get("replies") or [] if isinstance(r, dict)]


class WebhookQueries:
    """The webhook of the app as the realtime server sends it."""

    def __init__(self, realtime: "Realtime") -> None:
        self._realtime = realtime

    def deliveries(self) -> List[Dict[str, Any]]:
        """The last 100 tries of the last three days, the newest first: each batch by its ``id``, its HTTP ``status`` (0
        for none), ``next_at`` while it is tried again, and whether it is ``resendable``."""
        return list(self._realtime.request("GET", "/wordplus/realtime/webhooks").get("deliveries") or [])

    def resend(self, batch_id: str) -> Dict[str, Any]:
        """A batch your server did not take, sent again now. Raises ``not_found`` once it is gone."""
        return _outcome(self._realtime.request("POST", "/wordplus/realtime/webhooks/" + urllib.parse.quote(batch_id, safe="") + "/resend"))

    def test(self) -> Dict[str, Any]:
        """One ``webhook.test`` event sent now, to see your webhook take it. Raises ``no_webhook`` for an app without one."""
        return _outcome(self._realtime.request("POST", "/wordplus/realtime/webhooks/test"))


class CallQueries:
    """A group call as the media server holds it."""

    def __init__(self, realtime: "Realtime", name: str) -> None:
        self._realtime = realtime
        self.name = name
        self._path = "/wordplus/realtime/calls/" + urllib.parse.quote(name, safe="")

    def get(self) -> Dict[str, Any]:
        """Its people and what each sends now (``camera``, ``microphone``, ``screen``). With nobody in it, ``people`` is 0,
        ``started_at`` None and ``list`` empty."""
        return dict(self._realtime.request("GET", self._path).get("call") or {})

    def mute(self, user: UserId, track: str) -> bool:
        """Turns the ``microphone``, ``camera`` or ``screen`` of someone off. They may turn it on again. Whether it was on."""
        return bool(self._realtime.request("POST", self._path + "/mute", {"user": str(user), "track": track}).get("muted"))

    def remove(self, user: UserId) -> bool:
        """Takes someone out now. Their tokens signed before do not take them back in. Whether they were in it."""
        return bool(self._realtime.request("POST", self._path + "/remove", {"user": str(user)}).get("removed"))

    def permit(self, user: UserId, *, publish: Optional[bool] = None, subscribe: Optional[bool] = None) -> bool:
        """Changes what someone may do while it runs: ``publish`` to make a listener a speaker or a speaker a listener
        again, which stops what they send, ``subscribe`` to stop or start getting the others. At once for them when they
        are in it, and their page hears ``permissions``. Their tokens signed before follow it too. Your rule decides every
        join after, so keep it there as well. Whether they were in it."""
        body: Dict[str, Any] = {"user": str(user)}
        if publish is not None:
            body["publish"] = bool(publish)
        if subscribe is not None:
            body["subscribe"] = bool(subscribe)
        return bool(self._realtime.request("POST", self._path + "/permit", body).get("changed"))

    def end(self) -> None:
        """Ends it for everyone. Tokens signed before do not open it again."""
        self._realtime.request("POST", self._path + "/end")


class StreamQueries:
    """A live stream, and what its moderators do, from the server of the app."""

    def __init__(self, realtime: "Realtime", name: str) -> None:
        self._realtime = realtime
        self.name = name
        self._path = "/wordplus/realtime/streams/" + urllib.parse.quote(name, safe="")

    def get(self) -> Dict[str, Any]:
        """Its state, how many watch now, its peak, slow mode, reactions and the pinned message."""
        return dict(self._realtime.request("GET", self._path).get("stream") or {})

    def people(self) -> Dict[str, Any]:
        """The signed-in people watching or on it, and how many watch in all, visitors included."""
        answer = self._realtime.request("GET", self._path + "/people")
        return {"watching": int(answer.get("watching") or 0), "people": list(answer.get("people") or [])}

    def chat(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """The last messages of the chat, oldest first: 50, or ``limit`` up to 200."""
        return list(self._realtime.request("GET", self._path + "/chat" + ("" if limit is None else "?limit=" + str(int(limit)))).get("messages") or [])

    def say(self, text: str, name: str, avatar: Optional[str] = None) -> Dict[str, Any]:
        """A message from your app in the chat, shown as a host message: its name and an https picture of your own."""
        body: Dict[str, Any] = {"text": text, "name": name}
        if avatar is not None:
            body["avatar"] = avatar
        return dict(self._realtime.request("POST", self._path + "/chat", body).get("message") or {})

    def delete_message(self, message_id: str) -> bool:
        """Deletes a message for everyone. Whether it was there."""
        return bool(self._realtime.request("DELETE", self._path + "/chat/" + urllib.parse.quote(message_id, safe="")).get("deleted"))

    def clear_chat(self) -> None:
        """Empties the chat for everyone, the pinned message too."""
        self._realtime.request("DELETE", self._path + "/chat")

    def pin(self, message_id: Optional[str]) -> None:
        """Pins a message over the chat, or none (None). Raises ``not_found`` for a message no longer there."""
        self._realtime.request("POST", self._path + "/pin", {"id": message_id})

    def slow(self, seconds: int) -> None:
        """Slow mode: one message every ``seconds`` (up to 300) for everyone but its hosts and moderators, 0 turns it off."""
        self._realtime.request("POST", self._path + "/slow", {"seconds": int(seconds)})

    def timeout(self, user: UserId, seconds: int) -> int:
        """Someone may not write until the end of ``seconds`` (60 to 86,400), and goes on watching. When it ends, in ms."""
        return int(self._realtime.request("POST", self._path + "/timeout", {"user": str(user), "seconds": int(seconds)}).get("until") or 0)

    def untimeout(self, user: UserId) -> bool:
        """Lifts a timeout. Whether there was one."""
        return bool(self._realtime.request("POST", self._path + "/untimeout", {"user": str(user)}).get("lifted"))

    def kick(self, user: UserId) -> None:
        """Out of the stream now, free to come back. Raises ``host`` for a host."""
        self._realtime.request("POST", self._path + "/kick", {"user": str(user)})

    def ban(self, user: UserId) -> None:
        """Out of the stream until it is lifted. Raises ``host`` for a host."""
        self._realtime.request("POST", self._path + "/ban", {"user": str(user)})

    def unban(self, user: UserId) -> bool:
        """Lifts a ban. Whether there was one."""
        return bool(self._realtime.request("POST", self._path + "/unban", {"user": str(user)}).get("lifted"))

    def bans(self) -> List[Dict[str, Any]]:
        """Everyone banned, the latest first."""
        return list(self._realtime.request("GET", self._path + "/bans").get("bans") or [])

    def reactions(self, on: bool) -> None:
        """Turns reactions on or off for everyone watching."""
        self._realtime.request("POST", self._path + "/reactions", {"on": bool(on)})

    def end(self) -> Dict[str, Any]:
        """Ends it, as End does for its host."""
        return dict(self._realtime.request("POST", self._path + "/end").get("stream") or {})


class Realtime:
    def __init__(
        self,
        site: str,
        secret: str,
        local_key: str,
        *,
        profile: Optional[Callable[[UserId], Optional[Dict[str, Any]]]] = None,
        has_keys: Optional[Callable[[UserId], bool]] = None,
        hidden: Optional[Callable[[UserId], bool]] = None,
        generations: Optional[GenerationStore] = None,
        seal: bool = True,
        base: str = "/api/realtime",
        routes: Optional[Dict[str, str]] = None,
        headers: Optional[Dict[str, str]] = None,
        files: bool = True,
        worker: Optional[str] = None,
        rooms: Optional[str] = None,
        rooms_worker: Optional[str] = None,
        server: str = SERVER,
        api: str = API_SERVER,
        token_ttl: int = TOKEN_TTL,
        call_token_ttl: int = CALL_TTL,
        http: Optional[Http] = None,
        now: Optional[Callable[[], int]] = None,
        check_keys: bool = True,
    ) -> None:
        # The keys are checked now, or with check_keys=False when first used: a request, a token or an emit. Then a
        # framework's commands (Django's manage.py, collectstatic in a build) run before the keys are set.
        self.site = site
        self._secret_text = secret
        self._local_key = local_key
        self._generations = generations
        self._keys: Optional[Keys] = None
        if check_keys:
            self._secret, self.keys  # noqa: B018
        self._profile = profile
        self._has_keys = has_keys
        self._hidden = hidden
        self._seal = seal
        self._base = base.rstrip("/")
        self._routes = {name: address for name, address in (routes or {}).items() if name in ROUTES and address}
        self._headers = dict(headers or {})
        self._files = files
        self._worker = worker
        self._rooms_file = rooms
        self._rooms_worker = rooms_worker
        self._server = server.rstrip("/")
        self._api = api.rstrip("/")
        self._token_ttl = token_ttl
        self._call_token_ttl = call_token_ttl
        self._http = http or _urlopen
        self._now = now or (lambda: int(time.time()))
        # The rooms the app owns: each pattern's options and rule.
        self._rules = Patterns()
        self._call_rules = Patterns()
        self._group_rules = Patterns()
        self._stream_rules = Patterns()
        self._kinds: Dict[str, Tuple[Callable[..., Any], Optional[Callable[..., Any]]]] = {}
        self._handlers: Dict[str, List[Callable[..., Any]]] = {}
        self._fallback: Optional[Dict[str, Callable[..., Any]]] = None
        self._public_grant: Any = None
        self._warned_user = False

    @property
    def _secret(self) -> bytes:
        if not self.site or not self._secret_text:
            raise ValueError("wordplus-realtime: site and secret are required (WORDPLUS_SITE, WORDPLUS_SECRET)")
        return self._secret_text.encode("utf-8")

    @property
    def keys(self) -> Keys:
        """The keys everything sealed is sealed with, from the local key (64 hex characters)."""
        if self._keys is None:
            self._secret  # noqa: B018  (with nothing set, the site and secret are named first)
            self._keys = Keys(self._local_key, self._generations)
        return self._keys

    @classmethod
    def from_environment(cls, **options: Any) -> "Realtime":
        """From WORDPLUS_SITE, WORDPLUS_SECRET and WORDPLUS_LOCAL_KEY in the environment, with the other options given,
        and WORDPLUS_REALTIME_SERVER and WORDPLUS_REALTIME_API when it sets them and the options don't."""
        for name, env in (("server", "WORDPLUS_REALTIME_SERVER"), ("api", "WORDPLUS_REALTIME_API")):
            if os.environ.get(env) and name not in options:
                options[name] = os.environ[env]
        return cls(os.environ.get("WORDPLUS_SITE", ""), os.environ.get("WORDPLUS_SECRET", ""), os.environ.get("WORDPLUS_LOCAL_KEY", ""), **options)

    # Rules.

    def room(
        self,
        pattern: str,
        rule: Optional[Callable[..., Any]] = None,
        *,
        presence: bool = False,
        count: bool = False,
        history: Union[None, int, Dict[str, int]] = None,
        emit: Union[None, str, List[str]] = None,
        webhook: Union[None, str, List[str]] = None,
        public: bool = False,
        seal: Optional[bool] = None,
    ) -> "Realtime":
        """Rooms the app owns, by pattern (``order:{id}``), who may join, and what they are: ``rule(user, params, room)``
        answers False, True, or ``{"info": …, "emit": …, "readOnly": …}`` for that user. ``presence`` lists its members,
        ``count`` counts them, ``history`` keeps its last events (a number, or ``{"last", "days"}``), ``emit`` and
        ``webhook`` name the events a browser may send to it and those sent here ('*' for any), ``public`` lets anyone
        in, unsealed, and ``seal`` says otherwise. A public room may have no rule. The rule with the most characters of
        its own decides."""
        if not public and rule is None:
            raise ValueError("wordplus-realtime: room %r needs a rule, or `public`" % (pattern,))
        if presence and public:
            raise ValueError("wordplus-realtime: a public room has no members to list; take `presence` off %r" % (pattern,))
        options = _normalized({"presence": presence, "count": count, "history": history, "emit": emit, "webhook": webhook, "public": public, "seal": seal})
        self._rules.add(pattern, {"options": options, "rule": None if rule is None else _flexible(rule)})
        self._public_grant = None
        return self

    def fallback(self, rule: Optional[Callable[..., Any]], options: Optional[Callable[[str], Optional[Dict[str, Any]]]] = None) -> "Realtime":
        """Who decides a room no room() rule owns, and what such a room is: ``rule(user, room)`` answers as a room rule
        does, ``presence`` true in a dict for a member of a presence room; ``options(room)`` the room's options, or None
        for a room it doesn't own either."""
        self._fallback = None if rule is None else {"rule": _flexible(rule), "options": options or (lambda room: {})}
        return self

    def calls(self, pattern: str, rule: Callable[..., Any], *, people: Optional[Callable[..., Iterable[UserId]]] = None) -> "Realtime":
        """Calls between two people the app owns, by pattern (``support:{a}:{b}``): ``rule(user, with_user, params, call,
        side)`` answers False, True, or ``{"info", "publish", "subscribe", "admin", "hidden"}``. It is asked as the caller
        places the call (``side["role"]`` ``"caller"``) and again as the callee answers (``"callee"``), so a rule may let
        someone answer calls they may not place.

        A call becomes a group call when either of its people adds someone, which the rule decides as for any call: the
        user calling the person about the call's name, then the person taking a call from them. A call's rooms are
        encrypted end to end with a key only this server gives out, to the people in the call. ``people(user, call)``
        lists the user ids the call screen offers to add."""
        self._call_rules.add(pattern, {"rule": _flexible(rule), "people": None if people is None else _flexible(people)})
        return self

    def group_calls(self, pattern: str, rule: Callable[..., Any], *, encrypt: bool = False) -> "Realtime":
        """Group calls the app owns, by pattern (``meeting:{id}``): ``rule(user, params, name)``; ``encrypt`` encrypts
        their rooms end to end."""
        self._group_rules.add(pattern, {"rule": _flexible(rule), "encrypt": bool(encrypt)})
        return self

    def streams(self, pattern: str, rule: Callable[..., Any], *, stage: Any = None, reactions: Any = None, people: Any = None, chat: Any = None) -> "Realtime":
        """Live streams the app owns, by pattern (``show:{id}``): ``rule(user, params, name)`` says who is what in each.
        It answers False, a role (``host``, ``guest``, ``viewer``) or the role with more: ``{"role": …, "info": {"name": …,
        "avatar": https}, "chat": "write" | "read", "mod": bool, "src": [camera, microphone, screen], "quality": "720p" |
        "1080p"}``. ``user`` is None for a visitor who isn't signed in, who may only be a viewer. The stream's own
        settings: ``stage``, ``reactions``, ``people`` (``mods`` or ``all``) and ``chat`` (``offline`` open or closed,
        ``links``, ``fresh``), each a value or a function of the name's parts. A page asks with ``calls.stream(name)``."""
        settings = {"stage": stage, "reactions": reactions, "people": people, "chat": chat}
        self._stream_rules.add(pattern, {"rule": _flexible(rule), "settings": settings})
        return self

    def kind(self, kind: str, may_have: Callable[..., bool], newest: Optional[Callable[..., str]] = None) -> "Realtime":
        """Keys of the app's own kind (``kind:{rest}``), and who may have them: ``may_have(rest, user, label)``. A kind is
        1–16 of a-z and 0-9, starting with a letter, and not ``d``, ``u`` or ``ch``. ``newest(rest, label)`` names the
        newest key of the same thing, for a kind with generations."""
        if re.fullmatch(r"[a-z][a-z0-9]{0,15}", kind) and kind not in RESERVED:
            self._kinds[kind] = (_flexible(may_have), None if newest is None else _flexible(newest))
        return self

    def on(self, type: str, handler: Callable[[Dict[str, Any]], Any]) -> "Realtime":
        """A webhook from the realtime server, opened: ``room.occupied``, ``room.vacated``, ``member.joined``,
        ``member.left``, ``user.online``, ``user.offline``, ``stream.live``, ``stream.ended`` (a live stream going live
        and ending, its name in ``stream``), what people used (``call.ended``, ``group.joined``, ``group.left``,
        ``stream.joined``, ``stream.left``, with ``seconds`` once over), the name of a browser's event a room's rule
        sends here (``webhook``), or
        '*'."""
        self._handlers.setdefault(type, []).append(handler)
        return self

    # Sending, and what the realtime server holds.

    def to(self, rooms: Union[str, Iterable[str]]) -> Emitter:
        """An emit to rooms: ``realtime.to("order:42").except_tab(tab).emit("updated", data)``."""
        return Emitter(self).to(rooms)

    def to_user(self, users: Union[UserId, Iterable[UserId]]) -> Emitter:
        """An emit to users, every connection they have open: ``realtime.to_user(42).emit("notice", data)``."""
        return Emitter(self).to_user(users)

    def in_room(self, room: str) -> RoomQueries:
        """A room as the realtime server holds it: its members, count, history, and kicking a user out."""
        return RoomQueries(self, room)

    @property
    def online(self) -> OnlineQueries:
        """Who is online across the app."""
        return OnlineQueries(self)

    def list_rooms(self, *, prefix: Optional[str] = None, cursor: Optional[str] = None, limit: Optional[int] = None) -> Dict[str, Any]:
        """The rooms someone is in now, by name: those starting with ``prefix``, a page at a time (``cursor`` from
        ``next``, ``limit`` up to 1,000)."""
        ask = {name: value for name, value in (("prefix", prefix), ("cursor", cursor), ("limit", limit)) if value is not None}
        answer = self.request("GET", "/wordplus/realtime/rooms" + ("?" + urllib.parse.urlencode(ask) if ask else ""))
        out: Dict[str, Any] = {"count": int(answer.get("count") or 0), "rooms": list(answer.get("rooms") or [])}
        if answer.get("next"):
            out["next"] = str(answer["next"])
        return out

    def user(self, user_id: UserId) -> UserQueries:
        """A user as the realtime server knows them: their state, taking them out of everything at once, asking their pages."""
        return UserQueries(self, str(user_id))

    def usage(self) -> Dict[str, Any]:
        """What the app uses now: its connections (those of an app against its plan), and the credits of its account as WordPlus Cloud
        last said, a credit a minute."""
        answer = self.request("GET", "/wordplus/realtime/usage")
        return {"connections": dict(answer.get("connections") or {}), "credits": answer.get("credits")}

    @property
    def webhooks(self) -> WebhookQueries:
        """The last deliveries of the webhook, a batch not taken sent again, and a test event."""
        return WebhookQueries(self)

    def list_calls(self) -> List[Dict[str, Any]]:
        """The group calls of the app going on now, from the media server."""
        return list(self.request("GET", "/wordplus/realtime/calls").get("calls") or [])

    def call(self, name: str) -> CallQueries:
        """A group call as the media server holds it: its people, muting, removing someone, ending it."""
        return CallQueries(self, name)

    def list_streams(self) -> List[Dict[str, Any]]:
        """The live streams of the app that are live now."""
        return list(self.request("GET", "/wordplus/realtime/streams").get("streams") or [])

    def stream(self, name: str) -> StreamQueries:
        """A live stream: its state, who is in it, its chat, and what its moderators do."""
        return StreamQueries(self, name)

    def batch(self, events: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        """Several events at once, each as an emit takes them (``rooms``, ``users``, ``event``, ``data``, ``except``,
        ``seal``). The kept events' ids, by room, for each."""
        return [self.emit_event(event) for event in events]

    # The routes.

    def authorize(self, rooms: List[Any], user: Optional[UserId]) -> Dict[str, Any]:
        """What the auth route answers for the rooms asked: one token for those allowed, their keys, and why each other
        was refused (``forbidden``, ``bad_room``, ``no_rule``, ``too_many``)."""
        denied: Dict[str, str] = {}
        allowed: List[Dict[str, Any]] = []
        asked: List[str] = []
        for room in rooms:
            if isinstance(room, (str, int)) and not isinstance(room, bool) and str(room) not in asked:
                asked.append(str(room))

        for i, room in enumerate(asked):
            if i >= MAX_ROOMS:
                denied[room] = "too_many"
                continue
            if not valid_room(room):
                denied[room] = "bad_room"
                continue
            entry = self._entry_for(room)
            if entry is None:
                denied[room] = "no_rule"
                continue
            answer = self._answer_for(entry, room, user)
            options = dict(entry["options"])
            if answer is not None and answer.get("presence"):
                options["presence"] = True
                options["count"] = True
            if answer is None or (options["presence"] and not _known(user)):
                denied[room] = "forbidden"
                continue
            allowed.append({
                "room": room,
                "options": options,
                "emit": answer.get("emit", options["emit"]),
                "read_only": bool(answer.get("readOnly")),
                "info": answer.get("info"),
                "given": "info" in answer,
            })

        if not allowed:
            return {"denied": denied}

        now = self._now()
        exp = now + _clamp(self._token_ttl, 60, MAX_TTL)
        claims: Dict[str, Any] = {"iss": self.site, "aud": AUDIENCE, "iat": now, "exp": exp}
        if _known(user):
            claims["sub"] = str(user)

        r: Dict[str, Any] = {}
        infos: Dict[str, Any] = {}
        plain_info: Any = None
        has_plain_info = False
        keys: List[str] = []
        for a in allowed:
            r[a["room"]] = _short({**a["options"], "emit": a["emit"]}, a["read_only"])
            sealed = self._seal and a["options"]["seal"]
            if sealed:
                keys.append(self.keys.entry(self.keys.room_label(a["room"])))
            if not a["options"]["presence"]:
                continue
            info = a["info"] if a["given"] else self._default_info(user)
            if sealed:
                infos[a["room"]] = self.keys.seal_json(info, self.keys.room_label(a["room"])) or info
            else:
                plain_info = info
                has_plain_info = True

        claims["r"] = r
        if infos:
            claims["infos"] = infos
        if has_plain_info:
            claims["info"] = plain_info

        grant: Dict[str, Any] = {"token": _jwt(claims, self._token_key()), "exp": exp, "denied": denied}
        if keys:
            grant["keys"] = keys
        return grant

    def public_grants(self) -> List[Dict[str, Any]]:
        """The grant for the app's public rooms, which every page may carry: their patterns, no user, signed for 6 hours
        and made again an hour before it runs out. Empty when the app has none."""
        if isinstance(self._public_grant, dict) and self._public_grant["exp"] - self._now() < 3600:
            self._public_grant = None
        if self._public_grant is None:
            open_rooms = [(pattern, entry) for pattern, entry in self._rules.entries() if entry["options"]["public"] and entry["rule"] is None]
            if not open_rooms:
                self._public_grant = False
            else:
                now = self._now()
                exp = now + TOKEN_TTL
                r = {pattern: _short(entry["options"], False) for pattern, entry in open_rooms}
                self._public_grant = {
                    "token": _jwt({"iss": self.site, "aud": AUDIENCE, "iat": now, "exp": exp, "r": r}, self._token_key()),
                    "exp": exp,
                    "rooms": [pattern for pattern, _ in open_rooms],
                }
        return [] if self._public_grant is False else [self._public_grant]

    def authorize_call(self, request: Dict[str, Any], user: Optional[UserId]) -> Dict[str, Any]:
        """What the calls route answers: the page's line (``line``), its side of a call (``call``, ``id``, ``role``, ``to``
        or ``from``, ``type``, and ``group``, ``pair`` and ``member`` or ``ring`` for a ring into the group call it
        became), a place in a group call (``room``, ``type``), the people a user may add to a call (``people``: its
        name), whether the user may call each of some people (``may``: up to 100 ``{"call": …, "to": …}``, each asked of
        its rule as the caller), or a host's act in a group call (``moderate``: its name, ``act`` and ``user``). A token,
        when it runs out, the call's key for its signals, the key its rooms encrypt their media with, the call's pair and
        the user's proof of being in it, the proof a person rung in was rung, the people, ``may`` (true or false for each,
        in the order asked), ``done`` for a host's act, or ``denied``: ``no_user``, ``bad_request``, ``forbidden``,
        ``server``.

        Who is in a call is in proofs made with the local key, which WordPlus Cloud never sees: the realtime server
        carries them from page to page and can't make one, and this server keeps nothing."""
        # A live stream's grant (streams()), which a visitor who isn't signed in may get too, as a viewer.
        if "stream" in request:
            return self._authorize_stream(request["stream"], user)

        me = _call_user(user)
        if me is None:
            if _known(user) and not self._warned_user:
                self._warned_user = True
                warnings.warn("wordplus-realtime: a user of a call is an id of up to 64 characters with no space; %r is not one" % (user,))
            return {"denied": "no_user"}

        if request.get("line"):
            return self._sign_calls({"aud": LINE_AUDIENCE, "sub": me})

        if "people" in request:
            return {"people": self._call_people(request["people"], me)} if valid_room(request["people"]) else {"denied": "bad_request"}

        if "may" in request:
            return self._may_call(request["may"], me)

        if "moderate" in request:
            return self._moderate_call(request["moderate"], request.get("act"), request.get("user"), me)

        kind = "audio" if request.get("type") == "audio" else "video"

        if "room" in request:
            room = request["room"]
            if not valid_room(room):
                return {"denied": "bad_request"}
            found = self._group_rules.match(room)
            answer = None if found is None else self._call_answer(found["value"]["rule"](me, found["params"], room), me)
            if answer is None:
                return {"denied": "forbidden"}
            signed = self._sign_calls({
                "aud": ROOM_AUDIENCE,
                "room": room,
                "sub": me,
                "type": kind,
                "info": self._sealed_call_info(answer["info"]),
                "publish": bool(answer.get("publish", True)),
                "subscribe": bool(answer.get("subscribe", True)),
                "admin": bool(answer.get("admin", False)),
                "hidden": bool(answer.get("hidden", False)),
            })
            # Encrypted end to end when its rule says so: everyone the rule lets in gets the room's key.
            if found["value"]["encrypt"]:  # type: ignore[index]
                signed["media_key"] = self.keys.media("room|" + room)
            return signed

        call, attempt, role, group = request.get("call"), request.get("id"), request.get("role"), request.get("group")
        if not valid_room(call) or not _valid_attempt(attempt) or role not in ("caller", "callee"):
            return {"denied": "bad_request"}
        if group is not None and (not _valid_attempt(group) or group == attempt):
            return {"denied": "bad_request"}

        other = _call_user(request.get("to") if role == "caller" else request.get("from"))
        if other is None or other == me:
            return {"denied": "bad_request"}

        answer = self._ask_caller(me, call, other, role)
        if answer is None:
            return {"denied": "forbidden"}

        # The call's two people, whose key its rooms encrypt with: this request's, for the call itself; for a ring into
        # the group call it became, the pair its proofs name, with the ringer's proof of being in it or the proof the
        # person was rung.
        if group is None:
            first = attempt
            pair = (me, other) if role == "caller" else (other, me)
        else:
            first = group
            named = _pair_of(request.get("pair"))
            if named is None:
                return {"denied": "bad_request"}
            pair = named
            proof = request.get("member") if role == "caller" else request.get("ring")
            expected = self._call_proof("member" if role == "caller" else "rung", call, first, pair, me)
            if not isinstance(proof, str) or not hmac.compare_digest(expected, proof):
                return {"denied": "forbidden"}

        claims: Dict[str, Any] = {"aud": CALL_AUDIENCE, "call": call, "id": attempt, "sub": me, "role": role, "type": kind, "info": self._sealed_call_info(answer["info"])}
        if role == "caller":
            claims["to"] = other
        if group is not None:
            claims["group"] = group

        signed = self._sign_calls(claims)
        signed["key"] = self.call_key(attempt, me if role == "caller" else other, other if role == "caller" else me)
        signed["media_key"] = self.keys.media("call|%s|%s|%s|%s" % (call, first, _id_part(pair[0]), _id_part(pair[1])))
        signed["pair"] = [pair[0], pair[1]]
        signed["member"] = self._call_proof("member", call, first, pair, me)
        if group is not None and role == "caller":
            signed["ring"] = self._call_proof("rung", call, first, pair, other)
        return signed

    def call_key(self, attempt: str, caller: UserId, callee: UserId) -> str:
        """The key a call's two browsers seal their negotiation with: from the local key, which WordPlus Cloud doesn't know."""
        message = CALL_KEY_LABEL + "|" + attempt + "|" + _id_part(caller) + "|" + _id_part(callee)
        return hmac.new(self._local_key.encode("ascii"), message.encode("utf-8"), hashlib.sha256).hexdigest()

    def keys_answer(self, labels: Any, user: Optional[UserId]) -> Dict[str, Any]:
        """What the keys route answers, ``{labels}``: the keys asked for that this user may have, each with the newest of
        the same thing beside it. With no labels: the keys the user starts with, and their identity."""
        if not isinstance(labels, list) or not labels:
            keys = self._user_entries(user)
            identity = self.identity(user) if keys else None
            return {"keys": keys, "identity": identity} if identity else {"keys": keys}

        out: List[str] = []
        seen: List[str] = []
        for label in labels:
            if not isinstance(label, str) or label in seen:
                continue
            seen.append(label)
            if len(seen) > MAX_LABELS:
                break
            if not self.may_have(label, user):
                continue
            if self.keys.entry(label) not in out:
                out.append(self.keys.entry(label))
            newest = self._newest(label)
            if newest and self.may_have(newest, user) and self.keys.entry(newest) not in out:
                out.append(self.keys.entry(newest))
        return {"keys": out}

    def may_have(self, label: str, user: Optional[UserId]) -> bool:
        """Whether this user may have the key a label names, as WordPress's may_have() decides."""
        if not valid_label(label) or not self._user_has_keys(user):
            return False
        kind, rest = label.split(":", 1)
        if kind == "d":
            return _known(user) and re.fullmatch(r"\d{1,9}", rest) is not None and int(rest) <= day_of() + 1
        if kind == "u":
            return _known(user) and rest == self.keys.user_label(user)[2:]
        if kind == "ch":
            match = re.fullmatch(r"(.+):(\d{1,9})", rest)
            if match is None or not valid_room(match.group(1)):
                return False
            entry = self._entry_for(match.group(1))
            if entry is None or not entry["options"]["seal"]:
                return False
            generation = int(match.group(2))
            return 1 <= generation <= self.keys.room_generation(match.group(1)) and self.may_join(match.group(1), user)
        own = self._kinds.get(kind)
        return own is not None and own[0](rest, user, label) is True

    def may_join(self, room: str, user: Optional[UserId]) -> bool:
        """Whether a user may join a room, as the auth route decides it."""
        if not valid_room(room):
            return False
        entry = self._entry_for(room)
        if entry is None:
            return False
        answer = self._answer_for(entry, room, user)
        if answer is None:
            return False
        return not (entry["options"]["presence"] or answer.get("presence")) or _known(user)

    def identity(self, user: Optional[UserId]) -> Optional[Dict[str, Any]]:
        """Who a user is for the realtime server, and their entry in the app's directory, signed as a room token is: their
        online status, what the app's server sends them, and the directory. None for nobody, a user without a profile,
        or one cut off from the keys."""
        if not _known(user) or not self._user_has_keys(user):
            return None
        plain = self._profile_of(user)  # type: ignore[arg-type]
        if plain is None:
            return None
        profile = self.keys.profile(user, plain, self._seal)  # type: ignore[arg-type]
        now = self._now()
        exp = now + _clamp(self._token_ttl, 60, MAX_TTL)
        claims = {"iss": self.site, "aud": IDENTITY_AUDIENCE, "iat": now, "exp": exp, "sub": str(user), "pd": profile["pd"], "pdh": profile["pdh"]}
        if self._hidden is not None and self._hidden(user) is True:
            claims["hid"] = True
        return {"token": _jwt(claims, self._token_key()), "exp": exp}

    def rotate_room(self, room: str) -> None:
        """Moves a room's key on, when someone lost access to it; needs ``generations``."""
        self.keys.rotate_room(room)

    def rotate_user(self, user: UserId) -> None:
        """Moves a user's own key on, when their access is revoked; needs ``generations``."""
        self.keys.rotate_user(user)

    # The browser.

    def config(self, user: Optional[UserId] = None, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """The browser's settings for a user, for connect(): where to connect, the app, its routes, its public rooms'
        grant, and a signed-in user's keys and identity, so their page needs no request before it connects."""
        heads = {**self._headers, **(headers or {})}
        entries = self._user_entries(user)
        identity = self.identity(user) if entries else None
        grants = self.public_grants()
        keys: Dict[str, Any] = {"endpoint": self.address("keys"), "headers": heads, "entries": entries}
        if identity:
            keys["identity"] = identity
        config: Dict[str, Any] = {"server": self._server, "path": PATH, "site": self.site, "api": self._api}
        if self._worker or self._files:
            config["worker"] = self._worker or self.file_at("realtime-worker.js")
        if self._rooms_file or self._files:
            config["rooms"] = self._rooms_file or self.file_at("realtime-rooms.min.js")
        if self._rooms_worker:
            config["roomsWorker"] = self._rooms_worker
        # The call screen asks whom a user may add once a call is up, when some calls rule lists people.
        if any(entry["people"] is not None for _, entry in self._call_rules.entries()):
            config["screen"] = {"add": True}
        if grants:
            config["grants"] = grants
        config.update({"auth": {"endpoint": self.address("auth"), "headers": heads}, "calls": {"endpoint": self.address("calls"), "headers": heads}, "keys": keys})
        return config

    def head(self, user: Optional[UserId] = None, headers: Optional[Dict[str, str]] = None, importmap: bool = True) -> str:
        """What a page's ``<head>`` takes, as HTML: ``window.wordplusRealtimeConfig``, the settings for the user, and an
        import map naming ``@wordplus/realtime`` the client the routes serve, so a page's own module imports it with no
        bundler: ``import { connect } from '@wordplus/realtime'``. ``importmap=False`` leaves the map out, for a page
        whose bundler resolves the package, or that has an import map of its own."""

        def script_json(value: Any) -> str:
            # JSON that a <script> cannot be closed or commented out by.
            return json.dumps(value, separators=(",", ":")).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")

        out = ""
        if importmap and self._files:
            out += '<script type="importmap">' + script_json({"imports": {"@wordplus/realtime": self.file_at("realtime.js")}}) + "</script>\n"
        return out + "<script>window.wordplusRealtimeConfig = " + script_json(self.config(user, headers)) + ";</script>"

    def file_at(self, name: str) -> str:
        """Where the routes serve a browser file, in the folder of this version: ``realtime.js``, ``realtime-worker.js``,
        ``realtime-rooms.min.js``, ``realtime-rooms-e2ee.worker.js``, ``realtime-ui.min.js`` or
        ``realtime-ui-streams.min.js``. For a page with no bundler, ``realtime.js``:
        ``<script type="module">import { connect } from '…'</script>``."""
        return self._base + "/files/" + files_manifest()["version"] + "/" + name

    @property
    def base(self) -> str:
        """Where the routes are, ``/api/realtime`` by default, without a slash at its end."""
        return self._base

    @property
    def serves_files(self) -> bool:
        """Whether the routes serve the browser files (``files=True``, the default)."""
        return self._files

    def file(self, method: str, path: str, if_none_match: Optional[str] = None) -> Optional[Tuple[int, Dict[str, str], Optional[bytes]]]:
        """A browser file, for a GET or HEAD under ``{base}/files/``: (status, headers, body), or None for any other
        request. The package carries them, so a Python app needs no Node and copies nothing. In the folder of this version
        a file is kept for a year; with no version, as a page names it by hand, it is checked again each time; in another
        version's folder, as a page of the release before or after asks while servers are updated, it is the file of
        this one, kept by nobody."""
        if method.upper() not in ("GET", "HEAD") or not self._files:
            return None
        base = (self._base + "/files").strip("/")
        path = _path_of(path).strip("/")
        if not path.startswith(base + "/"):
            return None
        parts = path[len(base) + 1:].split("/")
        name = parts.pop()
        if len(parts) > 1:
            return 404, {"Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store"}, b"Not found"
        return self.file_named(method, parts[0] if parts else None, name, if_none_match)

    def file_named(self, method: str, folder: Optional[str], name: str, if_none_match: Optional[str] = None) -> Tuple[int, Dict[str, str], Optional[bytes]]:
        """A browser file by its folder (a version, or None) and name, as a framework's URL pattern parts them: file()
        without the path."""
        method = method.upper()
        manifest = files_manifest()
        if method not in ("GET", "HEAD") or not self._files or name not in manifest["files"]:
            return 404, {"Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store"}, b"Not found"
        etag = '"' + manifest["version"] + '"'
        headers = {
            "Content-Type": "text/javascript; charset=utf-8",
            "Cache-Control": "public, max-age=31536000, immutable" if folder == manifest["version"] else "no-cache" if folder is None else "no-store",
            "ETag": etag,
            "X-Content-Type-Options": "nosniff",
        }
        if folder is None and if_none_match == etag:
            return 304, headers, None
        if method == "HEAD":
            return 200, headers, None
        with open(os.path.join(FILES_DIR, name), "rb") as f:
            return 200, headers, f.read()

    def address(self, name: str) -> str:
        """Where a route is (``auth``, ``calls``, ``keys`` or ``webhook``): its own address from ``routes``, else ``{base}/{name}``."""
        return self._routes.get(name) or self._base + "/" + name

    @property
    def own_routes(self) -> bool:
        """Whether some route has an address of its own."""
        return bool(self._routes)

    def route_of(self, path: str) -> Optional[str]:
        """The route a request's path asks for: the one at that address, else, while no route has an address of its own,
        the path's last part, as the routes were always told apart. None for a path that is none of them."""
        path = _path_of(path).rstrip("/")
        for name in ROUTES:
            if _path_of(self.address(name)).rstrip("/") == path:
                return name
        if self._routes:
            return None
        return path.rsplit("/", 1)[-1]

    def handle(self, action: str, body: Any, user: Optional[UserId]) -> Tuple[int, Any]:
        """One of the JSON routes, ``auth``, ``calls`` or ``keys``, for a request's JSON body and its user: (status, body)."""
        params = body if isinstance(body, dict) else {}
        user = user if _known(user) else None
        if action == "auth":
            if not isinstance(params.get("rooms"), list):
                return 400, {"code": "bad_request", "message": "rooms must be a list of room names."}
            return 200, self.authorize(params["rooms"], user)
        if action == "calls":
            return 200, self.authorize_call(params, user)
        if action == "keys":
            return 200, self.keys_answer(params.get("labels"), user)
        return 404, {"code": "not_found"}

    def webhook(self, raw: Union[bytes, str], headers: Any, path: str) -> Tuple[int, Any]:
        """A webhook from the realtime server, as its request came (``raw`` the body as sent, ``path`` with its query):
        checked, its events opened and handed to the handlers on() set. (204, None) once every handler is done, 401 for a
        request the realtime server didn't sign, 500 when a handler raised (the realtime server sends the batch again
        later)."""
        body = raw.encode("utf-8") if isinstance(raw, str) else bytes(raw)
        timestamp = _header(headers, "X-WordPlus-Timestamp")
        signature = _header(headers, "X-WordPlus-Signature")
        if _header(headers, "X-WordPlus-Site") != self.site or not signature or re.fullmatch(r"\d{1,12}", timestamp) is None:
            return 401, {"code": "missing_signature"}
        if abs(self._now() - int(timestamp)) > WEBHOOK_WINDOW:
            return 401, {"code": "stale_signature"}
        key = hmac.new(self._secret, WEBHOOK_LABEL.encode("ascii"), hashlib.sha256).digest()
        expected = hmac.new(key, (timestamp + "\nPOST\n" + path + "\n" + hashlib.sha256(body).hexdigest()).encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            return 401, {"code": "bad_signature"}

        try:
            decoded = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            decoded = None
        if not isinstance(decoded, dict) or not isinstance(decoded.get("events"), list):
            return 400, {"code": "bad_request"}

        try:
            for e in decoded["events"]:
                if not isinstance(e, dict):
                    continue
                emitted = e.get("type") == "emit"
                event = {**e, "data": self.opened(e.get("data"))} if emitted else e
                for handler in [*self._handlers.get(str(e.get("event", "") if emitted else e.get("type", "")), []), *self._handlers.get("*", [])]:
                    handler(event)
        except Exception:
            log.exception("wordplus-realtime: a webhook handler failed")
            return 500, {"code": "handler_failed"}
        return 204, None

    def answer_request(self, method: str, content_type: str, action: str, body: bytes, user: Optional[UserId]) -> Tuple[int, Any]:
        """A request as the routes take it: POST, JSON (a page on another site can't send that without asking first, which
        it is never allowed), and its body."""
        if method.upper() != "POST":
            return 405, {"code": "method_not_allowed"}
        if "application/json" not in (content_type or "").lower():
            return 415, {"code": "bad_request", "message": "Send JSON."}
        try:
            parsed = json.loads(body.decode("utf-8") or "null")
        except (ValueError, UnicodeDecodeError):
            return 400, {"code": "bad_request", "message": "The body is not JSON."}
        return self.handle(action, parsed, user)

    # Used by Emitter, RoomQueries and OnlineQueries.

    def emit_event(self, event: Dict[str, Any]) -> Dict[str, str]:
        """What an emit sends: each sealed room's own copy, the others together, each user's own copy; the kept events'
        ids by room. Raises RealtimeError with the server's reason."""
        name = event.get("event")
        if not isinstance(name, str) or not name:
            raise RealtimeError("bad_request")
        given_rooms = event.get("rooms") or []
        rooms: List[str] = []
        for room in [given_rooms] if isinstance(given_rooms, str) else given_rooms:
            if str(room) not in rooms:
                rooms.append(str(room))
        given_users = event.get("users") or []
        users: List[str] = []
        for user in [given_users] if isinstance(given_users, (str, int)) else given_users:
            if _known(user) and str(user) not in users:
                users.append(str(user))
        data = _pack(event.get("data"))
        extra = {"except": str(event["except"])} if event.get("except") else {}
        sealing = event.get("seal", True) is not False and self._seal
        out: List[Dict[str, Any]] = []
        plain: List[str] = []
        plain_history: Dict[str, List[int]] = {}

        for room in rooms:
            if not valid_room(room):
                raise RealtimeError("bad_room")
            entry = self._entry_for(room)
            options = entry["options"] if entry else None
            history = {room: [options["history"]["last"], options["history"]["days"]]} if options and options["history"] else None
            if sealing and options and options["seal"]:
                out.append({"rooms": [room], "event": name, "data": self.keys.seal_json(data, self.keys.room_label(room)), **({"history": history} if history else {}), **extra})
            else:
                plain.append(room)
                plain_history.update(history or {})

        if plain:
            out.append({"rooms": plain, "event": name, "data": data, **({"history": plain_history} if plain_history else {}), **extra})

        plain_users: List[str] = []
        for user in users:
            label = self.keys.user_label(user) if sealing else ""
            if label:
                out.append({"users": [user], "event": name, "data": self.keys.seal_json(data, label), **extra})
            else:
                plain_users.append(user)
        if plain_users:
            out.append({"users": plain_users, "event": name, "data": data, **extra})

        if len(out) == 1:
            return dict(self._signed("POST", "/wordplus/realtime/emit", out[0]).get("ids") or {})
        ids: Dict[str, str] = {}
        for i in range(0, len(out), BATCH):
            for kept in self._signed("POST", "/wordplus/realtime/emit/batch", {"events": out[i : i + BATCH]}).get("ids") or []:
                for room, kept_id in (kept or {}).items():
                    ids.setdefault(room, kept_id)
        return ids

    def request(self, method: str, path: str, body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """A request to the realtime server, signed as the app."""
        return self._signed(method, path, body)

    def sealed_for(self, user: str, data: Any, seal: bool = True) -> Any:
        """Data for the pages of a user: sealed with their key when the app seals and has keys, its binary parts carried in it."""
        packed = _pack(data)
        label = self.keys.user_label(user) if seal and self._seal else ""
        return self.keys.seal_json(packed, label) if label else packed

    def opened(self, data: Any) -> Any:
        """An event's data as the app's server sees it: opened when it sealed it, its binary parts bytes again."""
        if not isinstance(data, str):
            return _unpack(data)
        plain = self.keys.open(data)
        if plain is None:
            return data
        try:
            return _unpack(json.loads(plain))
        except ValueError:
            return data

    # Inside.

    def _entry_for(self, room: str) -> Optional[Dict[str, Any]]:
        """The rule and options a room falls under: a room() rule, or the fallback's; None for none."""
        found = self._rules.match(room)
        if found is not None:
            return {"options": found["value"]["options"], "rule": found["value"]["rule"], "params": found["params"], "fallback": False}
        if self._fallback is None:
            return None
        options = self._fallback["options"](room)
        return {"options": _normalized(options), "rule": self._fallback["rule"], "params": {}, "fallback": True} if isinstance(options, dict) else None

    def _answer_for(self, entry: Dict[str, Any], room: str, user: Optional[UserId]) -> Optional[Dict[str, Any]]:
        """A rule's answer for a user: None for no, else what they bring and may do."""
        if entry["rule"] is None:
            return {} if entry["options"]["public"] else None
        answer = entry["rule"](user, room) if entry["fallback"] else entry["rule"](user, entry["params"], room)
        if answer is False or answer is None:
            return None
        if not isinstance(answer, dict):
            return {}
        out: Dict[str, Any] = {}
        if "info" in answer:
            out["info"] = answer["info"]
        if answer.get("emit") == "*" or isinstance(answer.get("emit"), (list, tuple)):
            out["emit"] = _names(answer["emit"])
        if answer.get("readOnly"):
            out["readOnly"] = True
        if answer.get("presence"):
            out["presence"] = True
        return out

    def _ask_caller(self, user: UserId, name: str, with_user: UserId, role: str) -> Optional[Dict[str, Any]]:
        found = self._call_rules.match(name)
        return None if found is None else self._call_answer(found["value"]["rule"](user, with_user, found["params"], name, {"role": role}), user)

    def _call_answer(self, answer: Any, user: UserId) -> Optional[Dict[str, Any]]:
        """A calls rule's answer, with the user's info by default; None for no."""
        if answer is False or answer is None:
            return None
        out = dict(answer) if isinstance(answer, dict) else {}
        if "info" not in out:
            out["info"] = self._default_info(user)
        return out

    def _call_proof(self, kind: str, call: str, first: str, pair: Tuple[UserId, UserId], user: UserId) -> str:
        """A proof only this server makes about a call: ``member``, a user is in it; ``rung``, someone in it rang a user in."""
        return self.keys.proof("%s|%s|%s|%s|%s|%s" % (kind, call, first, _id_part(pair[0]), _id_part(pair[1]), _id_part(user)))

    def _moderate_call(self, name: Any, act: Any, target: Any, me: UserId) -> Dict[str, Any]:
        """What a host does to someone else in the group call ``name``, from its call screen: the call's rule asked again
        for the user, who must be its host (``admin``), then the act through WordPlus Cloud: ``mute`` their microphone,
        ``speak`` or ``listen`` (permit()'s ``publish``), ``remove``. ``{"done": …}``, whether it changed anything."""
        user = _call_user(target)
        if not valid_room(name) or act not in MODERATION_ACTS or user is None or user == me:
            return {"denied": "bad_request"}
        found = self._group_rules.match(name)
        answer = None if found is None else found["value"]["rule"](me, found["params"], name)
        if not isinstance(answer, dict) or not answer.get("admin"):
            return {"denied": "forbidden"}
        call = self.call(name)
        try:
            if act == "mute":
                return {"done": call.mute(user, "microphone")}
            if act == "remove":
                return {"done": call.remove(user)}
            return {"done": call.permit(user, publish=act == "speak")}
        except RealtimeError:
            return {"denied": "server"}

    def _may_call(self, asks: Any, me: UserId) -> Dict[str, Any]:
        """Whether a user may call each person asked about (``[{"call": …, "to": …}]``), in the order asked: the rule of
        each call, asked as for its caller, as placing it asks. A list of people asks it before offering its call buttons.
        At most 100."""
        if not isinstance(asks, list) or len(asks) > 100:
            return {"denied": "bad_request"}
        may: List[bool] = []
        for ask in asks:
            call = ask.get("call") if isinstance(ask, dict) else None
            other = _call_user(ask.get("to")) if isinstance(ask, dict) else None
            # The rule alone, with no info to make for a call no one places yet.
            found = self._call_rules.match(call) if valid_room(call) and other is not None and other != me else None
            answer = None if found is None else found["value"]["rule"](me, other, found["params"], call, {"role": "caller"})
            may.append(answer is not None and answer is not False)
        return {"may": may}

    def _call_people(self, call: str, me: UserId) -> List[Dict[str, Any]]:
        """Whom a user may add to a call named ``call``: those its rule's ``people`` lists whom they may call about it. At
        most 100."""
        found = self._call_rules.match(call)
        people = None if found is None else found["value"]["people"]
        if people is None:
            return []
        listed: Dict[UserId, Dict[str, Any]] = {}
        for listed_id in people(me, call) or []:
            other = _call_user(listed_id)
            if other is None or other == me or other in listed or self._ask_caller(me, call, other, "caller") is None:
                continue
            profile = self._profile_of(other)
            if profile is not None:
                avatar = profile.get("avatar")
                listed[other] = {"id": other, "name": profile["name"], "avatar": avatar if isinstance(avatar, str) else ""}
            if len(listed) >= 100:
                break
        return list(listed.values())

    def _profile_of(self, user: UserId) -> Optional[Dict[str, Any]]:
        profile = self._profile(user) if self._profile else None
        return profile if isinstance(profile, dict) and isinstance(profile.get("name"), str) and profile["name"] else None

    def _default_info(self, user: Optional[UserId]) -> Any:
        """A member's info by default: their name and picture."""
        if not _known(user):
            return None
        profile = self._profile_of(user)  # type: ignore[arg-type]
        if profile is None:
            return None
        avatar = profile.get("avatar")
        return {"name": profile["name"], "avatar": avatar} if isinstance(avatar, str) and avatar else {"name": profile["name"]}

    def _user_has_keys(self, user: Optional[UserId]) -> bool:
        if not _known(user):
            return True
        return self._has_keys is None or self._has_keys(user) is not False  # type: ignore[arg-type]

    def _user_entries(self, user: Optional[UserId]) -> List[str]:
        return self.keys.user_entries(user) if _known(user) and self._user_has_keys(user) else []

    def _newest(self, label: str) -> str:
        kind, rest = label.split(":", 1)
        newest = ""
        if kind == "ch":
            match = re.fullmatch(r"(.+):\d{1,9}", rest)
            if match:
                newest = self.keys.room_label(match.group(1))
        elif kind in self._kinds and self._kinds[kind][1] is not None:
            newest = str(self._kinds[kind][1](rest, label))  # type: ignore[misc]
        return newest if valid_label(newest) and newest != label and newest.startswith(kind + ":") else ""

    def _authorize_stream(self, name: Any, user: Optional[UserId]) -> Dict[str, Any]:
        """Easy Stream's grant for a live stream, as its rule answers for this user: their role, name and picture, chat
        and what they may send, with the stream's settings. Denied ``bad_request`` for a name that isn't a stream's,
        ``forbidden`` where the rule says no, ``no_user`` where it gives a visitor more than a viewer's place."""
        if not isinstance(name, str) or not _STREAM_NAME.match(name):
            return {"denied": "bad_request"}
        found = self._stream_rules.match(name)
        if found is None:
            return {"denied": "forbidden"}

        signed_in = _known(user)
        answer = found["value"]["rule"](user if signed_in else None, found["params"], name)
        if isinstance(answer, str):
            answer = {"role": answer}
        if not isinstance(answer, dict) or answer.get("role") not in ("host", "guest", "viewer"):
            return {"denied": "forbidden"}

        sub = str(user) if signed_in else None
        if (answer["role"] != "viewer") if sub is None else not _STREAM_USER.match(sub):
            return {"denied": "no_user"}

        info = answer.get("info") if answer.get("info") is not None else self._default_info(user)
        named = info.get("name") if isinstance(info, dict) and isinstance(info.get("name"), str) and info.get("name") else None
        avatar = info.get("avatar") if isinstance(info, dict) else None
        if not (isinstance(avatar, str) and len(avatar) <= 512 and avatar.startswith("https://")):
            avatar = None

        params = found["params"]
        settings = found["value"]["settings"]

        def setting(value: Any) -> Any:
            return value(params) if callable(value) else value

        chat = setting(settings["chat"]) or {}
        now = self._now()
        exp = now + STREAM_TTL

        claims = {
            "iss": self.site, "aud": GRANT_AUDIENCE, "str": name, "role": answer["role"], "sub": sub,
            "name": named[:64] if named else None, "avatar": avatar, "chat": answer.get("chat"), "mod": answer.get("mod"),
            "src": answer.get("src"), "q": answer.get("quality"),
            "stage": setting(settings["stage"]), "offline": chat.get("offline"), "links": chat.get("links"),
            "fresh": chat.get("fresh"), "people": setting(settings["people"]), "reactions": setting(settings["reactions"]),
            "iat": now, "exp": exp,
        }
        key = hmac.new(self._secret, GRANT_KEY_LABEL.encode("ascii"), hashlib.sha256).digest()
        return {"token": stream_grant(claims, key), "exp": exp}

    def _sign_calls(self, claims: Dict[str, Any]) -> Dict[str, Any]:
        now = self._now()
        exp = now + _clamp(self._call_token_ttl, 60, CALL_TTL)
        key = hmac.new(self._secret, CALLS_LABEL.encode("ascii"), hashlib.sha256).digest()
        return {"token": _jwt({"iss": self.site, "iat": now, "exp": exp, **claims}, key), "exp": exp}

    def _sealed_call_info(self, info: Any) -> Any:
        """A call's or a group call's info, sealed with the day's key: everyone the app knows opens it."""
        if info is None or not self._seal:
            return info
        return self.keys.seal_json(info, self.keys.day_label()) or info

    def _signed(self, method: str, path: str, body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """A request to the realtime server, signed as the app: an HMAC-SHA256 over
        "{timestamp}\\n{METHOD}\\n{path with query}\\n{sha256 of the body}", with the publish key derived from its secret."""
        url = self._api + path
        raw = b"" if body is None else dumps(body).encode("utf-8")
        parsed = urllib.parse.urlsplit(url)
        signed_path = parsed.path + ("?" + parsed.query if parsed.query else "")
        timestamp = str(self._now())
        key = hmac.new(self._secret, PUBLISH_LABEL.encode("ascii"), hashlib.sha256).digest()
        message = timestamp + "\n" + method + "\n" + signed_path + "\n" + hashlib.sha256(raw).hexdigest()
        headers = {
            "Content-Type": "application/json",
            "X-WordPlus-Site": self.site,
            "X-WordPlus-Timestamp": timestamp,
            "X-WordPlus-Signature": hmac.new(key, message.encode("utf-8"), hashlib.sha256).hexdigest(),
        }
        status, answer = self._http(method, url, headers, None if body is None else raw)
        try:
            decoded = json.loads(answer.decode("utf-8") or "null")
        except (ValueError, UnicodeDecodeError):
            decoded = None
        if status != 200 or not isinstance(decoded, dict) or not decoded.get("ok"):
            raise RealtimeError(str(decoded["error"]) if isinstance(decoded, dict) and decoded.get("error") else "http_" + str(status), status)
        return decoded

    def _token_key(self) -> bytes:
        return hmac.new(self._secret, TOKEN_LABEL.encode("ascii"), hashlib.sha256).digest()


def _urlopen(method: str, url: str, headers: Dict[str, str], body: Optional[bytes]) -> Tuple[int, bytes]:
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310 (the realtime server's address)
            return response.status, response.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except (urllib.error.URLError, OSError):
        raise RealtimeError("unreachable") from None
