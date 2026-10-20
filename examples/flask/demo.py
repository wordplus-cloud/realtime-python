"""The demo frame around the API demo (WORDPLUS_DEMO=1), as the demo sites run it (flask.docs.wordplus.cloud and the
others): a shop for each visitor, for 24 hours, signed in as Ann. Windows that are Ben or Cara (/as/<token>, the token
then sent as a bearer, so each window of one browser is its own person), and what the page draws around the shop: the
stacks, the guide, the source, "Try this". The example itself is the same with or without it.

The same file in the Django, FastAPI and Flask examples: it knows no framework.
"""

import base64
import hashlib
import hmac
import json
import os
import random
import threading
import time

DAY = 24 * 3600
# New shops an address opens in an hour. Past them it gets the newest of them again.
SHOPS_AN_HOUR = 6

# The demos, in the order the top bar lists them, and where the source of each is.
STACKS = [
    ("wordpress", "WordPress", "realtime-wordpress"),
    ("nextjs", "Next.js", "realtime-js"),
    ("laravel", "Laravel", "realtime-php"),
    ("django", "Django", "realtime-python"),
    ("fastapi", "FastAPI", "realtime-python"),
    ("express", "Express", "realtime-js"),
    ("php", "PHP", "realtime-php"),
    ("flask", "Flask", "realtime-python"),
    ("mobile", "Mobile apps", "realtime-js"),
]

_opened = {}
_lock = threading.Lock()


def on():
    return os.environ.get("WORDPLUS_DEMO") == "1"


def sign(user):
    """The token of a user: their id and its signature."""
    mac = hmac.new(os.environ.get("SESSION_SECRET", "example-shop").encode(), str(user).encode(), hashlib.sha256).digest()
    return f"{user}.{base64.urlsafe_b64encode(mac).decode().rstrip('=')}"


def user_of(token):
    """The user id a token names, if its signature is right. None otherwise."""
    head = str(token or "").split(".")[0]
    if not head.isdigit():
        return None
    return int(head) if hmac.compare_digest(sign(int(head)), str(token)) else None


def shop_for(address, taken):
    """The shop for a new visitor at `address`, as `(number, new)`: a new number, not one of `taken`, or once the
    address has opened its few this hour, the newest of them again, so nobody is ever turned away and nobody can open
    thousands."""
    with _lock:
        recent = [(n, at) for n, at in _opened.get(address, []) if time.time() - at < 3600 and n in taken]
        if len(recent) >= SHOPS_AN_HOUR:
            _opened[address] = recent
            return recent[-1][0], False
        number = random.randint(100000, 999999)
        while number in taken:
            number = random.randint(100000, 999999)
        _opened[address] = recent + [(number, time.time())]
    return number, True


def frame(stack, me, people, opened):
    """What the page of a person draws around the shop: `people` those of the shop, `opened` when it opened, in seconds."""
    sites = os.environ.get("WORDPLUS_DEMO_SITES") or "https://{case}.docs.wordplus.cloud"
    name, repository = next((label, repo) for slug, label, repo in STACKS if slug == stack)
    return {
        "stack": stack,
        "name": name,
        "guide": f"https://docs.wordplus.cloud/{stack}/getting-started/",
        "source": f"https://github.com/wordplus-cloud/{repository}/tree/main/examples/{stack}",
        "sites": [{"stack": slug, "name": label, "url": sites.replace("{case}", slug)} for slug, label, _ in STACKS],
        # This window person, which the page sends with every request. And the others, each a window of their own.
        "token": sign(me["id"]),
        "open": [{"id": p["id"], "name": p["name"], "url": f"/as/{sign(p['id'])}"} for p in people if p["id"] != me["id"]],
        "ends": int((opened + DAY) * 1000),
        "limits": limits(),
        "code": code(stack),
    }


def limits():
    """How long a call and a meeting may last, in seconds, which the page keeps to: 10 and 15 minutes, as the demo runs
    on WordPlus Cloud for anyone. WORDPLUS_DEMO_LIMITS ("call,meeting") shortens them, for the demo check."""
    call, meeting = (int(s) for s in (os.environ.get("WORDPLUS_DEMO_LIMITS") or "600,900").split(","))
    return {"call": call, "meeting": meeting}


def code(stack):
    """The code under each card, "See the code": the parts of this example marked `# region demo: <card>`, which the
    build of the demo sites cuts from its source into WORDPLUS_DEMO_CODE, by stack."""
    path = os.environ.get("WORDPLUS_DEMO_CODE")
    if not path:
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f).get(stack)
