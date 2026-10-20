"""The shop data: a profile for each of its people (what others see of them), the order of Ben, and the chat of Ann and Ben."""

import time

from django.conf import settings
from django.db import models


def now_ms():
    return int(time.time() * 1000)


class Profile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    role = models.CharField(max_length=40)
    avatar = models.CharField(max_length=200)

    def shop(self):
        """As the page shows a person."""
        return {"id": self.user.pk, "name": self.user.first_name, "role": self.role, "staff": self.user.is_staff, "avatar": self.avatar, "shop": self.user.pk // 100}


class Order(models.Model):
    STATUSES = ["placed", "packed", "shipped", "delivered"]

    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    item = models.CharField(max_length=200)
    status = models.CharField(max_length=20, default="placed")


class Message(models.Model):
    """A message of the chat of Ann and Ben as the app keeps it: what the webhook brought (realtime.py, keep_chat), by the id of
    its room event, and who reacted to it with what. The chat on the page pages through them (views.chat_messages)."""

    event_id = models.CharField(max_length=64, null=True, unique=True)
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    text = models.TextField()
    at = models.BigIntegerField(default=now_ms)
    reactions = models.JSONField(default=dict)

    @classmethod
    def by_chat_id(cls, chat_id):
        """The message the chat names: by its room event id, or `first-<pk>` for those the shop opened with."""
        if chat_id.startswith("first-"):
            return cls.objects.filter(pk=int(chat_id[6:]) if chat_id[6:].isdigit() else 0).first()
        return cls.objects.filter(event_id=chat_id).first()

    def chat(self):
        """As the chat on the page shows it."""
        return {"id": self.event_id or f"first-{self.pk}", "from": self.sender_id, "text": self.text, "at": self.at, "reactions": self.reactions}
