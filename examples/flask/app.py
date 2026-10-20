"""The API demo on Flask: sign in as Ann (support), Ben (a customer) or Cara (the warehouse), then watch the order of Ben
move on, chat, see who is in the shop and who is online, call them, and meet in the daily meeting.

    cp .env.example .env              # your app key and secret from WordPlus Cloud, and a local key of your own
    pip install -r requirements.txt
    flask --app app run --port 8000
"""

import os
import time
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request, session

import demo
import wordplus_realtime.flask
from wordplus_realtime import Realtime

HERE = Path(__file__).parent

# .env, for the development server: a real host sets these in its environment.
if (HERE / ".env").exists():
    for line in (HERE / ".env").read_text().splitlines():
        name, _, value = line.partition("=")
        if name.strip() and not name.startswith("#") and value.strip():
            os.environ.setdefault(name.strip(), value.strip())

# The shop people and data. A real app has its users and orders in a database.
#
# Shop 0 is the one of this example. A demo (WORDPLUS_DEMO=1, demo.py) opens a shop for each visitor, numbered s, whose people are
# s × 100 + 34, + 42 and + 43 and whose order is s × 10000 + 1042: every rule below finds the shop of a user by arithmetic,
# so the people of one shop never reach another.
PEOPLE = [
    {"id": 34, "name": "Ann", "role": "Support", "staff": True, "avatar": "/static/avatars/ann.svg"},
    {"id": 42, "name": "Ben", "role": "Customer", "staff": False, "avatar": "/static/avatars/ben.svg"},
    {"id": 43, "name": "Cara", "role": "Warehouse", "staff": True, "avatar": "/static/avatars/cara.svg"},
]
STATUSES = ["placed", "packed", "shipped", "delivered"]


def open_shop(s):
    """A shop as it opens: its order, placed, and the chat as this server keeps it, its first two messages. What Ann and
    Ben say next comes by webhook (keep_chat)."""
    now = int(time.time() * 1000)
    return {
        "order": {"id": s * 10000 + 1042, "number": 1042, "customer": s * 100 + 42, "item": "Two ceramic mugs", "status": "placed"},
        "chat": [
            {"id": "first-1", "from": s * 100 + 42, "text": "Hi! Has my order left yet?", "at": now - 120_000, "reactions": {}},
            {"id": "first-2", "from": s * 100 + 34, "text": "Hi Ben, it is being packed now. I will let you know.", "at": now - 60_000, "reactions": {}},
        ],
        "opened": time.time(),
    }


def keep_chat(chat, event):
    """The chat as this server keeps it, from the webhook: a message by its room event id, once. A reaction as the
    one key of the user on it, an empty key taking it back. A real app saves them in its database."""
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    sender = int(event.get("from") or 0)
    if event["event"] == "message" and event.get("event_id") and all(m["id"] != event["event_id"] for m in chat):
        chat.append({"id": event["event_id"], "from": sender, "text": str(data.get("text", "")), "at": event.get("at"), "reactions": {}})
    message = next((m for m in chat if m["id"] == data.get("id")), None) if event["event"] == "reaction" else None
    if message is not None:
        message["reactions"] = {key: kept for key, users in message["reactions"].items() if (kept := [u for u in users if u != sender])}
        if isinstance(data.get("key"), str) and data["key"]:
            message["reactions"].setdefault(data["key"], []).append(sender)


def chat_page(chat, before):
    """A page of the chat, oldest first: the newest 50, or the 50 before the message `before`."""
    end = next((i for i, m in enumerate(chat) if m["id"] == before), len(chat)) if before else len(chat)
    start = max(0, end - 50)
    return {"messages": chat[start:end], "more": start > 0}


SHOPS = {} if demo.on() else {0: open_shop(0)}


def shop_of(user):
    return int(user) // 100 if str(user).isdigit() else None


def people_of(s):
    return [{**p, "id": s * 100 + p["id"], "shop": s} for p in PEOPLE]


def person(user):
    s = shop_of(user)
    return next((p for p in people_of(s) if p["id"] == int(user)), None) if s in SHOPS else None


def is_staff(user):
    return bool((person(user) or {}).get("staff"))


def same_shop(*users):
    return all(person(u) is not None and shop_of(u) == shop_of(users[0]) for u in users)


