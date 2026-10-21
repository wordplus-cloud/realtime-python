# Events from the page, in Django

Pages send events to the rooms they are in, straight through WordPlus Cloud, with no request to your server: chat messages, typing, read ticks, a cursor. A room rule says which events its pages may send.

![The chat window of Ben shows “Ann typing” while Ann, in her own browser, writes a reply](https://docs.wordplus.cloud/img/apps/chat-typing.webp)

## What a room allows

```python
# The chat of Ann and Ben: they send messages, typing, reactions and read ticks. The messages and reactions reach this
# server by webhook, which keeps the conversation.
realtime.room("chat:{a}:{b}", lambda user, p: str(user) in (p["a"], p["b"]),
              history=50, emit=["message", "typing", "reaction", "read"], webhook=["message", "reaction"])
```

- **`emit`** lists the names, or `"*"` for any. None by default: a room your server alone sends to.
- **`webhook`** names those your server gets too, to keep them ([below](#keeping-the-conversation)).
- **`history`** keeps the last events of the room for 5 minutes: what a page that reconnects missed comes again from it.
- **The answer for one user** can narrow it: `{"emit": ["typing"]}`, or `{"readOnly": True}`.
- **Reserved:** `joined`, `join`, `leave`, `count` and `error` are the names kept for the room itself.

## Sending

A page sends to a room it has joined, and hears what the others send:

```js
const chat = rt.join( 'chat:34:42' );

chat.emit( 'message', { text: 'Hi' } );                                // sent, nothing waited for
const { id, at } = await chat.emitWithAck( 'message', { text: 'Hi' } ); // WordPlus Cloud took it: checked, kept, sent
chat.volatile.emit( 'typing', { on: true } );                          // dropped rather than queued while off line, never kept
await chat.timeout( 5000 ).emitWithAck( 'message', { text: 'Hi' } );   // an ack waited for 5 seconds at most

chat.on( 'message', ( data, meta ) => draw( data.text, meta.from ) );   // meta: { from, id, at }
```

- **Everyone in the room** gets it, the other tabs and devices of the sender too. The tab that sent it does not, so it draws its own at once.
- **`emitWithAck`** resolves with the kept event id and time, or rejects with a code: `not_allowed` (the rule does not list it), `forbidden`, `rate_limited`, `too_large`.
- **`meta.from`** is the sender user id, as your server vouched for them: a page cannot send as someone else.
- **Binary:** an `ArrayBuffer`, `Uint8Array` or `Blob` may be anywhere in the data. It is sealed as binary.
- **Limits:** 1 MB an event, 50 a second a connection, in bursts of up to 100.

## Typing, done the usual way

```js
let sent = 0;
input.addEventListener( 'input', () => {
    if ( Date.now() - sent < 2000 ) return;   // at most every 2 seconds
    sent = Date.now();
    chat.volatile.emit( 'typing', { on: true } );
} );

chat.on( 'typing', ( data, meta ) => showTyping( meta.from, data.on ) );   // and hide it after 4 seconds of nothing
```

## Keeping the conversation

The conversation is for your app to keep, in its own database, as Better Messages keeps its own in the WordPress database. A room keeps its events for 5 minutes, for pages that reconnect. Your server gets the events the rule names in `webhook` ([webhooks](sending.md#webhooks)) and saves them by `event_id`, the id the pages saw as `meta.id`. A view gives them back, a page at a time:

```python
# store/models.py: one row a message, with what the chat draws.
from django.conf import settings
from django.db import models

class Message(models.Model):
    event_id = models.CharField(max_length=64, unique=True)
    room = models.CharField(max_length=200, db_index=True)
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    text = models.TextField()
    at = models.BigIntegerField()                       # milliseconds
    reactions = models.JSONField(default=dict)          # user id -> their reaction

    def chat(self):
        """Its id, who sent it, the text, the time, and each reaction with who chose it."""
        chosen = {}
        for user, key in self.reactions.items():
            chosen.setdefault(key, []).append(user)
        return {"id": self.event_id, "from": self.sender_id, "text": self.text, "at": self.at, "reactions": chosen}
```

```python
# store/realtime.py
# A guest in a public room sends with no "from": kept here from signed-in people alone. A repeat has the same id.
realtime.on("message", lambda e: "from" in e and Message.objects.get_or_create(event_id=e["event_id"], defaults={"room": e["room"], "sender_id": e["from"], "text": e["data"]["text"], "at": e["at"]}))

# One reaction a person on a message, an empty key taking it back.
def react(e):
    message = Message.objects.filter(event_id=e["data"].get("id")).first() if "from" in e else None
    if message is not None:
        message.reactions = {user: key for user, key in {**message.reactions, str(e["from"]): e["data"].get("key", "")}.items() if key}
        message.save(update_fields=["reactions"])

realtime.on("reaction", react)


# store/views.py, at path("chat/<int:a>/<int:b>/messages", views.chat_messages)
@login_required
def chat_messages(request, a, b):
    """The newest 50, or with ?before=<id> the 50 before that one, oldest first. Only its two people may read it."""
    if request.user.pk not in (a, b):
        return HttpResponseForbidden()
    messages = Message.objects.filter(room=f"chat:{a}:{b}")
    if before := Message.objects.filter(event_id=request.GET.get("before")).first():
        messages = messages.filter(pk__lt=before.pk)
    page = list(messages.order_by("-pk")[:51])
    return JsonResponse({"messages": [m.chat() for m in reversed(page[:50])], "more": len(page) > 50})   # each {id, from, text, at, reactions}
```

- **Check there anything that matters:** the events do not go through your server before they are sent on.
- **On localhost** no webhook reaches your server, as a webhook needs an address on the internet. While you build there, the ready-made chat tells your server of each message it sent with its `sent` event, for a route of yours to keep by the same id ([without a webhook](https://docs.wordplus.cloud/use-cases/chat/#without-a-webhook-as-on-localhost)). Or a tunnel gives your computer an address ([while you develop](https://docs.wordplus.cloud/apps/sending/#while-you-develop)).
- **`at`** is in milliseconds, and `reactions` maps each reaction to who chose it. A reaction comes as `{ id, key }`: the one reaction of the user to message `id`, an empty `key` taking it back.
- **A gap:** a page back after the 5 minutes a room keeps its events, or after more came than it keeps, gets what the room still had, then `error` on the room with `{ code: 'gap' }`, still joined. Some events are lost to it, so ask your route for the newest page again: `chat.on( 'error', ( e ) => e.code === 'gap' && reload() )`.

## Ready-made: the chat

Optional, as every ready-made part: the events above are all a chat needs, and [your own interface](https://docs.wordplus.cloud/apps/interface/#a-chat) draws one your way, or runs it in React with `useChat()`. This is the ready-made one.

The Better Messages conversation, on any room: your server conversation paged back as the reader scrolls up, the room filling in what came since, the day separators, the messages of a sender stacked, typing, reactions, the read ticks and the composer. It is one element:

```html
<chat-room room="chat:{{ chat.a }}:{{ chat.b }}" messages="/chat/{{ chat.a }}/{{ chat.b }}/messages" placeholder="{% translate 'Write a message' %}"></chat-room>
```

```js
await rt.callScreen();   // loads the elements and the call screen, rt.ui() the elements without calls
```

- **`messages`** is your route, asked with the page cookies. `chat.load = async ( before ) => ( { messages, more } )` replaces it, for a token or another shape: `before` is `null` for the newest page, or the oldest message shown (`{ id, at }`). With neither, it shows what the room still has.
- **Its room rule** lets it send what it uses: `emit=["message", "typing", "reaction", "read"]`, and names `message` and `reaction` in `webhook` for your server to keep.
- **What it sends** is what you would: `message` as `{ text }` with an ack, `typing` as `{ on }` and `read` as `{ id }`, both volatile, and `reaction` as `{ id, key }`. Your own pages and apps on the same room read it.
- **Names and pictures** come from your [directory](encryption.md#your-users).
- **It fills** the height its place gives it. Its look is that of Better Messages, in a shadow root. Its colours are CSS custom properties your page sets.

`<typing-line room="…">` is the typing line alone, for a page that draws its own messages.

More, with Node and PHP side by side: [events in depth](https://docs.wordplus.cloud/apps/events/).
