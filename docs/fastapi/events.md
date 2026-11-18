# Events from the page, in FastAPI

Pages send events to the rooms they are in, straight through WordPlus Cloud, with no request to your server: chat messages, typing, read ticks, a cursor. A room rule says which events its pages may send.

![The chat window of Ben shows “Ann typing” while Ann, in her own browser, writes a reply](https://docs.wordplus.cloud/img/apps/chat-typing.webp)

## What a room allows

The chat of Ann and Ben is named after them, `chat:34:42`, the smaller id first. A page that joins it asks your server first, and a rule answers: a function your server declares once for every room whose name fits `chat:{a}:{b}`. WordPlus Cloud then holds the page to the answer, and to the events the room lets it send ([permissions](https://docs.wordplus.cloud/apps/permissions/)). This rule says:

1. **The pages send** messages, typing, reactions and read ticks to it, and nothing else.
2. **Your server gets** the messages and reactions too, by webhook, to keep the conversation, and the room keeps its last 50 events for a page that reconnects.
3. **The two people** in the name join, and nobody else.

```python
def may_join_chat(user, p):
    # 3. The two people in the name, and nobody else.
    return str(user) in (p["a"], p["b"])

realtime.room(
    "chat:{a}:{b}",
    may_join_chat,
    # 1. What the pages may send to it.
    emit=["message", "typing", "reaction", "read"],
    # 2. What your server gets too, and the last 50 kept for a page that reconnects.
    webhook=["message", "reaction"],
    history=50,
)
```

- **`emit`** lists the names, or `"*"` for any. None by default: a room your server alone sends to.
- **`webhook`** names those your server gets too, to keep them ([below](#keeping-the-conversation)).
- **`history`** keeps the last events of the room for 5 minutes: what a page that reconnects missed comes again from it.
- **The answer for one user** can narrow it: `{"emit": ["typing"]}`, or `{"readOnly": True}`.
- **Reserved:** `joined`, `join`, `leave`, `count`, `error`, `kicked`, `connect`, `disconnect`, `connect_error`, `state` and `online` belong to the room and the connection, and are never allowed ([reserved names](https://docs.wordplus.cloud/apps/errors/#reserved-names)).

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

The conversation is for your app to keep, in its own database, as Better Messages keeps its own in the WordPress database. A room keeps its events for 5 minutes, for pages that reconnect. Your server gets the events the rule names in `webhook` ([webhooks](sending.md#webhooks)) and saves them by `event_id`, the id the pages saw as `meta.id`. A route of yours gives them back, a page at a time: `/chat/34/42/messages` for the chat `chat:34:42`. Here:

1. **Each message** is kept once, by its `event_id`, from signed-in people alone.
2. **The route** gives the newest 50, or with `?before=<id>` the 50 before that one, oldest first.
3. **Only the two people** of the chat may read it.

```python
# 1. Each message, kept once by its event_id: a repeat has the same one.
def keep_message(e):
    # A guest in a public room sends with no "from": kept from signed-in people alone.
    if "from" not in e:
        return
    save_message(e["event_id"], e["room"], e["from"], e["data"]["text"], e["at"])

realtime.on("message", keep_message)


# 2. The newest 50, or with ?before=<id> the 50 before that one, oldest first.
@app.get("/chat/{a}/{b}/messages")
async def chat_messages(request: Request, a: str, b: str, before: str | None = None):
    # 3. Only the two people of the chat.
    if str(await current_user(request)) not in (a, b):
        return JSONResponse({"error": "not_in_chat"}, status_code=403)

    return await messages_page(f"chat:{a}:{b}", before, 50)   # {"messages": [{id, from, text, at, reactions}], "more"}
```

- **Check there anything that matters:** the events do not go through your server before they are sent on.
- **On localhost** no webhook reaches your server, as a webhook needs an address on the internet. While you build there, the ready-made conversation window (`<chat-room>`) tells your server of each message it sent with its `sent` event, for a route of yours to keep by the same id ([without a webhook](https://docs.wordplus.cloud/use-cases/chat/#without-a-webhook-as-on-localhost)). Or a tunnel gives your computer an address ([while you develop](https://docs.wordplus.cloud/apps/sending/#while-you-develop)).
- **`at`** is in milliseconds, and `reactions` maps each reaction to who chose it. A reaction comes as `{ id, key }`: the one reaction of the user to message `id`, an empty `key` taking it back.
- **A gap:** a page back after the 5 minutes a room keeps its events, or after more came than it keeps, gets what the room still had, then `error` on the room with `{ code: 'gap' }`, still joined. Some events are lost to it, so ask your route for the newest page again: `chat.on( 'error', ( e ) => e.code === 'gap' && reload() )`.
- **Unread counts and pushes** are your server's too: a last-read marker for each member, which the page tells a route of yours, as read marks go volatile and never reach the webhook, and a push to Firebase or APNs for a member `online` says is offline ([what your server keeps for a chat](https://docs.wordplus.cloud/use-cases/chat-server/)).

## Ready-made: the chat

Optional, as every ready-made part: the events above are all a chat needs, and [your own interface](https://docs.wordplus.cloud/apps/interface/#a-chat) draws one your way, or runs it in React with `useChat()`. This is the ready-made one.

The Better Messages conversation, on any room: your server conversation paged back as the reader scrolls up, the room filling in what came since, the day separators, the messages of a sender stacked, typing, reactions, the read ticks and the composer. It is one element:

```html
<chat-room room="chat:{{ chat.a }}:{{ chat.b }}" messages="/chat/{{ chat.a }}/{{ chat.b }}/messages" placeholder="Write a message"></chat-room>
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

## Use cases

Each with the rules of your server and the code of the page:

- [Chat](https://docs.wordplus.cloud/use-cases/chat/): conversations of two and of a group, kept by your server
- [Editing together](https://docs.wordplus.cloud/use-cases/collaboration/): cursors as volatile events, and changes kept for a page that reconnects

More, with Node and PHP side by side: [events in depth](https://docs.wordplus.cloud/apps/events/).