def order_of(pk):
    order = SHOPS.get(int(pk) // 10000, {}).get("order")
    return order if order and order["id"] == int(pk) else None


def rooms_of(s):
    """The rooms of a shop, by name: those of shop 0 as the guides name them, those of a demo shop with its number."""
    return {
        "order": f"order:{s * 10000 + 1042}",
        "chat": f"chat:{s * 100 + 34}:{s * 100 + 42}",
        "shop": f"shop:{s}" if s else "shop",
        "meeting": f"meeting:{s}" if s else "meeting:daily",
        "product": f"product:{s}" if s else "product:mugs",
        "webhooks": f"webhooks:{s}" if s else "webhooks",
        "show": f"show:{s}" if s else "show:mugs",
    }


def shop_of_room(room):
    """The shop a room belongs to, from its name. None for none."""
    kind, _, rest = str(room or "").partition(":")
    first = rest.split(":")[0] if rest else None
    if kind == "order":
        return int(first) // 10000
    if kind == "chat":
        return shop_of(first)
    if kind not in ("shop", "meeting", "product", "webhooks", "show"):
        return None
    return 0 if first in (None, "daily", "mugs") else int(first) if first.isdigit() else None


def profile(user):
    p = person(user)
    return {"name": p["name"], "avatar": p["avatar"]} if p else None


realtime = Realtime.from_environment(
    # What others see of a user: in presence, calls and the directory.
    profile=profile,
    # WordPlus Cloud unless these say otherwise.
    **{name: os.environ[env] for name, env in (("server", "WORDPLUS_REALTIME_SERVER"), ("api", "WORDPLUS_REALTIME_API")) if os.environ.get(env)},
)


# region demo: order
# The room of an order: its customer and the shop staff. The last 20 updates kept, which the page shows as its timeline.
def may_follow(user, p):
    order = order_of(p["id"])
    return order is not None and (user == order["customer"] or (is_staff(user) and same_shop(user, order["customer"])))


realtime.room("order:{id}", may_follow, history=20)
# endregion

# region demo: chat
# The chat of Ann and Ben: those two only. They send messages, typing, reactions and read ticks straight to the room. The
# messages and reactions reach this server by webhook, and it keeps the conversation (keep_chat, GET /chat/messages). The
# room keeps its last events for 5 minutes, for a page that reconnects.
realtime.room("chat:{a}:{b}", lambda user, p: str(user) in (p["a"], p["b"]) and same_shop(p["a"], p["b"]),
              history=50, emit=["message", "typing", "reaction", "read"], webhook=["message", "reaction"])
# endregion


# region demo: presence
# Who is in the shop: its people, with their name and role.
def member(user, s):
    p = person(user)
    return {"info": {"name": p["name"], "role": p["role"]}} if p and p["shop"] == s else False


realtime.room("shop", lambda user: member(user, 0), presence=True)
realtime.room("shop:{s}", lambda user, p: member(user, int(p["s"])), presence=True)
# endregion

# region demo: product
# The product page: anyone, signed in or not, and a live count of who is looking.
realtime.room("product:{id}", public=True, count=True)
# endregion

# region demo: webhooks
# The webhooks this server got, sent on to the shop people as they come (below), the last 20 kept.
realtime.room("webhooks", lambda user: (person(user) or {}).get("shop") == 0, history=20)
realtime.room("webhooks:{s}", lambda user, p: (person(user) or {}).get("shop") == int(p["s"]), history=20)
# endregion


# region demo: members
# Calls between two people, support:34:42: the two it names, one of them staff. Either of them may bring more staff in,
# and the call goes on as a group call: the one adding calls the staff member about it, who takes the call from them.
def may_call(user, with_user, p):
    pair = [int(p["a"]), int(p["b"])]
    if not same_shop(user, with_user, *pair):
        return False
    if user in pair and with_user in pair:
        return is_staff(user) or is_staff(with_user)
    return (user in pair and is_staff(with_user)) or (is_staff(user) and with_user in pair)


# Whom the call screen offers to add: the shop staff not in the call.
realtime.calls("support:{a}:{b}", may_call, people=lambda user, call: [p["id"] for p in people_of(shop_of(user)) if p["staff"] and str(p["id"]) not in call.split(":")[1:]])
# endregion

# region demo: meeting
# The daily meeting: a group call for everyone in the shop.
realtime.group_calls("meeting:{id}", lambda user, p: (person(user) or {}).get("shop") == (0 if p["id"] == "daily" else int(p["id"])))
# endregion


# region demo: show
def show_role(user, p):
    """The shop live show, show:mugs: Ann presents it, and everyone else watches and writes in its chat, signed in or not."""
    s = shop_of_room(f"show:{p['id']}")
    if s is None or s not in SHOPS:
        return False
    me = person(user) or {}
    return "host" if me.get("shop") == s and me.get("name") == "Ann" else "viewer"


realtime.streams("show:{id}", show_role, reactions=True)
# endregion


# region demo: webhooks
# What WordPlus Cloud tells this server by webhook (set https://<your server>/api/realtime/webhook on your app page in
# WordPlus Cloud): a message or reaction from a page, someone coming online, the live show going live … each sent on to
# its shop webhooks room. A live stream event names its stream (show:mugs) where the others name a room.
def heard(event):
    room = event.get("room") or event.get("stream")
    s = shop_of_room(room) if room else shop_of(event.get("user"))
    if s not in SHOPS or str(room).startswith("webhooks"):
        return
    # region demo: chat
    if event["type"] == "emit" and room == rooms_of(s)["chat"]:
        keep_chat(SHOPS[s]["chat"], event)
    # endregion
    kind = event["event"] if event["type"] == "emit" else event["type"]
    realtime.to(rooms_of(s)["webhooks"]).emit("webhook", {"type": kind, "room": room, "user": event.get("user", event.get("from")), "at": event.get("at")})


realtime.on("*", heard)
# endregion

# The shop page as it is, at /static: no Node and no bundler, as the head names @wordplus/realtime the client the
# routes serve.
app = Flask(__name__, static_folder="shop", static_url_path="/static")
app.secret_key = os.environ.get("SESSION_SECRET", "example-shop")
if demo.on():
    app.config.update(SESSION_COOKIE_NAME="__Host-shop", SESSION_COOKIE_SECURE=True, SESSION_COOKIE_PATH="/")


def current_user():
    """Who is signed in: on a demo, the person of the window (its bearer, demo.py), else the user of the session, or None."""
    if demo.on():
        token = request.headers.get("Authorization", "").removeprefix("Bearer ")
        if (user := demo.user_of(token)) is not None and person(user):
            return user
    user = session.get("user")
    return user if person(user) else None


# The browser routes: POST /api/realtime/auth, /calls and /keys, for the user current_user() finds, JSON only, so the
# session cookie needs no CSRF token. The realtime server webhook, which it signs itself. GET /api/realtime/files/…, the
# browser files of the SDK. And wordplus_realtime() for the page head.
wordplus_realtime.flask.init_app(app, realtime, user=current_user)


@app.get("/login")
def sign_in_page():
    # A new visitor of a demo: a shop of their own, and they are its Ann.
    if demo.on():
        # The visitor address as the proxy in front saw it: the last of X-Forwarded-For, the one it added. The ones
        # before it are whatever the visitor sent.
        address = request.headers.get("X-Forwarded-For", request.remote_addr or "local").split(",")[-1].strip()
        for ended in [n for n, shop in SHOPS.items() if time.time() - shop["opened"] > demo.DAY]:
            del SHOPS[ended]
        s, new = demo.shop_for(address, SHOPS)
        if new:
            SHOPS[s] = open_shop(s)
        session["user"] = s * 100 + 34
        return redirect("/", code=303)
    return render_template("login.html", people=people_of(0))


@app.post("/login")
def sign_in():
    user = request.form.get("as", type=int)
    if (person(user) or {}).get("shop") == 0:
        session["user"] = user
    return redirect("/", code=303)


@app.post("/logout")
def sign_out():
    session.clear()
    return redirect("/login", code=303)


@app.get("/")
@app.get("/as/<token>")
def shop(token=None):
    """The page: the user realtime settings (keys and identity included) and the shop data, rendered in. On a demo,
    /as/<token> is the page of the person of the token."""
    me = person(demo.user_of(token)) if token and demo.on() else person(current_user())
    if me is None:
        return redirect("/login", code=303)
    s = me["shop"]
    order = SHOPS[s]["order"]
    data = {
        "me": me,
        "people": people_of(s),
        "order": order,
        "chat": {"between": [s * 100 + 34, s * 100 + 42]},
        "product": {"name": order["item"], "picture": "/static/products/mugs.webp"},
        "routes": {"status": f"/orders/{order['id']}/status", "wire": f"/orders/{order['id']}/wire", "messages": "/chat/messages"},
        "rooms": rooms_of(s),
        "events": {"order": "updated", "chat": "message"},
        "headers": {},
        **({"demo": demo.frame("flask", me, people_of(s), SHOPS[s]["opened"])} if demo.on() else {}),
    }
    return render_template("page.html", shop=data, me=me)


# region demo: order
@app.post("/orders/<int:pk>/status")
def order_status(pk):
    """The staff move the order on: saved, then emitted to its room but the tab that made the change, and a notice to its
    customer alone. JSON only, as the realtime routes take it."""
    body = request.get_json(silent=True) if request.is_json else None
    order = order_of(pk)
    user = current_user()
    if body is None or order is None or not is_staff(user) or not same_shop(user, order["customer"]) or body.get("status") not in STATUSES:
        return jsonify(ok=False), 403

    order["status"] = body["status"]
    realtime.to(f"order:{pk}").except_tab(request.headers.get("X-Realtime-Tab")).emit("updated", {"id": pk, "status": order["status"]})
    realtime.to_user(order["customer"]).emit("notice", {"text": f"Your order #{order['number']} is {order['status']}."})
    return jsonify(ok=True)
# endregion


@app.get("/orders/<int:pk>/wire")
def order_wire(pk):
    """What the cloud carries of the order update: its room and event as they are, its data sealed with the room key,
    which WordPlus Cloud never holds. The page shows it beside the update as it opened it."""
    order = order_of(pk)
    if order is None or not same_shop(current_user(), order["customer"]):
        return jsonify(ok=False), 403
    room = f"order:{pk}"
    return jsonify(room=room, event="updated", data=realtime.keys.seal_json({"id": pk, "status": order["status"]}, realtime.keys.room_label(room)))


# region demo: chat
@app.get("/chat/messages")
def chat_messages():
    """The chat this server keeps, for one of its two: the newest page, or `?before=<id>` the page before that message."""
    me = person(current_user())
    if me is None or me["id"] % 100 not in (34, 42):
        return jsonify(error="not_in_chat"), 403
    return jsonify(chat_page(SHOPS[me["shop"]]["chat"], request.args.get("before")))
# endregion
