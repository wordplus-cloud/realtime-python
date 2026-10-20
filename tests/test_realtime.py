"""The package against the conformance vectors (spec/vectors.json, @wordplus/realtime's scripts/vectors.php), and as
the browser uses its routes: what @wordplus/realtime's server part answers, case for case with its test/server.test.ts."""

import base64
import hashlib
import hmac
import json
import os
import pathlib
import re
import warnings

import pytest

from wordplus_realtime import Keys, Patterns, Realtime, RealtimeError, day_of
from wordplus_realtime.keys import base64url
from wordplus_realtime.realtime import FILES_DIR, MAX_HISTORY_DAYS

V = json.loads((pathlib.Path(__file__).parent.parent / "spec" / "vectors.json").read_text())
API = "https://rest.example.test"

keys = Keys(V["local_key"])


def app(sent=None, answer=None, **options):
    """An app whose requests to the realtime server are recorded in ``sent`` and answered by ``answer(path)``."""

    def http(method, url, headers, body):
        path = url[len(API) :]
        if sent is not None:
            sent.append({"method": method, "url": url, "path": path, "headers": headers, "raw": body, "body": None if body is None else json.loads(body)})
        return 200, json.dumps({"ok": True} if answer is None else answer(path)).encode()

    defaults = {"api": API, "profile": lambda user: {"name": "User " + str(user), "avatar": "https://example.com/" + str(user) + ".png"}, "http": http}
    return Realtime(V["site"], V["secret"], V["local_key"], **{**defaults, **options})


def claims(token, label):
    """A token's claims, after checking its signature with the key it should be signed with."""
    header, payload, signature = token.split(".")
    key = hmac.new(V["secret"].encode(), label.encode(), hashlib.sha256).digest()
    assert base64url(hmac.new(key, (header + "." + payload).encode(), hashlib.sha256).digest()) == signature
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


class Store:
    def __init__(self):
        self.values = {}

    def get(self, name):
        return self.values.get(name)

    def set(self, name, generation):
        self.values[name] = generation


def test_the_vectors_keys_call_key_sealed_values_media_keys_and_proofs():
    for case in V["keys"]:
        assert keys.entry(case["label"]) == case["entry"]
    assert keys.key("profile-hash").hex() == V["profile_hash_key"]
    assert app().call_key(V["call_key"]["id"], V["call_key"]["caller"], V["call_key"]["callee"]) == V["call_key"]["key"]

    for case in V["sealed"]:
        assert keys.seal(case["plain"], case["label"], bytes.fromhex(case["nonce_hex"])) == case["sealed"]
        assert keys.open(case["sealed"]) == case["plain"]

    first = V["sealed"][0]
    assert keys.open(first["sealed"].replace(first["label"], "ch:order:43:1")) is None
    assert Keys("0" * 64).open(first["sealed"]) is None

    for media in V["media"]:
        assert keys.media(media["what"]) == media["key"]
    for proof in V["proofs"]:
        assert keys.proof(proof["what"]) == proof["proof"]


def test_an_emit_is_signed_as_the_vectors_say():
    sent = []
    app(sent).to("orders").emit("updated", {"status": "paid"})

    request = sent[0]
    assert request["path"] == V["emit"]["path"]
    assert request["raw"].decode() == V["emit"]["body"]
    assert request["headers"]["X-WordPlus-Site"] == V["site"]
    key = hmac.new(V["secret"].encode(), b"wordplus-realtime publish v1", hashlib.sha256).digest()
    assert key.hex() == V["derived"]["publish"]
    sign = lambda timestamp: hmac.new(key, (timestamp + "\nPOST\n" + V["emit"]["path"] + "\n" + hashlib.sha256(V["emit"]["body"].encode()).hexdigest()).encode(), hashlib.sha256).hexdigest()  # noqa: E731
    assert request["headers"]["X-WordPlus-Signature"] == sign(request["headers"]["X-WordPlus-Timestamp"])
    assert sign(V["emit"]["timestamp"]) == V["emit"]["signature"]


def test_a_local_key_must_be_64_hex_and_the_credentials_given():
    with pytest.raises(ValueError):
        Realtime(V["site"], V["secret"], "short")
    with pytest.raises(ValueError):
        Realtime("", V["secret"], V["local_key"])


def test_patterns_match_a_rooms_parts_the_rule_with_most_of_its_own_characters_deciding():
    p = Patterns()
    p.add("chat:{a}:{b}", "chat")
    p.add("chat:{a}:support", "support")
    p.add("order:{id}", "order")
    p.add("order.{id}", "laravel")
    p.add("{any}", "fallback")

    assert p.match("chat:34:42") == {"pattern": "chat:{a}:{b}", "value": "chat", "params": {"a": "34", "b": "42"}}
    assert p.match("chat:34:support")["value"] == "support"
    assert p.match("order:42")["params"] == {"id": "42"}
    assert p.match("order.42")["value"] == "laravel"
    assert p.match("order:42:x") is None
    assert p.match("news")["value"] == "fallback"
    with pytest.raises(ValueError, match="not a pattern"):
        p.add("bad pattern", "x")


def test_the_auth_route_signs_one_token_for_the_rooms_allowed_with_their_options_and_keys():
    realtime = app()
    realtime.room("order:{id}", lambda user, p: user == 42 and p["id"] == "42", history=20)
    realtime.room(
        "chat:{a}:{b}",
        lambda user, p: {"info": {"name": "Ben", "role": "Customer"}} if str(user) in (p["a"], p["b"]) else False,
        presence=True, history={"last": 500, "days": 7}, emit=["message", "typing"], webhook=["message"],
    )
    realtime.room("news", public=True, count=True)
    realtime.room("board:{id}", lambda user: {"readOnly": True} if user == 42 else True, emit="*")

    grant = realtime.authorize(["order:42", "chat:34:42", "news", "board:1", "order:43", "nobody:1", "bad room", "order:42"], 42)
    assert grant["denied"] == {"order:43": "forbidden", "nobody:1": "no_rule", "bad room": "bad_room"}

    c = claims(grant["token"], "wordplus-realtime channels v1")
    assert (c["iss"], c["aud"], c["sub"]) == (V["site"], "wordplus-realtime", "42")
    assert c["r"] == {
        "order:42": {"h": [20, MAX_HISTORY_DAYS]},
        "chat:34:42": {"p": 1, "h": [500, MAX_HISTORY_DAYS], "e": ["message", "typing"], "w": ["message"]},
        "news": {"c": 1},
        "board:1": {"e": "*", "ro": 1},
    }
    assert c["exp"] - c["iat"] == 21600
    assert json.loads(keys.open(c["infos"]["chat:34:42"])) == {"name": "Ben", "role": "Customer"}

    # The sealed rooms' keys come with the token; a public room is not sealed.
    assert grant["keys"] == [keys.entry("ch:order:42:1"), keys.entry("ch:chat:34:42:1"), keys.entry("ch:board:1:1")]
    assert json.dumps(realtime.authorize([], 7)) == '{"denied": {}}'


