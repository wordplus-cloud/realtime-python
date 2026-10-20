"""The routes in Django and FastAPI, for the request's user, with the page's settings, and the realtime server's
webhook."""

import hashlib
import hmac
import json
import pathlib
import time

import django
import pytest
from django.conf import settings

V = json.loads((pathlib.Path(__file__).parent.parent / "spec" / "vectors.json").read_text())

if not settings.configured:
    settings.configure(
        DEBUG=True,
        SECRET_KEY="test",
        ROOT_URLCONF=__name__,
        ALLOWED_HOSTS=["*"],
        INSTALLED_APPS=["django.contrib.auth", "django.contrib.contenttypes", "django.contrib.sessions", "wordplus_realtime.django"],
        TEMPLATES=[{"BACKEND": "django.template.backends.django.DjangoTemplates", "OPTIONS": {"context_processors": ["django.template.context_processors.request"]}}],
        WORDPLUS_REALTIME={"site": V["site"], "secret": V["secret"], "local_key": V["local_key"], "base": "/rt", "user": "tests.test_frameworks.header_user", "hidden": "operator.not_"},
        MIDDLEWARE=["django.contrib.sessions.middleware.SessionMiddleware", "django.middleware.csrf.CsrfViewMiddleware", "django.contrib.auth.middleware.AuthenticationMiddleware"],
        DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}},
    )
    django.setup()

from django.contrib.auth.models import User  # noqa: E402
from django.core.management import call_command  # noqa: E402
from django.test import Client, RequestFactory  # noqa: E402
from django.urls import include, path  # noqa: E402
from fastapi import FastAPI, Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import wordplus_realtime.django as wr_django  # noqa: E402
import wordplus_realtime.fastapi as wr_fastapi  # noqa: E402
from wordplus_realtime import Keys, Realtime  # noqa: E402

seen = []
realtime = Realtime(V["site"], V["secret"], V["local_key"], profile=wr_django.user_profile, http=lambda *a: (200, b'{"ok":true}'))
realtime.room("order:{id}", lambda user, p: str(user) == p["id"])
realtime.on("member.joined", lambda e: seen.append(("django", e["room"], e["user"])))

# The same routes at addresses of their own, included at the root.
OWN = {"auth": "/permit/rooms", "calls": "/check-call", "keys": "/my/keys", "webhook": "/hooks/wordplus"}
own = Realtime(V["site"], V["secret"], V["local_key"], routes=OWN, http=lambda *a: (200, b'{"ok":true}'))
own.room("order:{id}", lambda user, p: str(user) == p["id"])
own.on("member.joined", lambda e: seen.append(("django own", e["room"], e["user"])))

urlpatterns = [path("api/realtime/", include(wr_django.urls(realtime))), path("", include(wr_django.urls(own)))]

call_command("migrate", verbosity=0, run_syncdb=True)


def signed(body, path):
    """A webhook's headers as the realtime server signs them, now."""
    timestamp = str(int(time.time()))
    key = hmac.new(V["secret"].encode(), b"wordplus-realtime webhook v1", hashlib.sha256).digest()
    signature = hmac.new(key, (timestamp + "\nPOST\n" + path + "\n" + hashlib.sha256(body).hexdigest()).encode(), hashlib.sha256).hexdigest()
    return {"X-WordPlus-Site": V["site"], "X-WordPlus-Timestamp": timestamp, "X-WordPlus-Signature": signature}


HOOK = json.dumps({"events": [{"id": "a", "at": 1, "type": "member.joined", "room": "order:42", "user": "42"}]}).encode()


def test_django_answers_the_sessions_user_behind_its_csrf_check():
    user = User.objects.create_user("ann", password="pw", first_name="Ann", last_name="Lee")
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)

    # The page's settings carry Django's CSRF token, which the routes need.
    request = RequestFactory().get("/")
    request.user = user
    request.session = client.session
    config = wr_django.config_for(realtime, request)
    token = config["auth"]["headers"]["X-CSRFToken"]
    assert Keys(V["local_key"]).open(json.loads(__import__("base64").urlsafe_b64decode(config["keys"]["identity"]["token"].split(".")[1] + "==="))["pd"]["name"]) == "Ann Lee"

    mine = "order:" + str(user.pk)
    refused = client.post("/api/realtime/auth", data=json.dumps({"rooms": [mine]}), content_type="application/json")
    assert refused.status_code == 403

    client.cookies["csrftoken"] = token
    answer = client.post("/api/realtime/auth", data=json.dumps({"rooms": [mine, "order:999"]}), content_type="application/json", headers={"X-CSRFToken": token})
    assert answer.status_code == 200 and answer["Cache-Control"] == "no-store"
    body = answer.json()
    assert "token" in body and body["denied"] == {"order:999": "forbidden"}

    keys = client.post("/api/realtime/keys", data=json.dumps({"labels": []}), content_type="application/json", headers={"X-CSRFToken": token}).json()
    assert len(keys["keys"]) == 4 and "identity" in keys


