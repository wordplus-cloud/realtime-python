"""The shops, by number. Shop 0 is the one the 0002 migration makes: Ann 34, Ben 42, Cara 43 and order 1042. A demo
(WORDPLUS_DEMO=1, demo.py) opens one for each visitor, numbered s, in the same tables: its people s × 100 + 34, + 42 and
+ 43, its order s × 10000 + 1042. Every rule finds the shop of a user by arithmetic, so the people of one shop never reach
another."""

from django.contrib.auth import get_user_model
from django.db import transaction

from .models import Message, Order, Profile, now_ms


def shop_of(user):
    return int(user) // 100 if str(user).isdigit() else None


def people_of(s):
    """The people of a shop, as the page shows them."""
    return [p.shop() for p in Profile.objects.filter(user_id__gte=s * 100, user_id__lt=s * 100 + 100).select_related("user").order_by("user_id")]


def exists(s):
    return s is not None and Profile.objects.filter(user_id=s * 100 + 34).exists()


def same_shop(*users):
    return all(shop_of(u) is not None and shop_of(u) == shop_of(users[0]) for u in users) and exists(shop_of(users[0]))


def open_shop(s):
    """A new shop, numbered `s`: its people, its order, placed, and the first two messages of the chat. What Ann and Ben say
    next comes by webhook (realtime.py, keep_chat)."""
    User = get_user_model()
    with transaction.atomic():
        for local, username, name, role, staff in [(34, "ann", "Ann", "Support", True), (42, "ben", "Ben", "Customer", False), (43, "cara", "Cara", "Warehouse", True)]:
            user = User.objects.create(pk=s * 100 + local, username=f"{username}-{s}", first_name=name, is_staff=staff, password="!")
            Profile.objects.create(user=user, role=role, avatar=f"/static/avatars/{username}.svg")
        Order.objects.create(pk=s * 10000 + 1042, customer_id=s * 100 + 42, item="Two ceramic mugs", status="placed")
        Message.objects.create(sender_id=s * 100 + 42, text="Hi! Has my order left yet?", at=now_ms() - 120_000)
        Message.objects.create(sender_id=s * 100 + 34, text="Hi Ben, it is being packed now. I will let you know.", at=now_ms() - 60_000)


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
