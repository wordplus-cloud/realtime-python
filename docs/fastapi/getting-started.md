# Getting started with FastAPI

Live updates, chat, who is online, calls, group calls and live streams in a FastAPI or Starlette app, through WordPlus Cloud. Two packages:

- **Your server** (`wordplus-realtime`, with `wordplus_realtime.fastapi`) declares your rooms once, says who may join them and call whom, and sends events to rooms and to users: the browser routes as a router, for the user your app finds.
- **The page** (`@wordplus/realtime`, the client your routes serve it, with no Node) connects to WordPlus Cloud, joins rooms, and sends and gets events: `emit`, `emitWithAck`, `volatile`.

What goes through WordPlus Cloud is sealed with keys only your server and the browsers of your users hold. Ready-made parts come with it, all optional: the Better Messages chat, its list of who is online and its call screen, and the Easy Stream player. Without them, your own components draw everything on the same API ([your own interface](https://docs.wordplus.cloud/apps/interface/)). The [example app](example.md) is a whole shop built this way.

Your framework can run websockets of its own. [Why WordPlus Cloud](https://docs.wordplus.cloud/apps/why/) says what the cloud runs for you, and what it adds.

**Try it live** at [fastapi.docs.wordplus.cloud](https://fastapi.docs.wordplus.cloud/): the [example app](example.md) of this guide as a demo, a shop of your own for a day, with Ben and Cara opening in windows of their own.

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

Python reads no `.env` by itself: set them in the environment of the server process, or start it with `uvicorn app:app --env-file .env`.

## 2. Install

```bash
pip install 'wordplus-realtime[fastapi]'    # uv add works the same
```

That is all, with no Node: the package carries the browser files, and its router serves them. The client as an ES module, the worker that lets the tabs of a user share one connection, the room client for group calls, and `realtime-ui.min.js` and `realtime-ui-streams.min.js`, the ready-made parts, the second for live streams. Each release serves the ones its package came with, from a folder named after their version.

## 3. Your server

```python
# app.py
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from wordplus_realtime import Realtime
import wordplus_realtime.fastapi as wr

realtime = Realtime.from_environment(       # WORDPLUS_SITE, WORDPLUS_SECRET, WORDPLUS_LOCAL_KEY
    # What others see of a user: in presence, calls and the directory.
    profile=lambda user: {"name": name_of(user), "avatar": avatar_of(user)},
)

# The room of an order: its customer may join, and the last 20 updates are kept.
realtime.room("order:{id}", lambda user, p: user is not None and owner_of(p["id"]) == user, history=20)

async def current_user(request: Request):
    """The user id of the request, or None: your sign-in, here a session."""
    return request.session.get("user")

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)
app.include_router(wr.router(realtime, current_user), prefix="/api/realtime")   # POST /auth, /calls, /keys, /webhook, GET /files/…
app.mount("/static", StaticFiles(directory="static"), name="static")
```

- **`current_user(request)`** gives the request user id, or `None`. It may be `async`: a token, a session, a dependency of your own.
- **The pattern of a room** names its parts: `order:{id}` matches `order:1042`, and the rule gets `{"id": "1042"}`.
- **The rules** (`room()`, `calls()`, `kind()`, `profile`) are plain functions. The router runs them on a worker thread, so a blocking database query in one does not hold up the event loop.
- **The routes take JSON POSTs,** and GETs for the browser files alone. A page on another site cannot send JSON without asking first, and it is never allowed to, so a session cookie needs no CSRF token here.

## 4. The page

```python
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="templates")

@app.get("/orders/{pk}")
async def order_page(request: Request, pk: int):
    head = realtime.head(await current_user(request))
    return templates.TemplateResponse(request, "order.html", {"realtime_head": head, "pk": pk})
```

```html
<!-- templates/order.html: the settings, and the import map of the client the router serves -->
<head>
    {{ realtime_head|safe }}
    <script type="module" src="/static/order.js"></script>
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

`realtime.head()` writes the settings for the user as `window.wordplusRealtimeConfig`, so the page connects with no request first, and an import map naming `@wordplus/realtime` the client the router serves, so `order.js` imports it as it is. With a bundler of your own, `npm install @wordplus/realtime` and `realtime.head(user, importmap=False)`. A single-page app can skip rendering, and connect with `connect( { app: 's1500000007' } )`, which asks `/api/realtime/keys` first and takes the worker and the room client from the router.

## 5. Send

```python
@app.post("/orders/{pk}/ship")
async def ship(pk: int):
    order = await mark_shipped(pk)
    await realtime.to(f"order:{pk}").aemit("updated", {"status": order.status})
    return {"ok": True}
```

Everyone in the room gets `{ status }`, sealed with the room key on the way, and a page that reconnects later gets it from the room history. `aemit()` runs the request on a worker thread.

## Next

- [Rooms](rooms.md), [presence and who is online](presence.md), [sending from your server](sending.md) and [events from the page](events.md), with the ready-made chat
- [Calls and group calls](calls.md), with the call screen
- [Encryption and your users](encryption.md)
- [Customizing the screens](customizing.md): their look, a piece of your own, or their whole code
- [Deploying](deploying.md), and [the example app](example.md)
- The [Python reference](../reference.md), the [browser reference](https://docs.wordplus.cloud/apps/browser/), [errors](https://docs.wordplus.cloud/apps/errors/) and [limits](https://docs.wordplus.cloud/apps/limits/)
