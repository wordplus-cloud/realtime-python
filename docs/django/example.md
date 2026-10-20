# The Django example

A whole shop on Django, in the package `examples/django`: sign in as Ann (support), Ben (a customer) or Cara (the warehouse), each in a browser of their own, and try everything this guide covers.

![The API demo signed in as Ben: his order 1042, shipped and live, with its timeline. The mugs and how many are looking at them. The daily meeting. His chat with Ann. The people in the shop, with call buttons. And the webhooks the server got](https://docs.wordplus.cloud/img/django/example.webp)

| On the page | What makes it |
|---|---|
| The order of Ben follows as Ann moves it on, and Ben alone gets a notice | the `order:{id}` [room](rooms.md), sent to by the `order_status` view once its transaction commits, with `except_tab`, and `to_user` ([sending](sending.md)) |
| The chat of Ann and Ben, with typing, reactions and read ticks | `<chat-room>` on the `chat:{a}:{b}` room, which lets pages [send](events.md) them. The server keeps the conversation from the webhook and gives it back from `GET /chat/messages` ([keeping the conversation](events.md#keeping-the-conversation)). The name and picture of the other side above it from the [directory](encryption.md#your-users) |
| Who is in the shop, with a call button for each | `<online-list>` on the `shop` [presence](presence.md) room, the name and role of each member |
| The daily meeting | `<room-button>`, a [group call](calls.md) |
| The order timeline, and what the cloud carried of it | the order room [history](rooms.md#history-and-nothing-lost). The `order_wire` view seals the update as the server sends it, with the room key ([encryption](encryption.md)) |
| How many are looking at the mugs | the `product:{id}` room, public and [counted](presence.md#counting) |
| The webhooks the server got | `realtime.on("*", …)`, which sends each on to the shop `webhooks` room ([webhooks](sending.md#webhooks)) |

**Try it online** at [django.docs.wordplus.cloud](https://django.docs.wordplus.cloud/): this example as a demo, where every visitor gets a shop of their own for a day, and its links open Ben and Cara in windows of their own. Its calls end after 10 minutes and its meetings after 15 (`limits` in the demo part, which the page keeps to). Under each card, **See the code** shows the parts of this example that make it, on the server and on the page: the lines between `# region demo: <card>` and `# endregion` in its files.

## Run it

```bash
cd examples/django
cp .env.example .env              # the key and secret of your app, with http://localhost:8000 among its addresses, and a local key
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python manage.py migrate        # the people of the shop (Ann 34, Ben 42, Cara 43) and the order of Ben
.venv/bin/python manage.py runserver      # http://localhost:8000
```

Open it in two browsers (or a private window), sign in as Ann in one and Ben in the other, and move the order on, chat, and call.

## Its files

| File | |
|---|---|
| `store/realtime.py` | the realtime server part: credentials, profiles from the shop people, the rooms and calls it declares, and its webhooks |
| `config/settings.py` | `wordplus_realtime.django` among the apps, and `shop/` as the static files |
| `config/urls.py` | the browser routes, the webhook and the browser files with `wr.urls()`, and the shop |
| `store/views.py` | signing in, the page, moving the order on, and what the cloud carried of it |
| `store/shops.py` | the shops, by number: their people, order and room names |
| `store/models.py`, `store/migrations/` | the profiles of the people and the order, and the data they start with |
| `store/templates/store/page.html` | the page, with `{% wordplus_realtime %}`, the settings and the import map of the client, and the shop data through `json_script` |
| `demo.py` | the demo part alone (`WORDPLUS_DEMO=1`), the same file in the three Python examples: a shop for each visitor, its windows, and the frame around the page |
| `shop/shop.js` | the page script, served as it is with no Node and no bundler: `connect()`, the order, the product, the chat, who is in the shop, the webhooks, the meeting and the call screen. The same file runs the shop in every example |
