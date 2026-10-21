# wordplus-realtime

WordPlus Cloud's realtime SDK for Python, outside WordPress: your server's part of rooms, presence, who is online, calls and group calls, sealed end to end. It declares your rooms and who may join, call and see what, signs it for the browser, and sends your events to rooms and to users. The browser part is the npm package [`@wordplus/realtime`](https://docs.wordplus.cloud/apps/browser/), with the chat, the list of who is online and the call screen of Better Messages as ready-made parts.

**Docs:** a whole guide each for [Django](https://docs.wordplus.cloud/django/getting-started/), [FastAPI](https://docs.wordplus.cloud/fastapi/getting-started/) and [Flask](https://docs.wordplus.cloud/flask/getting-started/) (in this package: [docs/django](docs/django/getting-started.md), [docs/fastapi](docs/fastapi/getting-started.md), [docs/flask](docs/flask/getting-started.md)), and the [Python reference](docs/reference.md).

**Examples:** the same shop in [Django](examples/django), [FastAPI](examples/fastapi) and [Flask](examples/flask): sign in as Ann, Ben or Cara, and try live updates, a chat with typing, reactions and read ticks, who is online, calls and a group call.

It answers the browser exactly as WordPress's [`wordplus/realtime`](https://docs.wordplus.cloud/wordpress/getting-started/) does, and the Node and PHP packages: the same routes, tokens, keys and calls, checked against the same vectors (`spec/vectors.json`).

```bash
pip install 'wordplus-realtime[django]'   # or [fastapi] or [flask], or none; uv add works the same
```

It carries the browser files too, the client as an ES module among them, and its routes serve them, so a Python app needs no Node: the page head it writes names `@wordplus/realtime` the client by an import map. With a bundler of your own, `npm install @wordplus/realtime`. It is also on WordPlus's own mirror, for a network that can't reach PyPI: add `--find-links https://packages.wordplus.cloud/pypi/index.html` to pip or uv.

```dotenv
WORDPLUS_SITE=s1500000007     # your app's key, from your WordPlus Cloud account (Apps)
WORDPLUS_SECRET=…             # its secret, never in a page
WORDPLUS_LOCAL_KEY=…          # your own: openssl rand -hex 32; it never leaves your servers
```

```python
from wordplus_realtime import Realtime

realtime = Realtime.from_environment(profile=lambda user: {"name": name_of(user)})
realtime.room("order:{id}", lambda user, p: owns_order(user, p["id"]), history=20)
realtime.room("chat:{a}:{b}", lambda user, p: str(user) in (p["a"], p["b"]), history=50, emit=["message", "typing"])
realtime.calls("support:{a}:{b}", lambda user, other, p: may_support(user, other))

realtime.to("order:42").emit("updated", {"status": "paid"})
realtime.to_user(42).emit("notice", {"text": "Your order shipped"})
```

## Django

```python
# settings.py
INSTALLED_APPS = [..., "wordplus_realtime.django"]

# shop/realtime.py, imported by the app ready(): the Realtime made from the environment and WORDPLUS_REALTIME
from wordplus_realtime.django import realtime
realtime.room("order:{id}", lambda user, p: owns_order(user, p["id"]), history=20)

# urls.py: POST auth, calls, keys for the session user, the webhook, and GET the browser files
urlpatterns = [path("api/realtime/", include("wordplus_realtime.django.routes"))]
```

```html
{% load wordplus_realtime %}
<head>
    {% wordplus_realtime %}    {# the settings with the CSRF token, and the import map of the client #}
    <script type="module">
        import { connect } from '@wordplus/realtime';
        const rt = await connect( window.wordplusRealtimeConfig );
        rt.join( 'order:42' ).on( 'updated', ( data ) => refresh( data ) );
    </script>
</head>
```

## FastAPI and Starlette

```python
import wordplus_realtime.fastapi as wr

app.include_router(wr.router(realtime, current_user), prefix="/api/realtime")   # current_user(request) may be async
head = realtime.head(user)                                                     # for the page head, as it is
await realtime.to("order:42").aemit("updated", {"status": "paid"})
```

## Flask

```python
import wordplus_realtime.flask

wordplus_realtime.flask.init_app(app, realtime)    # the routes, the webhook and the files, the Flask-Login user
```

```html
<head>{{ wordplus_realtime() }}</head>
```

## In this version

- **User ids** are yours, a number or text such as `user_2abc` or `auth0|5f7c`, up to 64 characters with no space, in rooms, presence, calls and the directory alike.
- **Python 3.9 or later**, with PyNaCl (libsodium) for the sealing.

## Licence

MIT.

## Developing

```bash
uv venv .venv && uv pip install --python .venv/bin/python -e '.[test]'
.venv/bin/python -m pytest      # the vectors, the routes, tokens, keys, sealing, sending, Django and FastAPI
```
