"""The shop views: signing in, the page, moving the order on, and the tokens that start a call, the meeting and the
show. The order is saved, then emitted once the transaction commits, but to the tab that made it, which shows it already."""

import json
from datetime import timedelta

from django.contrib.auth import get_user_model, login, logout
from django.db import transaction
from django.http import HttpResponseForbidden, JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

import demo
import wordplus_realtime.django as wr

from .models import Message, Order, Profile
from .realtime import realtime
from .shops import exists, open_shop, people_of, rooms_of, same_shop, shop_of, shop_of_room


def current_user(request):
    """Who is asking: on a demo, the person of a window (its bearer, demo.py), else the user of the session, or None."""
    if demo.on():
        user = demo.user_of(request.headers.get("Authorization", "").removeprefix("Bearer "))
        if user is not None and exists(shop_of(user)):
            return user
    return wr.session_user(request)


def start_visitor(request):
    """A new visitor of a demo: a shop of their own, and they are its Ann, signed in. Her id."""
    User = get_user_model()
    # Shops end after a day.
    User.objects.filter(pk__gte=10000000, date_joined__lt=timezone.now() - timedelta(seconds=demo.DAY)).delete()
    taken = {pk // 100 for pk in User.objects.filter(pk__gte=10000000).values_list("pk", flat=True)}
    # The visitor address as the proxy in front saw it: the last of X-Forwarded-For, the one it added. The ones before
    # it are whatever the visitor sent.
    address = request.headers.get("X-Forwarded-For", request.META.get("REMOTE_ADDR", "local")).split(",")[-1].strip()
    s, new = demo.shop_for(address, taken)
    if new:
        open_shop(s)
    login(request, User.objects.get(pk=s * 100 + 34))
    return s * 100 + 34


def sign_in(request):
    """How the example stands in for signing in: pick one of the shop people. Your app has its own sign-in. On a demo,
    each visitor gets a shop of their own, and they are its Ann."""
    User = get_user_model()
    if demo.on():
        start_visitor(request)
        return redirect("/")
    if request.method == "POST":
        user = get_object_or_404(User, pk=request.POST.get("as"))
        if shop_of(user.pk) != 0:
            return HttpResponseForbidden()
        login(request, user)
        return redirect("/")
    return render(request, "store/login.html", {"people": Profile.objects.filter(user_id__lt=100).select_related("user").order_by("user_id")})


@require_POST
def sign_out(request):
    logout(request)
    return redirect("/login/")


def shop(request, token=None):
    """The page: the user realtime settings (keys, identity, and the CSRF token for the routes) and the shop data.
    On a demo, /as/<token> is the page of the person of the token."""
    user = demo.user_of(token) if token and demo.on() else current_user(request)
    # A new visitor of a demo opening the start page gets their shop there and then, with no redirect to /login/ and
    # back, which a search engine, keeping no cookie, would follow without end.
    if user is None and token is None and demo.on() and request.method == "GET":
        user = start_visitor(request)
    if user is None or not exists(shop_of(user)):
        return redirect("/login/")
    s = shop_of(user)
    me = Profile.objects.select_related("user").get(user_id=user).shop()
    order = Order.objects.get(pk=s * 10000 + 1042)
    data = {
        "me": me,
        "people": people_of(s),
        "order": {"id": order.pk, "number": 1042, "customer": order.customer_id, "item": order.item, "status": order.status},
        "chat": {"between": [s * 100 + 34, s * 100 + 42]},
        "product": {"name": order.item, "picture": "/static/products/mugs.webp"},
        "routes": {
            "status": f"/orders/{order.pk}/status",
            "wire": f"/orders/{order.pk}/wire",
            "messages": "/chat/messages",
            # The routes that start a call, the meeting and the show, each with the id of the shop's own.
            "callToken": "/api/call-token",
            "meetingToken": "/api/meeting-token?id=" + rooms_of(s)["meeting"].split(":", 1)[1],
            "showToken": "/api/show-token?id=" + rooms_of(s)["show"].split(":", 1)[1],
        },
        "rooms": rooms_of(s),
        "events": {"order": "updated", "chat": "message"},
        "headers": {"X-CSRFToken": get_token(request)},
    }
    if demo.on():
        opened = get_user_model().objects.get(pk=s * 100 + 34).date_joined.timestamp()
        data["demo"] = demo.frame("django", me, data["people"], opened)
    page = render(request, "store/page.html", {"user_id": user, "shop": data, "me": me})
    # No search engine keeps a window (noindex): each new shop has new tokens, so it would find new addresses without end.
    if token:
        page["X-Robots-Tag"] = "noindex, nofollow"
    return page


# region demo: order
@require_POST
def order_status(request, pk):
    """The staff move the order on: its room follows, and its customer alone gets a notice."""
    user = current_user(request)
    body = json.loads(request.body or b"{}")
    order = Order.objects.filter(pk=pk).first()
    if order is None or user is None or not get_user_model().objects.filter(pk=user, is_staff=True).exists() or not same_shop(user, order.customer_id) or body.get("status") not in Order.STATUSES:
        return HttpResponseForbidden()

    tab = request.headers.get("X-Realtime-Tab")
    with transaction.atomic():
        order = get_object_or_404(Order.objects.select_for_update(), pk=pk)
        order.status = body["status"]
        order.save()

        def emit():
            realtime.to(f"order:{order.pk}").except_tab(tab).emit("updated", {"id": order.pk, "status": order.status})
            realtime.to_user(order.customer_id).emit("notice", {"text": f"Your order #1042 is {order.status}."})

        transaction.on_commit(emit)

    return JsonResponse({"ok": True})
# endregion


def order_wire(request, pk):
    """What the cloud carries of the order update: its room and event as they are, its data sealed with the room key,
    which WordPlus Cloud never holds. The page shows it beside the update as it opened it."""
    order = Order.objects.filter(pk=pk).first()
    user = current_user(request)
    if order is None or user is None or not same_shop(user, order.customer_id):
        return HttpResponseForbidden()
    room = f"order:{order.pk}"
    return JsonResponse({"room": room, "event": "updated", "data": realtime.keys.seal_json({"id": order.pk, "status": order.status}, realtime.keys.room_label(room))})


# region demo: chat
def chat_messages(request):
    """The chat the app keeps (realtime.py, keep_chat), for one of its two: the newest 50 messages, or with `?before=<id>`
    the 50 before that one, oldest first. The chat on the page pages through them. The room fills in only what came since."""
    user = current_user(request)
    if user is None or user % 100 not in (34, 42):
        return HttpResponseForbidden()
    s = shop_of(user)
    messages = Message.objects.filter(sender_id__gte=s * 100, sender_id__lt=s * 100 + 100)
    before = Message.by_chat_id(request.GET.get("before", "")) if request.GET.get("before") else None
    if before is not None:
        messages = messages.filter(pk__lt=before.pk)
    page = list(messages.order_by("-pk")[:51])
    return JsonResponse({"messages": [m.chat() for m in reversed(page[:50])], "more": len(page) > 50})
# endregion


# region demo: members
@require_GET
def call_token(request):
    """GET /api/call-token?to=34&type=video: a call between two people of a shop, asked by <call-button> and
    <online-list> as a call button is pressed. The app's own check, then the token that lets this user call that one."""
    me = current_user(request)
    to = int(request.GET["to"]) if request.GET.get("to", "").isdigit() else None

    # Two people of the same shop, one of them staff: customers never call each other.
    if me is None or to is None or to == me or not same_shop(me, to) or not Profile.objects.filter(user_id=to).exists():
        return HttpResponseForbidden()
    if not get_user_model().objects.filter(pk__in=[me, to], is_staff=True).exists():
        return HttpResponseForbidden()
    return JsonResponse({"token": realtime.call_token(me, to, type=request.GET.get("type"))})
# endregion


# region demo: meeting
@require_GET
def meeting_token(request):
    """GET /api/meeting-token?id=daily: the daily meeting of a shop, a group call, asked by <group-call-button> as it is
    pressed. The name comes from the id: meeting:daily for the shop of the guides, meeting:7 for a demo shop."""
    me = current_user(request)
    id = request.GET.get("id", "")

    # Everyone in the shop, and nobody else.
    if me is None or not exists(shop_of(me)) or shop_of(me) != (0 if id == "daily" else int(id) if id.isdigit() else None):
        return HttpResponseForbidden()
    return JsonResponse({"token": realtime.group_call_token(me, f"meeting:{id}")})
# endregion


# region demo: show
@require_GET
def show_token(request):
    """GET /api/show-token?id=mugs: the live show of a shop, asked by <live-stream>, again as each ten-minute token runs
    out. The name comes from the id: show:mugs for the shop of the guides, show:7 for a demo shop."""
    me = current_user(request)
    id = request.GET.get("id", "")
    name = f"show:{id}"

    # 1. A show of a shop here: any other is refused.
    s = shop_of_room(name) if id else None
    if s is None or not exists(s):
        return HttpResponseForbidden()

    # 2. Ann of the shop presents it, and everyone else watches and writes in its chat, signed in or not.
    host = me is not None and shop_of(me) == s and get_user_model().objects.filter(pk=me, first_name="Ann").exists()
    return JsonResponse({"token": realtime.stream_token(me, name, **({"role": "host"} if host else {}), settings={"reactions": True})})
# endregion
