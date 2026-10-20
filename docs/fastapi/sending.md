# Sending from FastAPI

Your server sends events to rooms and to users, after its own work is saved. Everyone in the room gets them, sealed on the way, and a room that keeps history keeps them.

## To a room

```python
await realtime.to("order:1042").aemit("updated", {"status": "shipped"})
await realtime.to(["order:1042", "staff"]).aemit("updated", {"status": "shipped"})
```

- **`aemit()`** runs the request on a worker thread, so the event loop goes on. `emit()` is the same, blocking, for a sync route or a task.
- **The answer** is the kept event ids, by room, for the rooms that keep history.
- **A refusal** raises `RealtimeError`, whose `code` says why: `too_large`, `too_many`, `reserved` (event names kept for the room itself), `bad_room` ([errors](https://docs.wordplus.cloud/apps/errors/)).
- **Up to 1 MB** an event, to up to 1,000 rooms at once.

## Not back to the tab that made it

A page that made the change already shows it. Send its tab with the request, and leave it out:

```js
// The page
await fetch( `/orders/${ id }/status`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Realtime-Tab': rt.tab },
    body: JSON.stringify( { status: 'shipped' } ),
} );
```

```python
# The route
@app.post("/orders/{pk}/status")
async def order_status(pk: int, body: StatusBody, request: Request):
    order = await set_status(pk, body.status)
    await realtime.to(f"order:{pk}").except_tab(request.headers.get("x-realtime-tab")).aemit("updated", {"status": order.status})
    return {"ok": True}
```

## To a user

Every tab and device a user has open, wherever they are in your app:

```python
await realtime.to_user(42).aemit("notice", {"text": "Your order shipped"})
await realtime.to_user([42, 43]).to("staff").aemit("notice", {"text": "A new order"})
```

```js
rt.on( 'notice', ( data ) => toast( data.text ) );   // on the page, for its signed-in user
```

It is sealed with the key of the user, so only their pages read it. A user with nothing open gets nothing: send an email for what must reach them.

## Many at once

```python
await run_in_threadpool(realtime.batch, [
    {"rooms": "order:1042", "event": "updated", "data": {"status": "shipped"}},
    {"users": 42, "event": "notice", "data": {"text": "Your order shipped"}},
])
```

Up to 100 events a call.

## Asking about a room

```python
realtime.in_room("shop").count()
realtime.in_room("shop").members()                     # of a presence room, their info opened
realtime.in_room("chat:34:42").history(limit=50)
realtime.in_room("chat:34:42").forget(event_id)        # one kept event, forget() for all
realtime.in_room("chat:34:42").kick(43)                # out now, and back only if your rule lets them in again
```

They block: run them with `run_in_threadpool` in an async route. `kick()` also moves a sealed room key on, so what is sent after it is not theirs to read, when your server keeps the key generations ([encryption](encryption.md#when-someone-loses-access)).

## A user

```python
realtime.user(42).disconnect()                                   # out of everything at once
replies = realtime.user(42).ask("cart", {"why": "checkout"})     # their pages reply with rt.answer( "cart", fn )
```

`disconnect()` takes the user out of every room, call and live stream on every connection, when you sign them out or block them. Their pages ask your routes again, so your rules decide whether they come back. They block: run them with `run_in_threadpool` in an async route. The rooms in use, what your app uses, the log of your webhook, and group calls and live streams from your server: [sending in depth](https://docs.wordplus.cloud/apps/sending/#a-user), [calls](https://docs.wordplus.cloud/apps/calls/#from-your-server), [live streams](https://docs.wordplus.cloud/apps/streams/#from-your-server).

## Webhooks

Your server can hear what happens in rooms. Set the address on your app page in your WordPlus Cloud account (on your computer, through a tunnel: [while you develop](https://docs.wordplus.cloud/apps/sending/#while-you-develop)), `https://shop.example.com/api/realtime/webhook`, which `wr.router()` already answers:

```python
# The rule of a room says which events of the pages come here too
realtime.room("chat:{a}:{b}", is_one_of, history=50, emit=["message", "typing"], webhook=["message"])

# A guest in a public room sends with no "from": kept here from signed-in people alone.
realtime.on("message", lambda e: "from" in e and save_message(e["event_id"], e["room"], e["from"], e["data"]["text"], e["at"]))   # a repeat has the same id
realtime.on("user.offline", lambda e: mark_away(e["user"]))
```

- **What comes:** the page events a rule names in `webhook`, by their name. `room.occupied` and `room.vacated`. `member.joined` and `member.left`. `user.online` and `user.offline`. `stream.live` and `stream.ended`, a live stream going live and ending, with its name in `stream`. `call.ended`, `group.joined`, `group.left`, `stream.joined` and `stream.left`, what people used, with how long once it is over, to charge them by ([charging for calls and streams](https://docs.wordplus.cloud/use-cases/charging/)). `"*"` gets them all.
- **Checked and opened:** each request is signed, and checked before your handler sees it. Sealed data comes opened. The handlers run on a worker thread.
- **At least once:** each event has its id, so a repeat can be dropped. A request that fails is tried again for 24 hours.

More, with Node and PHP side by side: [sending in depth](https://docs.wordplus.cloud/apps/sending/).