def test_django_takes_the_webhook_without_a_session_or_csrf_token_and_only_signed():
    client = Client(enforce_csrf_checks=True)
    path = "/api/realtime/webhook"

    answer = client.post(path, data=HOOK, content_type="application/json", headers=signed(HOOK, path))
    assert answer.status_code == 204 and answer["Cache-Control"] == "no-store"
    assert seen[-1] == ("django", "order:42", "42")

    assert client.post(path, data=HOOK, content_type="application/json", headers={**signed(HOOK, path), "X-WordPlus-Signature": "x"}).status_code == 401
    assert client.get(path).status_code == 405


def test_fastapi_answers_the_user_its_function_finds_and_the_webhook():
    app = FastAPI()

    async def current_user(request: Request):
        return request.headers.get("x-user")

    plain = Realtime(V["site"], V["secret"], V["local_key"], profile=lambda user: {"name": "User " + str(user)})
    plain.room("order:{id}", lambda user, p: str(user) == p["id"])
    plain.on("member.joined", lambda e: seen.append(("fastapi", e["room"], e["user"])))
    app.include_router(wr_fastapi.router(plain, current_user), prefix="/api/realtime")
    client = TestClient(app)

    ok = client.post("/api/realtime/auth", json={"rooms": ["order:42"]}, headers={"X-User": "42"})
    assert ok.status_code == 200 and "token" in ok.json() and ok.headers["cache-control"] == "no-store"
    assert client.post("/api/realtime/auth", json={"rooms": ["order:42"]}).json()["denied"] == {"order:42": "forbidden"}
    assert client.post("/api/realtime/auth", content=b"{}", headers={"Content-Type": "text/plain"}).status_code == 415
    assert client.post("/api/realtime/calls", json={"line": True}, headers={"X-User": "42"}).json()["token"]

    hook = client.post("/api/realtime/webhook", content=HOOK, headers={"Content-Type": "application/json", **signed(HOOK, "/api/realtime/webhook")})
    assert hook.status_code == 204
    assert seen[-1] == ("fastapi", "order:42", "42")
    assert client.post("/api/realtime/webhook", content=HOOK, headers=signed(HOOK, "/elsewhere")).status_code == 401


def test_django_answers_each_route_at_an_address_of_its_own():
    user = User.objects.create_user("ben", password="pw")
    client = Client()
    client.force_login(user)
    mine = "order:" + str(user.pk)

    assert client.post("/permit/rooms", data=json.dumps({"rooms": [mine]}), content_type="application/json").json()["token"]
    assert client.post("/check-call", data=json.dumps({"line": True}), content_type="application/json").json()["token"]
    assert len(client.post("/my/keys", data=json.dumps({"labels": []}), content_type="application/json").json()["keys"]) == 4
    hook = client.post("/hooks/wordplus", data=HOOK, content_type="application/json", headers=signed(HOOK, "/hooks/wordplus"))
    assert hook.status_code == 204 and seen[-1] == ("django own", "order:42", "42")


def test_fastapi_answers_each_route_at_an_address_of_its_own_and_takes_no_action_from_the_query():
    app = FastAPI()

    async def current_user(request: Request):
        return request.headers.get("x-user")

    mine = Realtime(V["site"], V["secret"], V["local_key"], routes={"calls": "/check-call", "webhook": "https://app.example.com/hooks/wordplus"})
    mine.room("order:{id}", lambda user, p: str(user) == p["id"])
    mine.on("member.joined", lambda e: seen.append(("fastapi own", e["room"], e["user"])))
    app.include_router(wr_fastapi.router(mine, current_user))
    client = TestClient(app)

    assert client.post("/check-call", json={"line": True}, headers={"X-User": "42"}).json()["token"]
    assert client.post("/check-call?action=keys", json={"line": True}, headers={"X-User": "42"}).json()["token"]
    assert client.post("/api/realtime/auth", json={"rooms": ["order:42"]}, headers={"X-User": "42"}).json()["token"]
    assert client.post("/api/realtime/calls", json={"line": True}).status_code == 404
    hook = client.post("/hooks/wordplus", content=HOOK, headers={"Content-Type": "application/json", **signed(HOOK, "/hooks/wordplus")})
    assert hook.status_code == 204 and seen[-1] == ("fastapi own", "order:42", "42")


