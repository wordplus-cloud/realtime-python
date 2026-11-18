"""The Example Shop of the Django, FastAPI and Flask examples starts its call, its daily meeting and its live show from
tokens of the app's own routes, as the guides teach and as realtime-js's examples do: the page (the same shop.js in every
example) names each route by token-url, the app answers them with call_token(), group_call_token() and stream_token(),
and declares no calls(), group_calls() or streams() rule for them."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = {
    "django": ["store/realtime.py", "store/views.py", "config/urls.py"],
    "fastapi": ["app.py"],
    "flask": ["app.py"],
}


def test_the_page_asks_the_apps_token_routes():
    pages = {name: (ROOT / "examples" / name / "shop" / "shop.js").read_bytes() for name in EXAMPLES}
    assert len(set(pages.values())) == 1, "the shop page is the same in every example"
    page = pages["flask"].decode()
    for route in ("callToken", "meetingToken", "showToken"):
        assert 'token-url="${shop.routes.' + route + '}"' in page, route
    assert "{pair}" not in page and "<room-button" not in page


def test_the_apps_make_the_tokens_with_no_rule():
    for name, files in EXAMPLES.items():
        code = "\n".join((ROOT / "examples" / name / f).read_text() for f in files)
        assert not re.search(r"realtime\.(calls|group_calls|streams)\(", code), name
        for made in ("call_token", "group_call_token", "stream_token"):
            assert f"realtime.{made}(" in code, f"{name}: {made}"
        for route in ("callToken", "meetingToken", "showToken"):
            assert f'"{route}":' in code, f"{name}: shop.routes.{route}"
        for path in ("api/call-token", "api/meeting-token", "api/show-token"):
            assert re.search(rf"[\"']/?{path}[\"']", code), f"{name}: {path}"
