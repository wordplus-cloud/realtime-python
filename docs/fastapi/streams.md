# Live streams in FastAPI

One person presents live to everyone watching: the picture, a chat beside it, reactions, and the count of who watches. The host goes live from the browser, a phone or OBS. Viewers may be signed in or not.

## Who is who

Your server declares streams beside its rooms and calls, by pattern. The rule says who each person is in the stream:

```python
# app.py: the show of the shop, show:mugs. Ann presents it, and everyone else watches and writes in its chat, signed in or not.
def show_role(user, p):
    if p["id"] != "mugs":
        return False
    return "host" if user == ANN else "viewer"

realtime.streams("show:{id}", show_role, reactions=True)
```

- **The answer:** `False`, `"host"` or `"viewer"`, or a dict: `role`, `info` (what others see of them), `chat` (`write` or `read`), `mod` (keeps the chat), `src` and `quality` (what the host sends).
- **A visitor who is not signed in** comes with `user` None, and may only be a viewer.
- **The settings of the stream**, keyword arguments: `reactions`, `people` and `chat` (`offline`, `links`, `fresh`), each a value or a function of the parts of the name ([live streams in depth](https://docs.wordplus.cloud/apps/streams/#who-is-who)).

The calls route (`/api/realtime/calls`) is already among the answers of `wr.router()`, for streams too.

Your server hears each stream go live and end by [webhook](sending.md#webhooks): `stream.live` and `stream.ended`, with its name in `stream`, and `started_at` and `ended_at` in milliseconds.

## The page

Optional, as every ready-made part: [a screen of your own](#a-screen-of-your-own) below draws the stream with no element.

The stream drawn ready: its player with the chat beside it, and the studio where the host goes live.

```html
<live-stream name="show:mugs" title="The new mugs"></live-stream>
```

```js
await rt.streamScreen();    // loads its script, realtime-ui-streams.min.js, once
```

- **The host** sees the studio in it: the camera and microphone, the picture before going live, Go live and End stream. Everyone else sees the player, how many watch, and the chat.
- **Its parts apart**, each where the page wants it: `view="player"`, `chat` (with `height="480"`), `details` or `studio`. The parts of one stream share it.
- **Its attributes:** `title`, `cover`, `url` (the page to share), `login-url` (where a visitor signs in to chat) and `chat="off"`.
- **Its script** comes from the routes with the others, and loads with the first stream on a page.

The show card of the API demo is this element, in `showCard()` of its page.

## A screen of your own

The same stream on markup of your own, with `calls.stream()`:

```js
const calls = await rt.calls();
const show = await calls.stream( 'show:mugs' );

show.watch( document.querySelector( '#show video' ) );      // the picture and its sound
show.on( 'state', ( state ) => draw( state ) );            // idle, live, ended
show.on( 'viewers', ( n ) => ( count.textContent = `${ n } watching` ) );
show.on( 'message', ( m ) => addLine( m.from.name, m.text ) );
await show.chat.send( 'Hello!' );

if ( show.role === 'host' ) {
    await show.preview();    // the camera, shown in the same video
    await show.goLive();
}
```

## More

Reactions, keeping the chat, OBS, and the refusals: [live streams in depth](https://docs.wordplus.cloud/apps/streams/).