def test_the_browser_files_come_from_the_routes_in_django_and_fastapi_without_a_session():
    # So a Python app needs no Node and copies nothing (an SDK review, 2026-10-15).
    from wordplus_realtime.realtime import FILES_DIR

    worker = (pathlib.Path(FILES_DIR) / "realtime-worker.js").read_bytes()
    at = realtime.file_at("realtime-worker.js")

    django_client = Client()
    served = django_client.get(at)
    assert served.status_code == 200 and served.content == worker and not served.cookies
    assert served["Cache-Control"] == "public, max-age=31536000, immutable" and served["Content-Type"] == "text/javascript; charset=utf-8"
    assert django_client.get("/api/realtime/files/realtime.js")["Cache-Control"] == "no-cache"
    assert django_client.get("/api/realtime/files/" + at.split("/")[4] + "/files.json").status_code == 404

    app = FastAPI()
    app.include_router(wr_fastapi.router(realtime, lambda request: None), prefix="/api/realtime")
    fastapi_client = TestClient(app)
    got = fastapi_client.get(at)
    assert got.status_code == 200 and got.content == worker and got.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert fastapi_client.head(at).status_code == 200
    assert fastapi_client.get("/api/realtime/files/realtime.js", headers={"If-None-Match": '"' + at.split("/")[4] + '"'}).status_code == 304

    # Routes at addresses of their own: the files stay under the base.
    mine = FastAPI()
    mine.include_router(wr_fastapi.router(own, lambda request: None))
    assert TestClient(mine).get(own.file_at("realtime.js")).status_code == 200


def test_flask_takes_the_extension_the_routes_the_files_and_the_page_head():
    from flask import Flask, render_template_string, session

    import wordplus_realtime.flask as wr_flask

    app = Flask(__name__)
    app.secret_key = "test"
    plain = Realtime(V["site"], V["secret"], V["local_key"], profile=lambda user: {"name": "User " + str(user)})
    plain.room("order:{id}", lambda user, p: str(user) == p["id"])
    plain.on("member.joined", lambda e: seen.append(("flask", e["room"], e["user"])))
    wr_flask.init_app(app, plain)

    @app.post("/sign-in")
    def sign_in():
        session["user_id"] = 42
        return ""

    @app.get("/page")
    def page():
        return render_template_string("<head>{{ wordplus_realtime() }}</head>")

    client = app.test_client()
    assert client.post("/api/realtime/auth", json={"rooms": ["order:42"]}).json["denied"] == {"order:42": "forbidden"}
    client.post("/sign-in")
    ok = client.post("/api/realtime/auth", json={"rooms": ["order:42"]})
    assert ok.status_code == 200 and "token" in ok.json and ok.headers["Cache-Control"] == "no-store"
    assert client.post("/api/realtime/auth", data=b"{}", content_type="text/plain").status_code == 415

    hook = client.post("/api/realtime/webhook", data=HOOK, content_type="application/json", headers=signed(HOOK, "/api/realtime/webhook"))
    assert hook.status_code == 204 and seen[-1] == ("flask", "order:42", "42")

    worker = client.get(plain.file_at("realtime-worker.js"))
    assert worker.status_code == 200 and worker.headers["Cache-Control"] == "public, max-age=31536000, immutable"

    # The head: the import map of the client the routes serve, and the settings of the signed-in user, safe in a <script>.
    head = client.get("/page").get_data(as_text=True)
    assert '<script type="importmap">{"imports":{"@wordplus/realtime":"' + plain.file_at("realtime.js") + '"}}</script>' in head
    settings = json.loads(head.split("window.wordplusRealtimeConfig = ", 1)[1].split(";</script>", 1)[0])
    assert settings["site"] == V["site"] and len(settings["keys"]["entries"]) == 4 and "</" not in head.split("wordplusRealtimeConfig", 1)[1].split("</script>")[0]


def test_flask_takes_routes_at_addresses_of_their_own():
    from flask import Flask

    import wordplus_realtime.flask as wr_flask

    app = Flask(__name__)
    mine = Realtime(V["site"], V["secret"], V["local_key"], routes={"calls": "/check-call"})
    wr_flask.init_app(app, mine, user=lambda: 42)
    client = app.test_client()
    assert client.post("/check-call", json={"line": True}).json["token"]
    assert client.post("/api/realtime/calls", json={"line": True}).status_code in (404, 405)
    assert client.post("/api/realtime/keys", json={"labels": []}).status_code == 200
    assert client.get(mine.file_at("realtime.js")).status_code == 200