def test_a_rooms_history_keeps_a_part_of_a_day_and_the_cloud_limit_when_days_is_missing_or_not_above_0():
    realtime = app()
    realtime.room("a:{id}", lambda user: True, history={"last": 30, "days": 0.002})
    realtime.room("b:{id}", lambda user: True, history={"last": 30, "days": "0.002"})
    realtime.room("c:{id}", lambda user: True, history={"last": 30})
    realtime.room("d:{id}", lambda user: True, history={"last": 30, "days": 0})
    realtime.room("e:{id}", lambda user: True, history={"last": 30, "days": 1})

    # The realtime server refuses a room whose history keeps 0 days, so `days` 0.002 must stay 0.002.
    c = claims(realtime.authorize(["a:1", "b:1", "c:1", "d:1", "e:1"], 42)["token"], "wordplus-realtime channels v1")
    assert c["r"] == {
        "a:1": {"h": [30, 0.002]},
        "b:1": {"h": [30, 0.002]},
        "c:1": {"h": [30, MAX_HISTORY_DAYS]},
        "d:1": {"h": [30, MAX_HISTORY_DAYS]},
        "e:1": {"h": [30, MAX_HISTORY_DAYS]},
    }


def test_nobody_gets_presence_a_public_room_needs_no_rule_and_info_stays_plain_when_sealing_is_off():
    realtime = app(seal=False)
    realtime.room("lobby", lambda user: True, presence=True)
    realtime.room("product:{id}", public=True, count=True)

    assert realtime.authorize(["lobby"], None)["denied"] == {"lobby": "forbidden"}
    assert "sub" not in claims(realtime.authorize(["product:7"], None)["token"], "wordplus-realtime channels v1")

    many = realtime.authorize(["product:" + str(i) for i in range(101)], 7)
    assert many["denied"] == {"product:100": "too_many"}

    plain = claims(realtime.authorize(["lobby"], 7)["token"], "wordplus-realtime channels v1")
    assert plain["info"] == {"name": "User 7", "avatar": "https://example.com/7.png"}
    assert "infos" not in plain
    assert "keys" not in realtime.authorize(["lobby"], 7)


def test_a_room_needs_a_rule_and_a_public_room_has_no_members():
    realtime = app()
    with pytest.raises(ValueError, match="needs a rule"):
        realtime.room("order:{id}")
    with pytest.raises(ValueError, match="public room"):
        realtime.room("lobby", public=True, presence=True)


def test_every_page_gets_a_grant_for_the_public_rooms_made_once_and_again_before_it_runs_out():
    now = [1791676800]
    realtime = app(now=lambda: now[0])
    realtime.room("product:{id}", public=True, count=True)
    realtime.room("scores", public=True, history=10)
    realtime.room("order:{id}", lambda user: True)

    [grant] = realtime.public_grants()
    assert grant["rooms"] == ["product:{id}", "scores"]
    c = claims(grant["token"], "wordplus-realtime channels v1")
    assert c["r"] == {"product:{id}": {"c": 1}, "scores": {"h": [10, MAX_HISTORY_DAYS]}}
    assert "sub" not in c
    assert realtime.public_grants()[0]["token"] == grant["token"]
    assert realtime.config(None)["grants"] == [grant]

    now[0] += 19800
    assert realtime.public_grants()[0]["token"] != grant["token"]
    assert app().public_grants() == []


def test_the_calls_route_signs_a_line_each_side_of_a_call_and_a_place_in_a_group_call():
    realtime = app()
    realtime.calls("support:{a}:{b}", lambda user, with_user, p: p["a"] in (str(user), str(with_user)))
    realtime.group_calls("meeting:{id}", lambda user: {"admin": user == 1, "info": {"name": "Agent"}})

    line = claims(realtime.authorize_call({"line": True}, 42)["token"], "wordplus-realtime calls v1")
    assert (line["aud"], line["sub"]) == ("wordplus-realtime line", 42)

    caller = realtime.authorize_call({"call": "support:42:34", "id": "abcDEF123_-xyz", "role": "caller", "to": 34, "type": "audio"}, 42)
    c = claims(caller["token"], "wordplus-realtime calls v1")
    assert {k: c[k] for k in ("call", "id", "sub", "role", "type", "to")} == {"call": "support:42:34", "id": "abcDEF123_-xyz", "sub": 42, "role": "caller", "type": "audio", "to": 34}
    assert json.loads(keys.open(c["info"])) == {"name": "User 42", "avatar": "https://example.com/42.png"}
    assert caller["key"] == V["call_key"]["key"]

    callee = realtime.authorize_call({"call": "support:42:34", "id": "abcDEF123_-xyz", "role": "callee", "from": "42"}, "34")
    assert callee["key"] == V["call_key"]["key"]

    room = claims(realtime.authorize_call({"room": "meeting:daily"}, 1)["token"], "wordplus-realtime calls v1")
    assert {k: room[k] for k in ("room", "publish", "subscribe", "admin", "hidden")} == {"room": "meeting:daily", "publish": True, "subscribe": True, "admin": True, "hidden": False}
    assert room["info"].startswith("d:" + str(day_of()) + ":1.")


def test_the_calls_rule_hears_which_side_asks_so_a_user_may_answer_calls_they_may_not_place():
    # Pro members place calls, anyone answers them (an SDK review, 2026-10-14).
    asked = []
    realtime = app()

    def rule(user, with_user, p, call, side):
        asked.append([user, side["role"]])
        return side["role"] == "callee" or user == "user_ann"

    realtime.calls("dm:{a}:{b}", rule)
    # A rule of three arguments, as before, still works.
    realtime.calls("help:{id}", lambda user, with_user, p: True)

    assert "token" in realtime.authorize_call({"call": "dm:user_ann:user_cara", "id": "abcdefgh", "role": "caller", "to": "user_cara"}, "user_ann")
    assert "token" in realtime.authorize_call({"call": "dm:user_ann:user_cara", "id": "abcdefgh", "role": "callee", "from": "user_ann"}, "user_cara")
    assert realtime.authorize_call({"call": "dm:user_ann:user_cara", "id": "ijklmnop", "role": "caller", "to": "user_ann"}, "user_cara") == {"denied": "forbidden"}
    assert asked == [["user_ann", "caller"], ["user_cara", "callee"], ["user_cara", "caller"]]
    assert "token" in realtime.authorize_call({"call": "help:1", "id": "abcdefgh", "role": "caller", "to": 2}, 1)


