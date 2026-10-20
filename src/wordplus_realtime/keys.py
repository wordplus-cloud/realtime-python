"""The keys that seal what an app sends through the realtime server, so WordPlus Cloud carries it without being able to
read or change it: the WordPress package's WordPlus_Realtime_Keys, label for label, derived from the app's local key in
place of WordPress's master key.

- ``d:{day}`` the day's key (UTC days since 1970), for what everyone the app knows may see.
- ``u:{id}:{generation}`` a user's own, for what goes to them alone.
- ``ch:{room}:{generation}`` a sealed room's, for its events and its members' info (the label's kind kept from
  protocol 2's channels).
- an app's own kinds (``Realtime.kind()``).

A key is ``HMAC-SHA256(local key, "wordplus-realtime key v1|" + label)``, and a sealed value
``{label}:1.{base64url(nonce + ciphertext)}``, XChaCha20-Poly1305 with the label as associated data.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import time
from typing import Any, Dict, List, Optional, Protocol, Union

from nacl.bindings import crypto_aead_xchacha20poly1305_ietf_decrypt, crypto_aead_xchacha20poly1305_ietf_encrypt
from nacl.exceptions import CryptoError

from .patterns import valid_room

DERIVE = "wordplus-realtime key v1|"
# A room's media key's derivation, and a call's proofs', apart from the labels' so no label names one.
MEDIA = "wordplus-realtime media v1|"
PROOF = "wordplus-realtime proof v1|"
FORMAT = "1"
NONCE_BYTES = 24
LABEL = r"[a-z][a-z0-9]{0,15}:[A-Za-z0-9_\-=@,.;:]{1,240}"
RESERVED = ("d", "u", "ch")
MAX_LABELS = 100

_LABEL = re.compile("^" + LABEL + "$")
_SEALED = re.compile("^(" + LABEL + "):" + FORMAT + r"\.([A-Za-z0-9_-]+)$")
# The characters of an id a label carries as they are: those of room names, but `=`, which escapes the others.
_LABEL_SAFE = re.compile(r"^[A-Za-z0-9_\-@,.;:]$")

UserId = Union[int, str]


def label_user(user: UserId) -> Optional[str]:
    """A user id as a label carries it (ids such as Auth0's ``auth0|5f7c…``): as it is when every character is one labels
    take, else each other character, ``=`` among them, as ``=`` and the hex of its UTF-8 bytes (``auth0=7C5f7c``), so no
    two ids share a label. None for an id of more than 64 characters, or with a space or a control character. The Node
    and PHP packages write the same."""
    text = str(user)
    if text == "" or len(text) > 64 or re.search(r"[\s\x00-\x1f\x7f]", text):
        return None
    out = "".join(char if _LABEL_SAFE.match(char) else "".join("=%02X" % byte for byte in char.encode("utf-8")) for char in text)
    return out if len(out) <= 200 else None


class GenerationStore(Protocol):
    """Where an app keeps its keys' generations (``ch:{room}`` and ``u:{id}``), so moving one on holds across its
    servers: a database row, a cache that doesn't evict."""

    def get(self, name: str) -> Optional[int]: ...

    def set(self, name: str, generation: int) -> None: ...


def dumps(data: Any) -> str:
    """JSON as the browser and the realtime server read it."""
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False)


def base64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def unbase64url(data: str) -> Optional[bytes]:
    try:
        return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
    except (ValueError, TypeError):
        return None


def valid_label(label: Any) -> bool:
    return isinstance(label, str) and len(label) <= 256 and _LABEL.match(label) is not None


def label_of(value: Any) -> Optional[str]:
    """The label of the key that opens a sealed value, or None when it isn't one."""
    if not isinstance(value, str):
        return None
    match = _SEALED.match(value)
    return match.group(1) if match else None


