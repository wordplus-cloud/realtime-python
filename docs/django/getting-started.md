# Getting started with Django

Live updates, chat, who is online, calls, group calls and live streams in a Django app, through WordPlus Cloud. Two packages:

- **Your server** (`wordplus-realtime`, with `wordplus_realtime.django`) declares your rooms once, says who may join them and call whom, and sends events to rooms and to users: the browser routes for the session user, the page settings with the CSRF token, and profiles from the Django user model.
- **The page** (`@wordplus/realtime`, the client your routes serve it, with no Node) connects to WordPlus Cloud, joins rooms, and sends and gets events: `emit`, `emitWithAck`, `volatile`.

What goes through WordPlus Cloud is sealed with keys only your server and the browsers of your users hold. Ready-made parts come with it, all optional: the Better Messages chat, its list of who is online and its call screen, and the Easy Stream player. Without them, your own components draw everything on the same API ([your own interface](https://docs.wordplus.cloud/apps/interface/)). The [example app](example.md) is a whole shop built this way.

Your framework can run websockets of its own. [Why WordPlus Cloud](https://docs.wordplus.cloud/apps/why/) says what the cloud runs for you, and what it adds.

**Try it live** at [django.docs.wordplus.cloud](https://django.docs.wordplus.cloud/): the [example app](example.md) of this guide as a demo, a shop of your own for a day, with Ben and Cara opening in windows of their own.

![Two browsers side by side: Ann marks order 1042 as shipped on the staff page of the shop, and the order page of Ben shows Shipped at once, without a reload](https://docs.wordplus.cloud/img/apps/orders-live.webp)

## 1. Your app in WordPlus Cloud

**Apps are in early access.** Ask for it on our [contact form](https://www.wordplus.cloud/contact), and we turn **Apps** on in your WordPlus Cloud account. Until then your account has no Apps page.

In your WordPlus Cloud account, go to **Apps → Add app**. Name it, and list the addresses its pages are served from: `https://shop.example.com`, and `http://localhost:8000` while you develop. Only pages on those addresses may connect.

You get the app **key**, public because every page carries it, and its **secret**, for your server only. Make a **local key** of your own too: everything sealed is sealed with keys derived from it, and it never leaves your servers.

```dotenv
WORDPLUS_SITE=s1500000007
WORDPLUS_SECRET=…
WORDPLUS_LOCAL_KEY=…        # openssl rand -hex 32; the same on every server of the app, kept as long as the app
```

Django reads no `.env` by itself: set them in the environment of the server process, or read the file at the top of `settings.py`, such as with python-dotenv (`load_dotenv(BASE_DIR / ".env")`). The package takes them as Django starts, and checks them when first used, so `manage.py migrate` and `collectstatic` run without them.

## 2. Install

```bash
pip install 'wordplus-realtime[django]'     # uv add works the same
```

That is all, with no Node: the package carries the browser files, and its routes serve them. The client as an ES module, the worker that lets the tabs of a user share one connection, the room client for group calls, and `realtime-ui.min.js` and `realtime-ui-streams.min.js`, the ready-made parts, the second for live streams. Each release serves the ones its package came with, from a folder named after their version.

```python
# settings.py
INSTALLED_APPS = [
    # …
    "wordplus_realtime.django",          # its template tag, {% wordplus_realtime %}
]
```

## 3. Your server

```python
# shop/realtime.py: the app's Realtime, made from WORDPLUS_SITE, WORDPLUS_SECRET and WORDPLUS_LOCAL_KEY
from wordplus_realtime.django import realtime

from .models import Order

# The room of an order: its customer may join, and the last 20 updates are kept.
realtime.room(
    "order:{id}",
    lambda user, p: Order.objects.filter(pk=p["id"], customer_id=user).exists(),
    history=20,
)
```

```python
# shop/apps.py: the rooms are declared as Django starts, before the first request
from django.apps import AppConfig

class ShopConfig(AppConfig):
    name = "shop"

    def ready(self):
        from . import realtime  # noqa: F401
```

```python
# urls.py: POST /api/realtime/auth, /calls, /keys and /webhook, and GET /api/realtime/files/…, the browser files
from django.urls import include, path

urlpatterns = [
    path("api/realtime/", include("wordplus_realtime.django.routes")),
    # …
]
```

- **The user** is the session (`request.user`), and the Django CSRF check stays on for the browser routes. The webhook is exempt, as the realtime server signs it, and the browser files ask no session.
- **What others see of a user** is their full name, or their username, from your user model.
- **Its settings,** all optional, go in `WORDPLUS_REALTIME` by name: `{"base": "/api/realtime", "user": "shop.auth.current_user", "profile": "shop.people.profile_of"}`, functions by their dotted path.
- **The pattern of a room** names its parts: `order:{id}` matches `order:1042`, and the rule gets `{"id": "1042"}`.
- **The rules** are plain functions that may query your models the usual way.

## 4. The page

```html
{# shop/templates/shop/order.html #}
{% load static wordplus_realtime %}
<head>
    {% wordplus_realtime %}
    <script type="module" src="{% static 'order.js' %}"></script>
</head>
```

```js
// shop/static/order.js, as it is: no Node and no bundler
import { connect } from '@wordplus/realtime';

const rt = await connect( window.wordplusRealtimeConfig );

const order = rt.join( 'order:1042' );
order.on( 'updated', ( data ) => showStatus( data.status ) );
order.on( 'error', ( e ) => console.warn( e.code ) );   // forbidden, no_rule …
```

`{% wordplus_realtime %}` writes the settings for the request user, the routes with the CSRF token as `X-CSRFToken` and the user keys, so the page connects with no request first, and an import map naming `@wordplus/realtime` the client the routes serve, so `order.js` imports it as it is.

- **It needs the request** in the template context: `django.template.context_processors.request`, which new projects have.
- **A view that knows its user another way** names them: `{% wordplus_realtime user=customer.pk %}`.
- **With a bundler of your own,** `npm install @wordplus/realtime`, import it the same way, and leave the map out: `{% wordplus_realtime importmap=False %}`.
- **A Realtime of your own,** made with `Realtime.from_environment(…)`, takes `path("api/realtime/", include(wr.urls(realtime)))` with `import wordplus_realtime.django as wr`, and the tag takes that one.

## 5. Send

After your own work is saved, once the transaction commits:

```python
from django.db import transaction

order.status = "shipped"
order.save()
transaction.on_commit(lambda: realtime.to(f"order:{order.pk}").emit("updated", {"status": order.status}))
```

Everyone in the room gets `{ status }`, sealed with the room key on the way, and a page that reconnects later gets it from the room history.

## Next

- [Rooms](rooms.md), [presence and who is online](presence.md), [sending from your server](sending.md) and [events from the page](events.md), with the ready-made chat
- [Calls and group calls](calls.md), with the call screen
- [Encryption and your users](encryption.md)
- [Customizing the screens](customizing.md): their look, a piece of your own, or their whole code
- [Deploying](deploying.md), and [the example app](example.md)
- The [Python reference](../reference.md), the [browser reference](https://docs.wordplus.cloud/apps/browser/), [errors](https://docs.wordplus.cloud/apps/errors/) and [limits](https://docs.wordplus.cloud/apps/limits/)