def test_the_calls_route_refuses_nobody_an_id_with_a_space_what_nobody_owns_and_what_isnt_a_request():
    realtime = app()
    realtime.calls("support:{id}", lambda user: True)

    assert realtime.authorize_call({"line": True}, None) == {"denied": "no_user"}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        assert realtime.authorize_call({"line": True}, "ann smith") == {"denied": "no_user"}
        assert realtime.authorize_call({"line": True}, "a" * 65) == {"denied": "no_user"}
    # An id of text is a user like any other, and one of digits a number.
    assert claims(realtime.authorize_call({"line": True}, "user_2abc")["token"], "wordplus-realtime calls v1")["sub"] == "user_2abc"
    assert claims(realtime.authorize_call({"line": True}, "42")["token"], "wordplus-realtime calls v1")["sub"] == 42
    assert realtime.authorize_call({"call": "sales:1", "id": "abcdefgh", "role": "caller", "to": 2}, 1) == {"denied": "forbidden"}
    assert realtime.authorize_call({"room": "meeting:1"}, 1) == {"denied": "forbidden"}
    assert realtime.authorize_call({"call": "support:1", "id": "short", "role": "caller", "to": 2}, 1) == {"denied": "bad_request"}
    assert realtime.authorize_call({"call": "support:1", "id": "abcdefgh", "role": "caller", "to": 1}, 1) == {"denied": "bad_request"}
    assert realtime.authorize_call({"room": "bad room"}, 1) == {"denied": "bad_request"}


def test_a_call_gives_both_sides_its_rooms_key_its_pair_and_each_ones_proof_of_being_in_it():
    realtime = app()
    realtime.calls("support-42", lambda user: True)

    caller = realtime.authorize_call({"call": "support-42", "id": "abcDEF123_-xyz", "role": "caller", "to": 34}, 42)
    callee = realtime.authorize_call({"call": "support-42", "id": "abcDEF123_-xyz", "role": "callee", "from": 42}, 34)

    assert [caller["media_key"], callee["media_key"]] == [V["media"][0]["key"]] * 2
    assert [caller["pair"], callee["pair"]] == [[42, 34], [42, 34]]
    assert caller["member"] == V["proofs"][0]["proof"]
    assert caller["member"] != callee["member"]
    assert "ring" not in caller


def test_someone_in_a_call_rings_a_person_in_with_their_proof_and_the_person_answers_with_the_ring():
    realtime = app()
    realtime.calls("support-42", lambda user: True)
    caller = realtime.authorize_call({"call": "support-42", "id": "abcDEF123_-xyz", "role": "caller", "to": 34}, 42)
    group = {"call": "support-42", "group": "abcDEF123_-xyz", "pair": caller["pair"]}

    ring = realtime.authorize_call({**group, "id": "ringCara0001", "role": "caller", "to": 56, "member": caller["member"]}, 42)
    c = claims(ring["token"], "wordplus-realtime calls v1")
    assert (c["sub"], c["to"], c["group"]) == (42, 56, "abcDEF123_-xyz")
    assert ring["ring"] == V["proofs"][1]["proof"]

    answer = realtime.authorize_call({**group, "id": "ringCara0001", "role": "callee", "from": 42, "ring": ring["ring"]}, 56)
    c = claims(answer["token"], "wordplus-realtime calls v1")
    assert (c["sub"], c["group"]) == (56, "abcDEF123_-xyz")
    assert answer["media_key"] == caller["media_key"]

    # Someone else's proof, none, another pair; another's ring; a pair that isn't two people; the ring's own id as the call.
    assert realtime.authorize_call({**group, "id": "ringCara0002", "role": "caller", "to": 78, "member": caller["member"]}, 34) == {"denied": "forbidden"}
    assert realtime.authorize_call({**group, "id": "ringCara0002", "role": "caller", "to": 78}, 42) == {"denied": "forbidden"}
    assert realtime.authorize_call({**group, "pair": [42, 35], "id": "ringCara0002", "role": "caller", "to": 78, "member": caller["member"]}, 42) == {"denied": "forbidden"}
    assert realtime.authorize_call({**group, "id": "ringCara0001", "role": "callee", "from": 42, "ring": ring["ring"]}, 57) == {"denied": "forbidden"}
    assert realtime.authorize_call({**group, "pair": [42, 42], "id": "ringCara0001", "role": "callee", "from": 42, "ring": ring["ring"]}, 56) == {"denied": "bad_request"}
    assert realtime.authorize_call({**group, "group": "ringCara0001", "id": "ringCara0001", "role": "callee", "from": 42, "ring": ring["ring"]}, 56) == {"denied": "bad_request"}


def test_calls_between_users_whose_ids_are_text_their_keys_and_proofs_never_the_same_for_two_pairs():
    realtime = app()
    realtime.calls("support-{id}", lambda user: True)

    # Ann, an id of Clerk, calls Ben, of Auth0, whose id holds the `|` keys are joined with: escaped there, as Node does.
    caller = realtime.authorize_call({"call": "support-1", "id": "abcDEF123_-xyz", "role": "caller", "to": "auth0|5f7c"}, "user_2abc")
    told = claims(caller["token"], "wordplus-realtime calls v1")
    assert (told["sub"], told["to"]) == ("user_2abc", "auth0|5f7c")
    assert caller["pair"] == ["user_2abc", "auth0|5f7c"]
    assert caller["media_key"] == keys.media("call|support-1|abcDEF123_-xyz|user_2abc|auth0%7C5f7c")

    # Another pair that would join to the same string unescaped: another key, and the proof of one is not that of the other.
    other = realtime.authorize_call({"call": "support-1", "id": "abcDEF123_-xyz", "role": "caller", "to": "5f7c"}, "user_2abc|auth0")
    assert other["media_key"] != caller["media_key"]
    ring = {"call": "support-1", "group": "abcDEF123_-xyz", "id": "ringCara0001", "role": "caller", "to": "cara@shop.example"}
    assert realtime.authorize_call({**ring, "pair": other["pair"], "member": caller["member"]}, "user_2abc") == {"denied": "forbidden"}
    rang = realtime.authorize_call({**ring, "pair": caller["pair"], "member": caller["member"]}, "user_2abc")
    assert claims(rang["token"], "wordplus-realtime calls v1")["to"] == "cara@shop.example"


