# Rooms in Django

A room is a name pages join to get its events. Your server declares your rooms once, by pattern, with what they keep and allow, and answers for each user who asks to join.

## Declaring rooms

```python
# shop/realtime.py
# The updates of an order: its customer and the staff, the last 20 kept.
def may_follow_order(user, p):
    if user is None:
        return False
    order = Order.objects.filter(pk=p["id"]).first()
    return order is not None and (order.customer_id == user or User.objects.filter(pk=user, is_staff=True).exists())

realtime.room("order:{id}", may_follow_order, history=20)

# A chat between two people, chat:34:42: those two only. They send messages and typing to it, and the messages are kept.
realtime.room("chat:{a}:{b}", lambda user, p: str(user) in (p["a"], p["b"]), history=50, emit=["message", "typing"])

# The page of a product: anyone, signed in or not, with a live count of who is looking.
realtime.room("product:{id}", public=True, count=True)
```

- **`user`** is the request user id (`request.user.pk`), or `None`.
- **The parts** of the pattern come as strings: `{"a": "34", "b": "42"}`. A rule may take only `user`, or `user, params, room`.
- **The answer:** `False` (or `None`) for no, `True` for yes, or `{"info": …}` for yes with what the others see of them in a [presence](presence.md) room.
- **For one user**, the answer may narrow the room: `{"emit": ["typing"]}` lets them send only that, `{"readOnly": True}` nothing.

## Names and patterns

- **Room names:** up to 200 characters of `A-Z a-z 0-9 _ - = @ , . ; :`.
- **`{name}`** matches one or more characters other than `:` and `.`.
- **The most specific rule wins:** the pattern with the most fixed characters, and on a tie the one declared first. A room no pattern matches is refused (`no_rule`).
- **When the rule runs:** when a page joins, and when its token is renewed (every 6 hours by default). A page asks for every room it joins in the same moment in one request, and keeps the tokens across reconnects and moves.

## What a room keeps and allows

| Option | Default | |
|---|---|---|
| `history` | none | Events kept for pages that reconnect: a number (`50`), up to 1,000, for 5 minutes. Or `{"last": 50, "days": 0.002}` for less (0.002 of a day is about 3 minutes) |
| `emit` | none | Events pages may send to the room: names, or `"*"` for any ([events from the page](events.md)) |
| `presence` | off | Its members are listed, with their info, and `join` and `leave` tell the others ([presence](presence.md)) |
| `count` | off | A live count of who is in it, at any size, without a list |
| `webhook` | none | Which of the page events your server gets too ([sending from your server](sending.md#webhooks)) |
| `public` | off | Anyone may join, signed in or not. Its grant names no user, so it may sit in a page a CDN caches |
| `seal` | on | Its events, its member info and its history are sealed with the room key ([encryption](encryption.md)) |

The options travel in the room token, signed by your server, so WordPlus Cloud enforces them and nothing is set in two places.

## Joining

```js
const order = rt.join( 'order:1042' );
order.on( 'updated', ( data, meta ) => showStatus( data.status ) );   // meta: { from, id, at }
order.on( 'joined', () => showLive() );
order.on( 'error', ( e ) => console.warn( e.code ) );   // forbidden, no_rule, full …

rt.leave( 'order:1042' );
```

- `join()` gives the same room for the same name. The tabs of a user ride one connection (the worker), each with its own rooms.
- **Events reach a listener opened:** you never handle sealed values.
- **`meta.from`** is the user who sent it from a page, or nothing for your server. `meta.id` and `meta.at` are the kept event id and time.
- **Reserved names:** `joined`, `join`, `leave`, `count` and `error` are kept for the room itself. Your server and pages cannot send them.

## History, and nothing lost

A room keeps its events for 5 minutes at most, for recovery. Your app keeps its own records, such as the messages of a chat, from the [webhook](events.md#keeping-the-conversation).

A room that keeps history gives a page that comes back what it missed: a reconnect within the history span gets the missed events first, in order, with `meta.replayed`, then the new ones.

```js
const { events, more } = await order.history( { limit: 50 } );          // the newest 50, oldest first
const older = await order.history( { before: events[ 0 ].id, limit: 50 } );
```

Events over 64 KB are sent but not kept. `volatile` ones are never kept. Your server reads and erases history too: `realtime.in_room("order:1042").history()` and `.forget()` ([sending from your server](sending.md#asking-about-a-room)).

More, with Node and PHP side by side: [rooms in depth](https://docs.wordplus.cloud/apps/rooms/).
