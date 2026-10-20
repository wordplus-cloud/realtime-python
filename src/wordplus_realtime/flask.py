"""WordPlus Cloud's realtime SDK in Flask, as an extension: the browser's routes, the realtime server's webhook and the
browser files as a blueprint, the user from Flask-Login or the session, and ``wordplus_realtime()`` for a page's head.

    realtime = Realtime.from_environment(profile=lambda user: {"name": name_of(user)})
    realtime.room("order:{id}", lambda user, p: order_owner(p["id"]) == user, history=20)
    wordplus_realtime.flask.init_app(app, realtime)

    <head>{{ wordplus_realtime() }}</head>        {# the settings, and the import map of the client #}
    <script type="module">import { connect } from '@wordplus/realtime'; …</script>

The routes take JSON alone, so a page on another site cannot send them, and they need no CSRF token: Flask-WTF's
CSRFProtect, when the app has it, leaves them out.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from flask import Blueprint, Flask, Response, current_app, jsonify, request, session
from markupsafe import Markup

from .keys import UserId
from .realtime import ROUTES, Realtime, _path_of


def session_user() -> Optional[UserId]:
    """The signed-in user: Flask-Login's ``current_user`` when the app has it, else ``session["user_id"]``, or None. An
    id of digits is a number, as Flask-Login gives every id as text."""
    user: Any = None
    if hasattr(current_app, "login_manager"):
        from flask_login import current_user  # type: ignore[import-not-found]

        if current_user and getattr(current_user, "is_authenticated", False):
            user = current_user.get_id()
    if user is None:
        user = session.get("user_id")
    if isinstance(user, str) and user.isdigit():
        return int(user)
    return user if isinstance(user, (int, str)) and user != "" else None


def init_app(app: Flask, realtime: Realtime, user: Callable[[], Optional[UserId]] = session_user) -> Blueprint:
    """Adds the routes under the routes' base (``/api/realtime`` by default): POST auth, calls, keys and webhook, each at
    its own address with the ``routes`` option, and GET files/<version>/<name>, the browser files. Adds
    ``wordplus_realtime()`` to the templates, for a page's head. ``user()`` gives the request's user's id, or None."""
    routes = Blueprint("wordplus_realtime", __name__)

    def answer(action: str) -> Response:
        if action == "webhook":
            path = request.path + ("?" + request.query_string.decode() if request.query_string else "")
            status, body = realtime.webhook(request.get_data(), request.headers, path)
        else:
            status, body = realtime.answer_request(request.method, request.content_type or "", action, request.get_data(), user())
        response = Response(status=204) if status == 204 else jsonify(body)
        response.status_code = status
        response.headers["Cache-Control"] = "no-store"
        return response

    if realtime.own_routes:
        for name in ROUTES:
            routes.add_url_rule(_path_of(realtime.address(name)), "route_" + name, lambda name=name: answer(name), methods=["POST"])
    else:
        routes.add_url_rule(realtime.base + "/<action>", "route", answer, methods=["POST"])

    if realtime.serves_files:

        def file(name: str, version: Optional[str] = None) -> Response:
            status, headers, body = realtime.file_named(request.method, version, name, request.headers.get("If-None-Match"))
            return Response(body or b"", status=status, headers=headers)

        routes.add_url_rule(realtime.base + "/files/<name>", "file", file, methods=["GET"])
        routes.add_url_rule(realtime.base + "/files/<version>/<name>", "files", file, methods=["GET"])

    csrf = app.extensions.get("csrf")
    if csrf is not None and hasattr(csrf, "exempt"):
        csrf.exempt(routes)

    app.register_blueprint(routes)
    app.extensions["wordplus_realtime"] = realtime
    app.add_template_global(lambda importmap=True: Markup(realtime.head(user(), importmap=importmap)), "wordplus_realtime")
    return routes