def test_the_calls_route_takes_what_the_host_of_a_group_call_does_and_nothing_from_anyone_else():
    sent = []
    realtime = app(sent, lambda path: {"ok": True, "changed": False} if path.endswith("/permit") else {"ok": True, "muted": True, "removed": True})
    realtime.group_calls("meeting:{id}", lambda user: {"admin": True} if user == 1 else True)

    assert realtime.authorize_call({"moderate": "meeting:7", "act": "mute", "user": 42}, 1) == {"done": True}
    assert realtime.authorize_call({"moderate": "meeting:7", "act": "speak", "user": "auth0|5f7c8e"}, 1) == {"done": False}
    assert realtime.authorize_call({"moderate": "meeting:7", "act": "listen", "user": 42}, 1) == {"done": False}
    assert realtime.authorize_call({"moderate": "meeting:7", "act": "remove", "user": "42"}, 1) == {"done": True}
    assert [(s["path"], s["body"]) for s in sent] == [
        ("/wordplus/realtime/calls/meeting%3A7/mute", {"user": "42", "track": "microphone"}),
        ("/wordplus/realtime/calls/meeting%3A7/permit", {"user": "auth0|5f7c8e", "publish": True}),
        ("/wordplus/realtime/calls/meeting%3A7/permit", {"user": "42", "publish": False}),
        ("/wordplus/realtime/calls/meeting%3A7/remove", {"user": "42"}),
    ]

    # Someone in it who isn't its host, a call no rule owns, an act or a person that isn't one, and the host themselves.
    sent.clear()
    assert realtime.authorize_call({"moderate": "meeting:7", "act": "remove", "user": 1}, 42) == {"denied": "forbidden"}
    assert realtime.authorize_call({"moderate": "board:7", "act": "remove", "user": 42}, 1) == {"denied": "forbidden"}
    assert realtime.authorize_call({"moderate": "meeting:7", "act": "end", "user": 42}, 1) == {"denied": "bad_request"}
    assert realtime.authorize_call({"moderate": "meeting:7", "act": "mute", "user": "two words"}, 1) == {"denied": "bad_request"}
    assert realtime.authorize_call({"moderate": "meeting:7", "act": "mute", "user": 1}, 1) == {"denied": "bad_request"}
    assert sent == []

    failing = app(http=lambda method, url, headers, body: (500, b'{"ok":false,"error":"server"}'))
    failing.group_calls("meeting:{id}", lambda user: {"admin": True})
    assert failing.authorize_call({"moderate": "meeting:7", "act": "mute", "user": 42}, 1) == {"denied": "server"}


def test_the_calls_route_answers_whether_a_user_may_call_each_person_for_the_call_buttons_of_a_list():
    profiles = []
    realtime = app(profile=lambda user: profiles.append(user) or {"name": "Someone"})
    sides = []

    def rule(user, with_user, params, call, side):
        sides.append(side["role"])
        return with_user != 56

    realtime.calls("support:{a}:{b}", rule)

    asks = [{"call": "support:34:42", "to": 34}, {"call": "support:42:56", "to": 56}, {"call": "meeting:1", "to": 34}, {"call": "support:42:42", "to": 42}, {"call": "support:42:x", "to": "two words"}, "junk"]
    assert realtime.authorize_call({"may": asks}, 42) == {"may": [True, False, False, False, False, False]}
    assert sides == ["caller", "caller"]
    # No profile is looked up for an answer no call is made with.
    assert profiles == []
    assert realtime.authorize_call({"may": [{"call": "support:34:42", "to": 34}] * 101}, 42) == {"denied": "bad_request"}
    assert realtime.authorize_call({"may": "support:34:42"}, 42) == {"denied": "bad_request"}
    assert realtime.authorize_call({"may": []}, None) == {"denied": "no_user"}


def test_the_calls_route_lists_whom_a_user_may_add_and_encrypts_a_group_call_whose_rule_says_so():
    realtime = app()
    realtime.calls("support:{id}", lambda user, with_user: with_user == 34 or user == 34, people=lambda user, call: [34, 56, 42, "two words", 0, 56])
    realtime.group_calls("board-{id}", lambda user: True, encrypt=True)
    realtime.group_calls("meeting:{id}", lambda user: True)

    assert realtime.authorize_call({"people": "support:42"}, 42)["people"] == [{"id": 34, "name": "User 34", "avatar": "https://example.com/34.png"}]
    assert [p["id"] for p in realtime.authorize_call({"people": "support:42"}, 34)["people"]] == [56, 42]
    assert realtime.authorize_call({"people": "board-1"}, 34) == {"people": []}
    assert realtime.authorize_call({"people": "bad name"}, 34) == {"denied": "bad_request"}

    assert realtime.authorize_call({"room": "board-7"}, 1)["media_key"] == V["media"][1]["key"]
    assert "media_key" not in realtime.authorize_call({"room": "meeting:daily"}, 34)
    assert realtime.config()["screen"] == {"add": True}


def test_a_user_is_labelled_by_their_id_any_id_of_text_included_never_two_ids_the_same():
    from wordplus_realtime.keys import label_user

    # As labels take them: the ids of digits, Clerk, UUIDs, emails without a plus. Each other character escaped, as Node does.
    assert [label_user(u) for u in [42, -7, "user_2abc", "0b6f1c9e-8f5d-4c38", "ann@shop.example"]] == ["42", "-7", "user_2abc", "0b6f1c9e-8f5d-4c38", "ann@shop.example"]
    assert label_user("auth0|5f7c") == "auth0=7C5f7c"
    assert label_user("a=b") == "a=3Db"
    assert label_user("a=7Cb") == "a=3D7Cb"
    assert label_user("ann+news@shop.example") == "ann=2Bnews@shop.example"
    assert label_user("Zoë") == "Zo=C3=AB"
    assert [label_user("ann smith"), label_user("a" * 65), label_user("")] == [None, None, None]

    # Such a user has their own key and an identity.
    start = app().keys_answer([], "auth0|5f7c")
    assert start["keys"][0] == keys.entry("u:auth0=7C5f7c:1")
    assert claims(start["identity"]["token"], "wordplus-realtime channels v1")["sub"] == "auth0|5f7c"


def test_the_keys_route_gives_a_users_keys_and_identity_and_the_keys_they_may_have():
    realtime = app()
    realtime.room("order:{id}", lambda user, p: user == 42 and p["id"] == "42")
    realtime.room("news", public=True)
    realtime.kind("note", lambda rest, user: rest == "7" and user == 42)
    today = day_of()

    start = realtime.keys_answer([], 42)
    assert start["keys"] == [keys.entry("u:42:1"), keys.entry("d:" + str(today - 1)), keys.entry("d:" + str(today)), keys.entry("d:" + str(today + 1))]
    identity = claims(start["identity"]["token"], "wordplus-realtime channels v1")
    assert (identity["aud"], identity["sub"]) == ("wordplus-realtime identity", "42")
    assert identity["pd"]["user_id"] == 42
    assert keys.open(identity["pd"]["name"]) == "User 42"
    assert len(identity["pdh"]) == 64
    assert "hid" not in identity

    asked = realtime.keys_answer(["d:" + str(today + 1), "d:" + str(today + 2), "u:42:1", "u:43:1", "ch:order:42:1", "ch:order:42:2", "ch:order:43:1", "ch:news:1", "note:7", "note:8", "nonsense"], 42)
    assert asked["keys"] == [keys.entry("d:" + str(today + 1)), keys.entry("u:42:1"), keys.entry("ch:order:42:1"), keys.entry("note:7")]
    assert realtime.keys_answer([], None) == {"keys": []}


def test_a_string_id_gets_its_keys_and_identity_and_a_hidden_user_is_marked():
    realtime = app(hidden=lambda user: user == "k7f3q:ben")

    start = realtime.keys_answer([], "k7f3q:ben")
    assert start["keys"][0] == keys.entry("u:k7f3q:ben:1")
    identity = claims(start["identity"]["token"], "wordplus-realtime channels v1")
    assert identity["pd"]["user_id"] == "k7f3q:ben"
    assert identity["sub"] == "k7f3q:ben"
    assert identity["hid"] is True


