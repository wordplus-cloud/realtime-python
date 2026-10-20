"""WordPlus Cloud's realtime SDK in Django, as an app: the browser's routes for the request's user, the realtime
server's webhook and the browser files, ``{% wordplus_realtime %}`` for a page's head, and a user's profile from
Django's user model.

    # settings.py
    INSTALLED_APPS = [..., "wordplus_realtime.django"]
    WORDPLUS_REALTIME = {"base": "/api/realtime"}     # optional: Realtime's options, the keys from the environment

    # store/realtime.py, imported by your app's ready() or its urls
    from wordplus_realtime.django import realtime
    realtime.room("order:{id}", lambda user, p: Order.objects.filter(pk=p["id"], user_id=user).exists(), history=20)

    # urls.py: POST /api/realtime/auth, /calls, /keys and /webhook, and GET /api/realtime/files/…
    path("api/realtime/", include("wordplus_realtime.django.routes"))

    {% load wordplus_realtime %}
    <head>{% wordplus_realtime %}</head>              {# the settings, and the import map of the client #}

The routes take the session's user and Django's CSRF check: the page's settings carry the token as X-CSRFToken. The
webhook, which the realtime server signs itself, takes neither. An app with a Realtime of its own includes
``urls(its_realtime, user=…)`` instead, and the template tag takes that one.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from django.contrib.auth import get_user_model
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.middleware.csrf import get_token
from django.urls import URLPattern, path
from django.views.decorators.csrf import csrf_exempt

from ..keys import UserId
from ..realtime import ROUTES, Realtime, _path_of

# The Realtime and the user the routes were made with, which {% wordplus_realtime %} takes: urls() sets them, and the
# one made from settings is it until then.
_current: Optional[Dict[str, Any]] = None
_from_settings: Optional[Realtime] = None


def get_realtime() -> Realtime:
    """The app's Realtime: the one ``urls()`` was given, else the one made from ``settings.WORDPLUS_REALTIME`` (Realtime's
    options by name, ``site``, ``secret`` and ``local_key`` from WORDPLUS_SITE, WORDPLUS_SECRET and WORDPLUS_LOCAL_KEY
    when it leaves them out, ``profile``, ``has_keys`` and ``hidden`` functions or their dotted paths), with the profile
    from Django's user model unless it names one."""
    global _from_settings
    if _current is not None:
        return _current["realtime"]
    if _from_settings is None:
        from django.conf import settings
        from django.utils.module_loading import import_string

        options = dict(getattr(settings, "WORDPLUS_REALTIME", {}) or {})
        options.pop("user", None)   # the routes', settings_user()
        for name in ("profile", "has_keys", "hidden"):
            if isinstance(options.get(name), str):
                options[name] = import_string(options[name])
        options.setdefault("profile", user_profile)
        # Its keys checked when first used, so manage.py runs before they are set (migrate, collectstatic in a build).
        options.setdefault("check_keys", False)
        site, secret, local_key = options.pop("site", None), options.pop("secret", None), options.pop("local_key", None)
        _from_settings = Realtime(site, secret, local_key or "", **options) if site and secret else Realtime.from_environment(**options)
    return _from_settings


def __getattr__(name: str) -> Any:
    # `from wordplus_realtime.django import realtime`: made from settings when first asked, after Django read them.
    if name == "realtime":
        return get_realtime()
    raise AttributeError(name)


def session_user(request: HttpRequest) -> Optional[UserId]:
    """The signed-in user's id, or None."""
    user = getattr(request, "user", None)
    return user.pk if user is not None and user.is_authenticated else None


def user_profile(user_id: UserId) -> Optional[Dict[str, Any]]:
    """A user's profile from Django's user model: their full name, or their username."""
    found = get_user_model().objects.filter(pk=user_id).first()
    if found is None:
        return None
    name = (found.get_full_name() if hasattr(found, "get_full_name") else "") or found.get_username()
    return {"name": name} if name else None


def _json(status: int, body: Any) -> HttpResponse:
    if status == 204:
        response = HttpResponse(status=204)
    else:
        response = JsonResponse(body, status=status, safe=False, json_dumps_params={"separators": (",", ":"), "ensure_ascii": False})
    response["Cache-Control"] = "no-store"
    return response


