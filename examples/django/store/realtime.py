"""The shop realtime server part: its credentials from the environment, what others see of a user, and its rooms and
who may join them. Every rule checks the shop of the user (shops.py), so the people of one shop never reach another. Its
calls, the meeting and the show start from tokens of the app's own routes (views.py)."""

import os

from django.contrib.auth import get_user_model
from wordplus_realtime import Realtime

from .models import Message, Order, Profile, now_ms
from .shops import exists, rooms_of, same_shop, shop_of, shop_of_room


def profile(user_id):
    """What others see of a user: in presence, calls and the directory."""
    found = Profile.objects.filter(user_id=user_id).select_related("user").first()
    return {"name": found.user.first_name, "avatar": found.avatar} if found else None


def is_staff(user_id):
    return get_user_model().objects.filter(pk=user_id, is_staff=True).exists()


realtime = Realtime.from_environment(
    profile=profile,
    # WordPlus Cloud unless these say otherwise.
    **{name: os.environ[env] for name, env in (("server", "WORDPLUS_REALTIME_SERVER"), ("api", "WORDPLUS_REALTIME_API")) if os.environ.get(env)},
)


# region demo: order
# The room of an order: its customer and the shop staff. The last 20 updates kept, which the page shows as its timeline.
def may_follow_order(user, params):
    order = Order.objects.filter(pk=params["id"]).first()
    return user is not None and order is not None and (order.customer_id == user or (is_staff(user) and same_shop(user, order.customer_id)))


realtime.room("order:{id}", may_follow_order, history=20)
# endregion

# region demo: chat
# The chat of Ann and Ben: those two only. They send messages, typing, reactions and read ticks straight to the room. The
# messages and reactions reach this server by webhook, and it keeps the conversation (keep_chat, views.chat_messages).
# The room keeps its last events for 5 minutes, for a page that reconnects.
realtime.room("chat:{a}:{b}", lambda user, p: str(user) in (p["a"], p["b"]) and same_shop(p["a"], p["b"]),
              history=50, emit=["message", "typing", "reaction", "read"], webhook=["message", "reaction"])
# endregion


# region demo: presence
# Who is in the shop: its people, with their name and role.
def in_the_shop(user, s):
    found = Profile.objects.filter(user_id=user).select_related("user").first() if user is not None else None
    return {"info": {"name": found.user.first_name, "role": found.role}} if found and shop_of(user) == s else False


realtime.room("shop", lambda user: in_the_shop(user, 0), presence=True)
realtime.room("shop:{s}", lambda user, p: in_the_shop(user, int(p["s"])), presence=True)
# endregion

# region demo: product
# The product page: anyone, signed in or not, and a live count of who is looking.
realtime.room("product:{id}", public=True, count=True)
# endregion

# region demo: webhooks
# The webhooks this server got, sent on to the shop people as they come (below), the last 20 kept.
realtime.room("webhooks", lambda user: user is not None and shop_of(user) == 0 and exists(0), history=20)
realtime.room("webhooks:{s}", lambda user, p: user is not None and shop_of(user) == int(p["s"]) and exists(int(p["s"])), history=20)
# endregion


# Calls, the daily meeting and the live show start from tokens of the app's own routes (views.py): GET /api/call-token,
# /api/meeting-token and /api/show-token, each its own check, then realtime.call_token(), group_call_token() or
# stream_token().


# region demo: webhooks
# What WordPlus Cloud tells this server by webhook (set https://<your server>/api/realtime/webhook on your app page in
# WordPlus Cloud): a message or reaction from a page, someone coming online, the live show going live … each sent on to
# its shop webhooks room. A live stream event names its stream (show:mugs) where the others name a room.
def heard(event):
    room = event.get("room") or event.get("stream")
    s = shop_of_room(room) if room else shop_of(event.get("user"))
    if not exists(s) or str(room).startswith("webhooks"):
        return
    # region demo: chat
    if event["type"] == "emit" and room == rooms_of(s)["chat"]:
        keep_chat(event)
    # endregion
    kind = event["event"] if event["type"] == "emit" else event["type"]
    realtime.to(rooms_of(s)["webhooks"]).emit("webhook", {"type": kind, "room": room, "user": event.get("user", event.get("from")), "at": event.get("at")})
# endregion


# region demo: chat
def keep_chat(event):
    """The chat as the app keeps it, from the webhook: a message once, by the id of its room event. A reaction as the
    one key on its message, an empty key taking it back."""
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    sender = int(event.get("from") or 0)
    if event["event"] == "message" and event.get("event_id"):
        Message.objects.get_or_create(event_id=event["event_id"], defaults={"sender_id": sender, "text": str(data.get("text", "")), "at": event.get("at") or now_ms()})
    message = Message.by_chat_id(str(data.get("id", ""))) if event["event"] == "reaction" else None
    if message is not None:
        reactions = {key: kept for key, users in message.reactions.items() if (kept := [u for u in users if u != sender])}
        if isinstance(data.get("key"), str) and data["key"]:
            reactions.setdefault(data["key"], []).append(sender)
        message.reactions = reactions
        message.save(update_fields=["reactions"])
# endregion


# region demo: webhooks
realtime.on("*", heard)
# endregion