def test_a_rooms_key_moves_on_and_the_newest_comes_beside_an_older_one():
    realtime = app(generations=Store())
    realtime.room("team:{id}", lambda user: True)

    realtime.rotate_room("team:1")
    assert realtime.keys_answer(["ch:team:1:1"], 7) == {"keys": [keys.entry("ch:team:1:1"), keys.entry("ch:team:1:2")]}
    assert realtime.authorize(["team:1"], 7)["keys"] == [keys.entry("ch:team:1:2")]

    realtime.rotate_user("user_2abc")
    assert realtime.keys_answer([], "user_2abc")["keys"][0] == keys.entry("u:user_2abc:2")

    with pytest.raises(RuntimeError):
        app().rotate_room("team:1")


def test_no_key_for_a_user_cut_off_and_no_identity_without_a_profile():
    assert app(has_keys=lambda user: user != 42).keys_answer([], 42) == {"keys": []}
    assert "identity" not in app(profile=lambda user: None).keys_answer([], 42)


def test_an_emit_seals_a_sealed_rooms_data_a_copy_each_sends_the_others_together_and_says_which_keep_it():
    sent = []
    realtime = app(sent, lambda path: {"ok": True, "ids": [{"order:42": "1-0"}, {}]} if path.endswith("/batch") else {"ok": True, "ids": {}})
    realtime.room("order:{id}", lambda user: True, history=20)
    realtime.room("news", public=True, history=5)
    realtime.room("ticker", public=True)

    ids = realtime.to(["order:42", "news", "ticker"]).except_tab("tab-1").emit("updated", {"status": "paid"})
    assert ids == {"order:42": "1-0"}
    assert len(sent) == 1 and sent[0]["path"] == "/wordplus/realtime/emit/batch"
    sealed, plain = sent[0]["body"]["events"]
    assert {k: v for k, v in sealed.items() if k != "data"} == {"rooms": ["order:42"], "event": "updated", "history": {"order:42": [20, MAX_HISTORY_DAYS]}, "except": "tab-1"}
    assert json.loads(keys.open(sealed["data"])) == {"status": "paid"}
    assert plain == {"rooms": ["news", "ticker"], "event": "updated", "data": {"status": "paid"}, "history": {"news": [5, MAX_HISTORY_DAYS]}, "except": "tab-1"}


def test_an_emit_to_users_seals_each_with_their_own_key_and_binary_goes_as_b():
    sent = []
    realtime = app(sent)

    realtime.to_user([42, "k7f3q:ben"]).emit("notice", {"text": "Shipped", "photo": bytes([7, 8])})
    assert sent[0]["path"] == "/wordplus/realtime/emit/batch"
    first, second = sent[0]["body"]["events"]
    assert first["users"] == ["42"]
    assert json.loads(keys.open(first["data"])) == {"text": "Shipped", "photo": {"$b": "Bwg="}}
    assert second["users"] == ["k7f3q:ben"]
    assert second["data"].startswith("u:k7f3q:ben:1:1.")

    realtime.to_user(7).emit("plain", 1, seal=False)
    assert (sent[1]["path"], sent[1]["body"]) == ("/wordplus/realtime/emit", {"users": ["7"], "event": "plain", "data": 1})


def test_a_batch_sends_each_event_and_a_refusal_is_raised_with_the_servers_reason():
    sent = []
    realtime = app(sent)
    realtime.room("r{n}", public=True)
    realtime.batch([{"rooms": "r" + str(i), "event": "e"} for i in range(3)])
    assert [s["path"] for s in sent] == ["/wordplus/realtime/emit"] * 3

    refusing = app(http=lambda *a: (413, b'{"ok":false,"error":"too_large"}'))
    with pytest.raises(RealtimeError) as refused:
        refusing.to("r1").emit("e", "x")
    assert (refused.value.code, refused.value.status) == ("too_large", 413)
    with pytest.raises(RealtimeError):
        refusing.to("bad room").emit("e")


def test_reading_a_rooms_count_members_and_history_opened_erasing_it_and_kicking_a_user_out():
    sealed_info = keys.seal_json({"name": "Ann"}, "ch:chat:1:1")
    sealed_data = keys.seal_json({"text": "Hi", "photo": {"$b": "CQ=="}}, "ch:chat:1:1")

    def answer(path):
        if "/history" in path and "id=" not in path:
            return {"ok": True, "events": [{"id": "1-0", "at": 1, "event": "message", "data": sealed_data, "from": "34"}], "more": False}
        if path.endswith("?members=1"):
            return {"ok": True, "count": 1, "members": {"count": 1, "list": [{"id": "34", "info": sealed_info}]}}
        return {"ok": True, "count": 3, "deleted": 1}

    sent = []
    store = Store()
    realtime = app(sent, answer, generations=store)

    assert realtime.in_room("chat:1").count() == 3
    assert realtime.in_room("chat:1").members() == {"count": 1, "list": [{"id": "34", "info": {"name": "Ann"}}]}
    history = realtime.in_room("chat:1").history(limit=10)
    assert history["events"][0] == {"id": "1-0", "at": 1, "event": "message", "data": {"text": "Hi", "photo": b"\x09"}, "from": "34"}
    assert history["more"] is False
    assert realtime.in_room("chat:1").forget("1-0") == 1

    realtime.in_room("chat:1").kick(43)
    assert [(s["method"], s["path"]) for s in sent] == [
        ("GET", "/wordplus/realtime/rooms/chat%3A1"),
        ("GET", "/wordplus/realtime/rooms/chat%3A1?members=1"),
        ("GET", "/wordplus/realtime/rooms/chat%3A1/history?limit=10"),
        ("DELETE", "/wordplus/realtime/rooms/chat%3A1/history?id=1-0"),
        ("POST", "/wordplus/realtime/rooms/chat%3A1/kick"),
    ]
    assert sent[4]["body"] == {"user": "43"}
    assert store.get("ch:chat:1") == 2


def test_reading_who_is_online():
    sent = []
    realtime = app(sent, lambda path: {"ok": True, "count": 2, "online": [{"id": "34", "online": True}, {"id": "42", "online": False, "at": 5}]} if "ids=" in path else {"ok": True, "count": 2, "ids": ["34", "43"], "next": "0"})

    assert realtime.online.states([34, 42]) == [{"id": "34", "online": True}, {"id": "42", "online": False, "at": 5}]
    assert realtime.online.has(34) is True
    assert realtime.online.count() == 2
    assert realtime.online.list() == {"ids": ["34", "43"], "next": "0"}
    assert sent[0]["path"] == "/wordplus/realtime/online?ids=34,42"