def view(realtime: Realtime, user: Callable[[HttpRequest], Optional[UserId]] = session_user) -> Callable[..., HttpResponse]:
    """The routes as one view, the action from the URL: ``path("<str:action>", view(realtime))``."""

    def realtime_view(request: HttpRequest, action: str) -> HttpResponse:
        return _json(*realtime.answer_request(request.method or "GET", request.headers.get("Content-Type", ""), action, request.body, user(request)))

    return realtime_view


def webhook_view(realtime: Realtime) -> Callable[..., HttpResponse]:
    """The realtime server's webhook: checked as it was sent, its events handed to the handlers ``realtime.on()`` set."""

    @csrf_exempt
    def realtime_webhook(request: HttpRequest) -> HttpResponse:
        if request.method != "POST":
            return _json(405, {"code": "method_not_allowed"})
        return _json(*realtime.webhook(request.body, request.headers, request.get_full_path()))

    return realtime_webhook


def file_view(realtime: Realtime) -> Callable[..., HttpResponse]:
    """GET files/<version>/<name>: a browser file the package carries (``realtime.file_named()``), no session asked."""

    def realtime_file(request: HttpRequest, name: str, version: Optional[str] = None) -> HttpResponse:
        status, headers, body = realtime.file_named(request.method or "GET", version, name, request.headers.get("If-None-Match"))
        response = HttpResponse(body or b"", status=status)
        for header, value in headers.items():
            response[header] = value
        return response

    return realtime_file


def _files(realtime: Realtime, at: str) -> List[URLPattern]:
    if not realtime.serves_files:
        return []
    serve = file_view(realtime)
    return [
        path(at + "files/<str:name>", serve, name="wordplus-realtime-file"),
        path(at + "files/<str:version>/<str:name>", serve, name="wordplus-realtime-files"),
    ]


def urls(realtime: Realtime, user: Callable[[HttpRequest], Optional[UserId]] = session_user) -> List[URLPattern]:
    """The routes' URLs, to include under the routes' base (``/api/realtime/`` by default): POST auth, calls, keys and
    webhook, and GET files/<version>/<name>, the browser files. With routes at addresses of their own (the ``routes``
    option), each at its whole address: include them at the root, ``path("", include(…))``. The first Realtime given here
    is the one ``{% wordplus_realtime %}`` takes, with its user."""
    global _current
    if _current is None:
        _current = {"realtime": realtime, "user": user}
    if realtime.own_routes:
        answer = view(realtime, user)
        return _files(realtime, realtime.base.lstrip("/") + "/") + [
            path(_path_of(realtime.address(name)).lstrip("/"), webhook_view(realtime), name="wordplus-realtime-webhook")
            if name == "webhook"
            else path(_path_of(realtime.address(name)).lstrip("/"), answer, {"action": name}, name="wordplus-realtime-" + name)
            for name in ROUTES
        ]
    return _files(realtime, "") + [
        path("webhook", webhook_view(realtime), name="wordplus-realtime-webhook"),
        path("<str:action>", view(realtime, user), name="wordplus-realtime"),
    ]


def config_for(realtime: Realtime, request: HttpRequest, user: Callable[[HttpRequest], Optional[UserId]] = session_user) -> Dict[str, Any]:
    """The browser's settings for the request's user, with Django's CSRF token for the routes."""
    return realtime.config(user(request), headers={"X-CSRFToken": get_token(request)})


def settings_user() -> Callable[[HttpRequest], Optional[UserId]]:
    """Who a request's user is: ``WORDPLUS_REALTIME["user"]``, a function or its dotted path, else the session's user."""
    from django.conf import settings
    from django.utils.module_loading import import_string

    named = (getattr(settings, "WORDPLUS_REALTIME", {}) or {}).get("user")
    return import_string(named) if isinstance(named, str) else named or session_user


def head_for(request: HttpRequest, importmap: bool = True, user: Optional[Callable[[HttpRequest], Optional[UserId]]] = None) -> str:
    """What ``{% wordplus_realtime %}`` writes: the settings for the request's user, as the routes find them unless
    ``user`` says, with Django's CSRF token, and the import map of the client, from the Realtime the routes were made with."""
    realtime = get_realtime()
    if user is None:
        user = _current["user"] if _current is not None else settings_user()
    return realtime.head(user(request), headers={"X-CSRFToken": get_token(request)}, importmap=importmap)