def test_flask_takes_the_user_from_flask_login_when_the_app_has_it():
    from flask import Flask
    from flask_login import LoginManager, UserMixin, login_user

    import wordplus_realtime.flask as wr_flask

    class Person(UserMixin):
        def __init__(self, id):
            self.id = id

    app = Flask(__name__)
    app.secret_key = "test"
    LoginManager(app).user_loader(lambda id: Person(id))
    plain = Realtime(V["site"], V["secret"], V["local_key"])
    plain.room("order:{id}", lambda user, p: user == 42 and p["id"] == "42")
    wr_flask.init_app(app, plain)

    @app.post("/sign-in")
    def sign_in():
        login_user(Person(42))
        return ""

    client = app.test_client()
    client.post("/sign-in")
    assert "token" in client.post("/api/realtime/auth", json={"rooms": ["order:42"]}).json   # its id "42", a number again


def header_user(request):
    """The user WORDPLUS_REALTIME names in the test settings, by dotted path."""
    return request.headers.get("X-User")


def test_django_writes_the_page_head_with_its_template_tag():
    from django.template import engines

    user = User.objects.create_user("tag", password="pw")
    request = RequestFactory().get("/page")
    request.user = user
    request.session = {}
    page = engines["django"].from_string("{% load wordplus_realtime %}<head>{% wordplus_realtime %}</head>").render({}, request)

    # The routes' Realtime, the first urls() was given: its import map, and the settings of the user with the CSRF token.
    assert '<script type="importmap">{"imports":{"@wordplus/realtime":"' + realtime.file_at("realtime.js") + '"}}</script>' in page
    settings = json.loads(page.split("window.wordplusRealtimeConfig = ", 1)[1].split(";</script>", 1)[0])
    assert settings["site"] == V["site"] and "X-CSRFToken" in settings["auth"]["headers"] and settings["keys"]["entries"]
    plain = engines["django"].from_string("{% load wordplus_realtime %}{% wordplus_realtime importmap=False %}").render({}, request)
    assert "importmap" not in plain and "wordplusRealtimeConfig" in plain

    # A view that knows its user another way: the visitor of the request, the user it names.
    request.user = type("Anonymous", (), {"is_authenticated": False, "pk": None})()
    nobody = engines["django"].from_string("{% load wordplus_realtime %}{% wordplus_realtime %}").render({}, request)
    named = engines["django"].from_string("{% load wordplus_realtime %}{% wordplus_realtime user=me %}").render({"me": user.pk}, request)
    assert json.loads(nobody.split("wordplusRealtimeConfig = ", 1)[1].split(";</script>")[0])["keys"]["entries"] == []
    assert json.loads(named.split("wordplusRealtimeConfig = ", 1)[1].split(";</script>")[0])["keys"]["entries"]


def test_django_makes_a_realtime_from_settings():
    from django.urls import resolve

    import wordplus_realtime.django as wr

    kept, wr._current, wr._from_settings = wr._current, None, None
    try:
        made = wr.get_realtime()
        assert made is wr.realtime and made.site == V["site"] and made.base == "/rt"
        assert made._hidden is __import__("operator").not_   # a function of the settings, by its dotted path
        assert made.config(None)["auth"]["endpoint"] == "/rt/auth"
        assert wr.settings_user().__name__ == "header_user"   # by its dotted path

        # include("wordplus_realtime.django.routes"): its routes, for the user the settings name.
        import importlib

        import wordplus_realtime.django.routes as routes

        importlib.reload(routes)
        names = {p.name for p in routes.urlpatterns}
        assert {"wordplus-realtime", "wordplus-realtime-webhook", "wordplus-realtime-file", "wordplus-realtime-files"} <= names
    finally:
        wr._current = kept



def test_django_runs_its_commands_before_the_keys_are_set(monkeypatch):
    # manage.py migrate, check and collectstatic in a Docker build: the app ready() declares rooms, and nothing needs the
    # keys until a page asks (an SDK review, 2026-10-15).
    from django.core.management import call_command
    from django.test import override_settings

    import wordplus_realtime.django as wr

    for name in ("WORDPLUS_SITE", "WORDPLUS_SECRET", "WORDPLUS_LOCAL_KEY"):
        monkeypatch.delenv(name, raising=False)
    kept, wr._current, wr._from_settings = wr._current, None, None
    try:
        with override_settings(WORDPLUS_REALTIME={}):
            made = wr.get_realtime()
            made.room("order:{id}", lambda user, p: True)
            call_command("check", verbosity=0)
            with pytest.raises(ValueError, match="site and secret are required"):
                made.config(42)
    finally:
        wr._current, wr._from_settings = kept, None