def test_reaching_rooms_users_usage_the_webhook_group_calls_and_live_streams():
    reply = Keys(V["local_key"]).seal_json({"ok": 1}, "u:42:1")

    def answer(path):
        if path.startswith("/wordplus/realtime/rooms"):
            return {"ok": True, "count": 1, "rooms": [{"name": "shop:1", "count": 2, "connections": 2}], "next": "1"}
        if path.endswith("/ask"):
            return {"ok": True, "replies": [{"data": reply, "at": 7}]}
        if path.startswith("/wordplus/realtime/users/"):
            return {"ok": True, "user": {"id": "42", "online": True, "connections": 2}}
        if path == "/wordplus/realtime/usage":
            return {"ok": True, "connections": {"now": 3, "limit": 1000}, "credits": None}
        if path == "/wordplus/realtime/webhooks":
            return {"ok": True, "deliveries": [{"id": "b1", "status": 500, "resendable": True}]}
        if path.startswith("/wordplus/realtime/webhooks/"):
            return {"ok": True, "delivered": True, "status": 204}
        if path == "/wordplus/realtime/calls":
            return {"ok": True, "calls": [{"name": "meeting:7", "people": 2, "started_at": 1}]}
        if path.startswith("/wordplus/realtime/calls/"):
            return {"ok": True, "call": {"name": "meeting:7", "people": 1, "started_at": 1, "list": []}, "muted": True, "removed": True, "changed": True}
        if path.endswith("/chat?limit=5"):
            return {"ok": True, "messages": [{"id": "1-0", "text": "hi"}]}
        if path.endswith("/chat"):
            return {"ok": True, "message": {"id": "2-0", "text": "Welcome"}}
        return {"ok": True, "stream": {"name": "show:1", "state": "live"}, "until": 99, "lifted": True, "deleted": True}

    sent = []
    realtime = app(sent, answer)

    assert realtime.list_rooms(prefix="shop:", limit=1) == {"count": 1, "rooms": [{"name": "shop:1", "count": 2, "connections": 2}], "next": "1"}
    assert realtime.user(42).get() == {"id": "42", "online": True, "connections": 2}
    realtime.user(42).disconnect()
    assert realtime.user(42).ask("cart", {"why": "checkout"}, timeout=5000) == [{"data": {"ok": 1}, "at": 7}]
    assert realtime.usage() == {"connections": {"now": 3, "limit": 1000}, "credits": None}
    assert realtime.webhooks.deliveries()[0]["resendable"] is True
    assert realtime.webhooks.resend("b1") == {"delivered": True, "status": 204}
    assert realtime.webhooks.test() == {"delivered": True, "status": 204}
    assert realtime.list_calls() == [{"name": "meeting:7", "people": 2, "started_at": 1}]
    assert realtime.call("meeting:7").get()["people"] == 1
    assert realtime.call("meeting:7").mute(42, "microphone") is True
    assert realtime.call("meeting:7").permit(43, publish=True) is True
    assert realtime.call("meeting:7").remove(43) is True
    realtime.call("meeting:7").end()
    assert realtime.stream("show:1").get()["state"] == "live"
    assert realtime.stream("show:1").chat(5) == [{"id": "1-0", "text": "hi"}]
    assert realtime.stream("show:1").say("Welcome", "Shop") == {"id": "2-0", "text": "Welcome"}
    assert realtime.stream("show:1").delete_message("1-0") is True
    realtime.stream("show:1").pin(None)
    realtime.stream("show:1").slow(10)
    assert realtime.stream("show:1").timeout(7, 600) == 99
    assert realtime.stream("show:1").unban(7) is True

    assert [(s["method"], s["path"]) for s in sent] == [
        ("GET", "/wordplus/realtime/rooms?prefix=shop%3A&limit=1"),
        ("GET", "/wordplus/realtime/users/42"),
        ("POST", "/wordplus/realtime/users/42/disconnect"),
        ("POST", "/wordplus/realtime/users/42/ask"),
        ("GET", "/wordplus/realtime/usage"),
        ("GET", "/wordplus/realtime/webhooks"),
        ("POST", "/wordplus/realtime/webhooks/b1/resend"),
        ("POST", "/wordplus/realtime/webhooks/test"),
        ("GET", "/wordplus/realtime/calls"),
        ("GET", "/wordplus/realtime/calls/meeting%3A7"),
        ("POST", "/wordplus/realtime/calls/meeting%3A7/mute"),
        ("POST", "/wordplus/realtime/calls/meeting%3A7/permit"),
        ("POST", "/wordplus/realtime/calls/meeting%3A7/remove"),
        ("POST", "/wordplus/realtime/calls/meeting%3A7/end"),
        ("GET", "/wordplus/realtime/streams/show%3A1"),
        ("GET", "/wordplus/realtime/streams/show%3A1/chat?limit=5"),
        ("POST", "/wordplus/realtime/streams/show%3A1/chat"),
        ("DELETE", "/wordplus/realtime/streams/show%3A1/chat/1-0"),
        ("POST", "/wordplus/realtime/streams/show%3A1/pin"),
        ("POST", "/wordplus/realtime/streams/show%3A1/slow"),
        ("POST", "/wordplus/realtime/streams/show%3A1/timeout"),
        ("POST", "/wordplus/realtime/streams/show%3A1/unban"),
    ]
    # The ask's data sealed with the user's key, which WordPlus Cloud doesn't hold.
    assert sent[3]["body"]["event"] == "cart" and sent[3]["body"]["timeout"] == 5000
    assert sent[3]["body"]["data"].startswith("u:42:1:1.")
    assert sent[10]["body"] == {"user": "42", "track": "microphone"}
    assert sent[11]["body"] == {"user": "43", "publish": True}
    assert sent[16]["body"] == {"text": "Welcome", "name": "Shop"}
    assert sent[18]["body"] == {"id": None}
    assert sent[20]["body"] == {"user": "7", "seconds": 600}


def hook_headers(body, timestamp=None):
    """A webhook's headers, signed as the realtime server signs them."""
    timestamp = timestamp or V["webhook"]["timestamp"]
    key = hmac.new(V["secret"].encode(), b"wordplus-realtime webhook v1", hashlib.sha256).digest()
    message = timestamp + "\nPOST\n" + V["webhook"]["path"] + "\n" + hashlib.sha256(body.encode()).hexdigest()
    return {"x-wordplus-site": V["site"], "x-wordplus-timestamp": timestamp, "x-wordplus-signature": hmac.new(key, message.encode(), hashlib.sha256).hexdigest()}


def test_a_webhooks_signature_is_the_vectors():
    assert hook_headers(V["webhook"]["body"])["x-wordplus-signature"] == V["webhook"]["signature"]


