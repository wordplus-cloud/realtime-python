"""WordPlus Cloud's realtime SDK for Python, outside WordPress: your server's part of rooms, presence, history, online
status, calls and group calls, sealed end to end. The browser part is the npm package @wordplus/realtime.

    from wordplus_realtime import Realtime

    realtime = Realtime.from_environment(profile=lambda user: {"name": name_of(user)})
    realtime.room("order:{id}", lambda user, p: owns_order(user, p["id"]), history=20)
    realtime.to("order:42").emit("updated", {"status": "paid"})

Django: ``wordplus_realtime.django``. FastAPI and Starlette: ``wordplus_realtime.fastapi``.
"""

from .keys import GenerationStore, Keys, day_of, label_of, valid_label
from .patterns import Patterns, valid_pattern, valid_room
from .realtime import API_SERVER, SERVER, VERSION, CallQueries, Emitter, OnlineQueries, Realtime, RealtimeError, RoomQueries, StreamQueries, UserQueries, WebhookQueries

__all__ = [
    "Realtime",
    "RealtimeError",
    "Emitter",
    "RoomQueries",
    "OnlineQueries",
    "UserQueries",
    "WebhookQueries",
    "CallQueries",
    "StreamQueries",
    "Keys",
    "GenerationStore",
    "Patterns",
    "valid_room",
    "valid_pattern",
    "valid_label",
    "label_of",
    "day_of",
    "SERVER",
    "API_SERVER",
    "VERSION",
]

__version__ = VERSION