def day_of(at: Optional[float] = None) -> int:
    """Today, in UTC days since 1970, or the day of a unix time."""
    return int((time.time() if at is None else at) // 86400)


class Keys:
    def __init__(self, master: str, store: Optional[GenerationStore] = None) -> None:
        if not isinstance(master, str) or re.fullmatch(r"[0-9a-f]{64}", master) is None:
            raise ValueError("wordplus-realtime: the local key must be 64 hex characters (openssl rand -hex 32)")
        self._master = master.encode("ascii")
        self._store = store
        self._derived: Dict[str, bytes] = {}

    def media(self, what: str) -> str:
        """The key a room's media is encrypted with end to end, base64url: ``call|{call}|{call id}|{caller}|{callee}`` for a
        call's rooms, ``room|{room}`` for a group call's room whose prefix encrypts it. Only the calls route gives it out."""
        return base64url(hmac.new(self._master, (MEDIA + what).encode("utf-8"), hashlib.sha256).digest())

    def proof(self, what: str) -> str:
        """A proof only this app's server makes, base64url: a user is in a call, or was rung into it (``member|…``,
        ``rung|…``)."""
        return base64url(hmac.new(self._master, (PROOF + what).encode("utf-8"), hashlib.sha256).digest())

    def key(self, label: str) -> bytes:
        """The key a label names, 32 bytes; also the profile hash's, under a name no label takes."""
        found = self._derived.get(label)
        if found is None:
            if len(self._derived) > 10000:
                self._derived.clear()
            found = hmac.new(self._master, (DERIVE + label).encode("utf-8"), hashlib.sha256).digest()
            self._derived[label] = found
        return found

    def entry(self, label: str) -> str:
        """A label and its key as a browser keeps them, ``{label}:{64 hex}``, or '' for a label that isn't one."""
        return label + ":" + self.key(label).hex() if valid_label(label) else ""

    def seal(self, value: str, label: str, nonce: Optional[bytes] = None) -> Optional[str]:
        if not valid_label(label):
            return None
        nonce = nonce if nonce is not None else os.urandom(NONCE_BYTES)
        sealed = crypto_aead_xchacha20poly1305_ietf_encrypt(value.encode("utf-8"), label.encode("utf-8"), nonce, self.key(label))
        return label + ":" + FORMAT + "." + base64url(nonce + sealed)

    def seal_json(self, data: Any, label: str) -> Optional[str]:
        return self.seal(dumps(data), label)

    def open(self, value: Any) -> Optional[str]:
        """The plain value of one this app sealed, or None: not a sealed value, another app's, or changed on the way."""
        if not isinstance(value, str):
            return None
        match = _SEALED.match(value)
        raw = unbase64url(match.group(2)) if match else None
        if match is None or raw is None or len(raw) < NONCE_BYTES + 16:
            return None
        label = match.group(1)
        try:
            plain = crypto_aead_xchacha20poly1305_ietf_decrypt(raw[NONCE_BYTES:], label.encode("utf-8"), raw[:NONCE_BYTES], self.key(label))
        except CryptoError:
            return None
        return plain.decode("utf-8")

    def day_label(self, day: Optional[int] = None) -> str:
        return "d:" + str(day_of() if day is None else day)

    def user_generation(self, user: UserId) -> int:
        stored = self._store.get("u:" + str(user)) if self._store else None
        return max(1, int(stored or 1))

    def user_label(self, user: Optional[UserId]) -> str:
        """A user's own key, its newest; '' for nobody or an id labels can't carry."""
        part = None if user is None or user == 0 else label_user(user)
        if part is None:
            return ""
        return "u:" + part + ":" + str(self.user_generation(user))

    def rotate_user(self, user: UserId) -> None:
        """The user's next key, which the one they had doesn't open: when their access is revoked."""
        self._need_store().set("u:" + str(user), self.user_generation(user) + 1)

    def room_generation(self, room: str) -> int:
        stored = self._store.get("ch:" + room) if self._store else None
        return max(1, int(stored or 1))

    def room_label(self, room: str) -> str:
        """A room's key, its newest; '' for a name that isn't one. Whether a room is sealed is its rule's to say."""
        if not valid_room(room):
            return ""
        return "ch:" + room + ":" + str(self.room_generation(room))

    def rotate_room(self, room: str) -> None:
        """A room's next key, when someone lost access to it: what it carries from now on is sealed from them."""
        if valid_room(room):
            self._need_store().set("ch:" + room, self.room_generation(room) + 1)

    def user_entries(self, user: Optional[UserId]) -> List[str]:
        """The keys a user starts with: their own, and the day's from yesterday's to tomorrow's. None for nobody."""
        own = self.user_label(user)
        if own == "":
            return []
        today = day_of()
        return [self.entry(own)] + [self.entry(self.day_label(today + offset)) for offset in (-1, 0, 1)]

    def profile(self, user: UserId, plain: Dict[str, Any], seal: bool = True) -> Dict[str, Any]:
        """A user's entry in the directory: ``pd``, the profile with every text sealed with the day's key however deep,
        and ``pdh``, an HMAC of the plain profile under a key derived from the local key."""
        full = dict(plain)
        full["user_id"] = user
        label = self.day_label()
        pd: Dict[str, Any] = {}
        for field, value in full.items():
            # The id stays as it is, a number or a string: the server keys the entry by it.
            if field == "user_id":
                pd["user_id"] = user
                continue
            kept = self._sealed_value(value, label, seal, 0)
            if kept is not None or value is None:
                pd[field] = kept
        return {"pd": pd, "pdh": hmac.new(self.key("profile-hash"), dumps(full).encode("utf-8"), hashlib.sha256).hexdigest()}

    def _sealed_value(self, value: Any, label: str, seal: bool, depth: int) -> Any:
        if isinstance(value, str):
            return self.seal(value, label) if seal and value != "" else value
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if depth >= 8:
            return None
        if isinstance(value, (list, tuple)):
            return [self._sealed_value(item, label, seal, depth + 1) for item in value]
        if isinstance(value, dict):
            return {str(k): self._sealed_value(item, label, seal, depth + 1) for k, item in value.items()}
        return None

    def _need_store(self) -> GenerationStore:
        if self._store is None:
            raise RuntimeError("wordplus-realtime: rotating a key needs a generation store (the `generations` option)")
        return self._store