def test_a_webhook_hands_each_event_opened_to_its_handlers_and_answers_204():
    realtime = app(now=lambda: int(V["webhook"]["timestamp"]))
    seen = []
    realtime.on("room.occupied", lambda e: seen.append(["occupied", e["room"]]))
    realtime.on("message", lambda e: seen.append(["message", e["data"], e["from"]]))
    realtime.on("stream.live", lambda e: seen.append(["live", e["stream"], e["started_at"]]))
    realtime.on("*", lambda e: seen.append(["any", e["type"]]))

    body = json.dumps({"events": [
        {"id": "a", "at": 1, "type": "room.occupied", "room": "order:42"},
        {"id": "b", "at": 2, "type": "emit", "room": "chat:1", "event": "message", "data": keys.seal_json({"text": "Hi"}, "ch:chat:1:1"), "from": "34", "event_id": "1-0"},
        {"id": "c", "at": 3, "type": "stream.live", "stream": "show:mugs", "started_at": 3, "ended_at": None},
    ]})
    assert realtime.webhook(body.encode(), hook_headers(body), V["webhook"]["path"]) == (204, None)
    assert seen == [["occupied", "order:42"], ["any", "room.occupied"], ["message", {"text": "Hi"}, "34"], ["any", "emit"], ["live", "show:mugs", 3], ["any", "stream.live"]]


def test_a_webhook_hands_what_people_used_to_its_handlers_for_an_app_that_charges_by_it():
    realtime = app(now=lambda: int(V["webhook"]["timestamp"]))
    charged = []
    realtime.on("call.ended", lambda e: charged.append(["call", e["call"], e["from"], e["seconds"]]))
    realtime.on("group.left", lambda e: charged.append(["group", e["call"], e["user"], e["seconds"]]))
    realtime.on("stream.left", lambda e: charged.append(["stream", e["stream"], e["user"], e["seconds"]]))

    body = json.dumps({"events": [
        {"id": "call.ended:c1", "at": 1, "type": "call.ended", "call": "support:34:42", "call_id": "c1", "from": 42, "to": 34, "media": "video",
         "started_at": 1, "answered_at": 2, "ended_at": 125002, "seconds": 125, "reason": "hangup"},
        {"id": "group:EV_1", "at": 2, "type": "group.left", "call": "team:7", "user": "auth0|5f7c", "media": "audio", "joined_at": 1, "left_at": 61001, "seconds": 61},
        {"id": "s1", "at": 3, "type": "stream.left", "stream": "live:1", "user": 42, "role": "viewer", "watch": "w1", "joined_at": 1, "left_at": 30001, "seconds": 30},
    ]})
    assert realtime.webhook(body.encode(), hook_headers(body), V["webhook"]["path"]) == (204, None)
    assert charged == [["call", "support:34:42", 42, 125], ["group", "team:7", "auth0|5f7c", 61], ["stream", "live:1", 42, 30]]


def test_a_webhook_the_server_didnt_sign_a_stale_one_and_a_failing_handler_are_refused():
    now = [int(V["webhook"]["timestamp"])]
    realtime = app(now=lambda: now[0])
    good = hook_headers(V["webhook"]["body"])
    send = lambda headers, body=V["webhook"]["body"]: realtime.webhook(body, headers, V["webhook"]["path"])  # noqa: E731

    assert send({**good, "x-wordplus-signature": "x"})[0] == 401
    assert send({**good, "x-wordplus-site": "other"})[0] == 401
    assert send(good, V["webhook"]["body"] + " ")[0] == 401
    now[0] += 400
    assert send(good) == (401, {"code": "stale_signature"})
    now[0] -= 400
    assert send(good)[0] == 204

    def failing(event):
        raise RuntimeError("down")

    realtime.on("room.occupied", failing)
    assert send(good)[0] == 500


def test_the_routes_answer_json_posts_only():
    realtime = app()
    realtime.room("order:{id}", lambda user: str(user) == "42")

    status, body = realtime.answer_request("POST", "application/json; charset=utf-8", "auth", b'{"rooms":["order:1"]}', 42)
    assert status == 200 and "token" in body
    assert realtime.answer_request("GET", "application/json", "auth", b"", 42)[0] == 405
    assert realtime.answer_request("POST", "text/plain", "auth", b"{}", 42)[0] == 415
    assert realtime.answer_request("POST", "application/json", "auth", b"{", 42)[0] == 400
    assert realtime.answer_request("POST", "application/json", "auth", b'{"rooms":"x"}', 42)[0] == 400
    assert realtime.answer_request("POST", "application/json", "other", b"{}", 42)[0] == 404
    assert realtime.answer_request("POST", "application/json", "calls", b'{"line":true}', 0) == (200, {"denied": "no_user"})


def test_the_browsers_settings_carry_a_users_keys_and_identity():
    config = app(base="/realtime/", worker="/realtime-worker.js", api="https://rest.wordplus.cloud").config(42, {"X-CSRFToken": "t"})

    assert config["server"] == "https://ws.wordplus.cloud"
    assert config["api"] == "https://rest.wordplus.cloud"
    assert config["site"] == V["site"]
    assert config["path"] == "/websocket"
    assert config["worker"] == "/realtime-worker.js"
    assert config["auth"] == {"endpoint": "/realtime/auth", "headers": {"X-CSRFToken": "t"}}
    assert config["calls"]["endpoint"] == "/realtime/calls"
    assert config["keys"]["endpoint"] == "/realtime/keys"
    assert len(config["keys"]["entries"]) == 4 and "identity" in config["keys"]
    assert re.fullmatch(r"/realtime/files/[0-9a-f]{12}/realtime-rooms\.min\.js", config["rooms"]) and "grants" not in config
    assert app().config(None)["keys"]["entries"] == []


