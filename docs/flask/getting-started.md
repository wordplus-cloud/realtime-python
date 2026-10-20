# Getting started with Flask

Live updates, chat, who is online, calls, group calls and live streams in a Flask app, or any Python framework that takes a route, through WordPlus Cloud. Two packages:

- **Your server** (`wordplus-realtime`) declares your rooms once, says who may join them and call whom, and sends events to rooms and to users. In Flask it is one route and a few rules.
- **The page** (`@wordplus/realtime`, the client your routes serve it, with no Node) connects to WordPlus Cloud, joins rooms, and sends and gets events: `emit`, `emitWithAck`, `volatile`.

What goes through WordPlus Cloud is sealed with keys only your server and the browsers of your users hold. Ready-made parts come with it, all optional: the Better Messages chat, its list of who is online and its call screen, and the Easy Stream player. Without them, your own components draw everything on the same API ([your own interface](https://docs.wordplus.cloud/apps/interface/)). The [example app](example.md) is a whole shop built this way.

Your framework can run websockets of its own. [Why WordPlus Cloud](https://docs.wordplus.cloud/apps/why/) says what the cloud runs for you, and what it adds.

**Try it live** at [flask.docs.wordplus.cloud](https://flask.docs.wordplus.cloud/): the [example app](example.md) of this guide as a demo, a shop of your own for a day, with Ben and Cara opening in windows of their own.

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

Python reads no `.env` by itself: `flask run` reads it when python-dotenv is installed (`pip install python-dotenv`). Elsewhere, set them in the environment of the server process.

## 2. Install

```bash
pip install 'wordplus-realtime[flask]'     # uv add works the same
```

That is all, with no Node: the package carries the browser files, and its extension serves them. The client as an ES module, the worker that lets the tabs of a user share one connection, the room client for group calls, and `realtime-ui.min.js` and `realtime-ui-streams.min.js`, the ready-made parts, the second for live streams. Each release serves the ones its package came with, from a folder named after their version.

## 3. Your server

```python
# app.py
from flask import Flask, render_template
import wordplus_realtime.flask
from wordplus_realtime import Realtime

realtime = Realtime.from_environment(       # WORDPLUS_SITE, WORDPLUS_SECRET, WORDPLUS_LOCAL_KEY
    # What others see of a user: in presence, calls and the directory.
    profile=lambda user: {"name": name_of(user), "avatar": avatar_of(user)},
)

# The room of an order: its customer may join, and the last 20 updates are kept.
realtime.room("order:{id}", lambda user, p: user is not None and owner_of(p["id"]) == user, history=20)

app = Flask(__name__)

# POST /api/realtime/auth, /calls and /keys for the user of the request, the webhook, which the realtime server signs,
# and GET /api/realtime/files/…, the browser files. And wordplus_realtime() for the page templates.
wordplus_realtime.flask.init_app(app, realtime)
```

- **The user** is whatever id your app knows them by, an int or a str, or `None`: the Flask-Login `current_user` when your app has it, else `session["user_id"]`. Another way: `init_app(app, realtime, user=lambda: …)`.
- **The pattern of a room** names its parts: `order:{id}` matches `order:1042`, and the rule gets `{"id": "1042"}`.
- **The routes take JSON POSTs,** and GETs for the browser files alone. A page on another site cannot send JSON without asking first, and it is never allowed to, so the session cookie needs no CSRF token here: CSRFProtect of Flask-WTF, if you use it, leaves them out.
- **Another framework** (Bottle, Pyramid, Falcon, Litestar) answers the same way: `answer_request()` and `webhook()` give `(status, body)`, and `file()` `(status, headers, body)` for a browser file.

## 4. The page

```python
@app.get("/orders/<int:pk>")
def order_page(pk):
    return render_template("order.html", pk=pk)
```

```html
<!-- templates/order.html: the settings, and the import map of the client the routes serve -->
<head>
    {{ wordplus_realtime() }}
    <script type="module" src="{{ url_for('static', filename='order.js') }}"></script>
</head>
```

```js
// static/order.js, as it is: no Node and no bundler
import { connect } from '@wordplus/realtime';

const rt = await connect( window.wordplusRealtimeConfig );

const order = rt.join( 'order:1042' );
order.on( 'updated', ( data ) => showStatus( data.status ) );
order.on( 'error', ( e ) => console.warn( e.code ) );   // forbidden, no_rule …
```

`wordplus_realtime()` writes the settings for the user of the request as `window.wordplusRealtimeConfig`, so the page connects with no request first, and an import map naming `@wordplus/realtime` the client the routes serve, so `order.js` imports it as it is. With a bundler of your own, `npm install @wordplus/realtime` and `wordplus_realtime(importmap=False)`.

## 5. Send

After your own work is saved:

```python
realtime.to("order:1042").emit("updated", {"status": "shipped"})
```

Everyone in the room gets `{ status }`, sealed with the room key on the way, and a page that reconnects later gets it from the room history.

## Next

- [Rooms](rooms.md), [presence and who is online](presence.md), [sending from your server](sending.md) and [events from the page](events.md), with the ready-made chat
- [Calls and group calls](calls.md), with the call screen
- [Encryption and your users](encryption.md)
- [Customizing the screens](customizing.md): their look, a piece of your own, or their whole code
- [Deploying](deploying.md), and [the example app](example.md)
- The [Python reference](../reference.md), the [browser reference](https://docs.wordplus.cloud/apps/browser/), [errors](https://docs.wordplus.cloud/apps/errors/) and [limits](https://docs.wordplus.cloud/apps/limits/)