def test_the_browser_files_are_served_as_the_package_carries_them():
    # From the routes, so a Python app needs no Node and copies nothing (an SDK review, 2026-10-15).
    realtime = app()
    at = realtime.file_at("realtime-worker.js")
    assert re.fullmatch(r"/api/realtime/files/[0-9a-f]{12}/realtime-worker\.js", at)
    version = at.split("/")[4]
    config = realtime.config(None)
    assert [config["worker"], config["rooms"]] == [at, at.replace("realtime-worker.js", "realtime-rooms.min.js")]

    # The copies are the files their manifest names, so a copy left behind fails here.
    with open(os.path.join(FILES_DIR, "files.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    assert list(manifest["files"]) == ["realtime.js", "realtime-worker.js", "realtime-rooms.min.js", "realtime-rooms-e2ee.worker.js", "realtime-ui.min.js", "realtime-ui-streams.min.js"]
    for name, sha in manifest["files"].items():
        with open(os.path.join(FILES_DIR, name), "rb") as f:
            text = f.read()
        assert hashlib.sha256(text).hexdigest() == sha, name
        status, headers, body = realtime.file("GET", realtime.file_at(name) + "?x=1")
        assert (status, headers["Content-Type"], headers["Cache-Control"], body) == (200, "text/javascript; charset=utf-8", "public, max-age=31536000, immutable", text)

    # By hand with no version: checked again, and not sent again while the same. Another version: kept by nobody.
    _, plain, _ = realtime.file("GET", "/api/realtime/files/realtime.js")
    assert (plain["Cache-Control"], plain["ETag"]) == ("no-cache", '"' + version + '"')
    assert realtime.file("GET", "/api/realtime/files/realtime.js", '"' + version + '"')[0] == 304
    assert realtime.file("GET", "/api/realtime/files/0123456789ab/realtime.js")[1]["Cache-Control"] == "no-store"
    assert realtime.file("HEAD", at)[2] is None

    assert realtime.file("GET", "/api/realtime/files/" + version + "/files.json")[0] == 404
    assert realtime.file("GET", "/api/realtime/files/a/b/realtime.js")[0] == 404
    assert realtime.file("POST", at) is None
    assert realtime.file("GET", "/api/realtime/auth") is None

    # An app that serves them itself.
    own = app(files=False)
    assert own.file("GET", at) is None and "worker" not in own.config(None)
    assert app(worker="/realtime-worker.js").config(None)["worker"] == "/realtime-worker.js"


def test_a_route_at_an_address_of_its_own_is_named_to_the_page_and_found_by_its_path_alone():
    mine = app(routes={"auth": "/permit/rooms", "calls": "/check-call/", "keys": "https://app.example.com/my/keys"})
    config = mine.config(None)

    assert [config["auth"]["endpoint"], config["calls"]["endpoint"], config["keys"]["endpoint"]] == ["/permit/rooms", "/check-call/", "https://app.example.com/my/keys"]
    assert mine.address("webhook") == "/api/realtime/webhook"
    assert mine.route_of("/permit/rooms") == "auth"
    assert mine.route_of("/check-call?x=1") == "calls"
    assert mine.route_of("/my/keys/") == "keys"
    assert mine.route_of("/api/realtime/webhook") == "webhook"
    # Not at their usual addresses any more, and nothing else ending as a route does.
    assert mine.route_of("/api/realtime/calls") is None
    assert mine.route_of("/blog/auth") is None
    # Without addresses of their own, the last part, as before.
    assert app().route_of("/anywhere/calls") == "calls"


def test_every_callback_takes_as_many_arguments_as_it_names():
    realtime = app()
    realtime.room("a:{id}", lambda: True)
    realtime.room("b:{id}", lambda user, params, room: room == "b:1" and params == {"id": "1"})
    assert realtime.authorize(["a:1", "b:1", "b:2"], 7)["denied"] == {"b:2": "forbidden"}


def test_from_the_environment(monkeypatch):
    monkeypatch.setenv("WORDPLUS_SITE", "s1")
    monkeypatch.setenv("WORDPLUS_SECRET", "x")
    monkeypatch.setenv("WORDPLUS_LOCAL_KEY", V["local_key"])
    assert Realtime.from_environment().site == "s1"


def test_live_streams_sign_easy_streams_own_vectors():
    from wordplus_realtime.realtime import stream_grant

    g = json.loads((pathlib.Path(__file__).parent.parent / "spec" / "stream-grants.json").read_text(encoding="utf-8"))
    key = hmac.new(g["secret"].encode(), b"easy-stream grant v1", hashlib.sha256).digest()
    for case in g["cases"]:
        assert stream_grant({**case["claims"], "aud": "easy-stream"}, key) == case["token"], case["name"]


def test_the_calls_route_answers_a_streams_grant_as_its_rule_and_settings_say_a_visitor_as_a_viewer_only():
    realtime = app()

    def rule(user, params):
        if user == 1:
            return {"role": "host", "quality": "720p"}
        if user == 9:
            return False
        return "viewer" if user is None else {"role": "viewer", "chat": "read", "info": {"name": "Ben", "avatar": "http://not-https.example/b.png"}}

    realtime.streams("show:{id}", rule, stage=False, reactions=True, chat=lambda p: {"offline": "open" if p["id"] == "42" else "closed", "links": False})

    host = realtime.authorize_call({"stream": "show:42"}, 1)
    c = claims(host["token"], "easy-stream grant v1")
    assert list(c) == ["iss", "aud", "str", "role", "sub", "name", "avatar", "q", "stage", "offline", "links", "reactions", "iat", "exp"]
    assert {k: c[k] for k in list(c)[:12]} == {"iss": V["site"], "aud": "easy-stream", "str": "show:42", "role": "host", "sub": "1", "name": "User 1", "avatar": "https://example.com/1.png", "q": "720p", "stage": False, "offline": "open", "links": False, "reactions": True}
    assert c["exp"] - c["iat"] == 600 and host["exp"] == c["exp"]

    ben = claims(realtime.authorize_call({"stream": "show:7"}, 34)["token"], "easy-stream grant v1")
    assert [ben["role"], ben["sub"], ben["name"], ben["chat"], ben["offline"]] == ["viewer", "34", "Ben", "read", "closed"]
    assert "avatar" not in ben
    visitor = claims(realtime.authorize_call({"stream": "show:7"}, None)["token"], "easy-stream grant v1")
    assert visitor["role"] == "viewer" and "sub" not in visitor

    assert realtime.authorize_call({"stream": "show:7"}, 9) == {"denied": "forbidden"}
    assert realtime.authorize_call({"stream": "talk:7"}, 1) == {"denied": "forbidden"}
    assert realtime.authorize_call({"stream": "show_7"}, 1) == {"denied": "bad_request"}

    realtime.streams("open:{id}", lambda user: "host")
    assert realtime.authorize_call({"stream": "open:1"}, None) == {"denied": "no_user"}


def test_the_keys_may_be_checked_when_first_used_so_a_framework_command_runs_without_them():
    # Django's manage.py, collectstatic in a Docker build: the rules are declared before the keys are set (an SDK review,
    # 2026-10-15). The first token, request or emit says what is missing.
    later = Realtime("", "", "", check_keys=False)
    later.room("order:{id}", lambda user, p: True)
    later.calls("support:{a}:{b}", lambda user, other, p: True)
    assert later.file_at("realtime.js").startswith("/api/realtime/files/")
    with pytest.raises(ValueError, match="site and secret are required"):
        later.config(42)
    with pytest.raises(ValueError, match="site and secret are required"):
        later.to("order:1").emit("updated", {})

    # A local key checked when the keys are first used.
    short = Realtime(V["site"], V["secret"], "short", check_keys=False)
    with pytest.raises(ValueError):
        short.keys.room_label("order:1")


def test_the_local_cloud_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("WORDPLUS_SITE", V["site"])
    monkeypatch.setenv("WORDPLUS_SECRET", V["secret"])
    monkeypatch.setenv("WORDPLUS_LOCAL_KEY", V["local_key"])
    monkeypatch.setenv("WORDPLUS_REALTIME_SERVER", "http://127.0.0.1:17613")
    monkeypatch.setenv("WORDPLUS_REALTIME_API", "http://127.0.0.1:17613/")
    config = Realtime.from_environment().config(None)
    assert (config["server"], config["api"]) == ("http://127.0.0.1:17613", "http://127.0.0.1:17613")
    assert Realtime.from_environment(server="https://ws.example.test").config(None)["server"] == "https://ws.example.test"
