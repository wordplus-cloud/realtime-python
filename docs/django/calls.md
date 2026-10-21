# Calls in Django

Calls between two people that ring in every tab and device the callee has open, group calls on the WordPlus Cloud media servers, and the Better Messages call screen: the buttons, the ring and the call window, with no call code. The media of a call is encrypted end to end, with keys your server gives out.

![Ben has pressed a video call button: his browser shows the call window calling Ann, over his own camera, and the browser of Ann rings, with buttons to answer and decline](https://docs.wordplus.cloud/img/apps/calls-ringing.webp)

## Who may call

Your server declares calls as it declares rooms, by pattern:

```python
# shop/realtime.py: calls between two people, support:34:42, the two it names, one of them staff.
def may_call(user, with_user, p):
    pair = [p["a"], p["b"]]  # the two ids in the name, as text
    return str(user) in pair and str(with_user) in pair and (is_staff(user) or is_staff(with_user))

realtime.calls("support:{a}:{b}", may_call)

# Pro members call anyone, pro:42:7, and anyone answers: call and side, the fourth and fifth arguments, say which side asks.
def may_call_pro(user, with_user, p, call, side):
    pair = [p["a"], p["b"]]
    if str(user) not in pair or str(with_user) not in pair:
        return False
    return side["role"] == "callee" or is_pro(user)

realtime.calls("pro:{a}:{b}", may_call_pro)

# The daily meeting: a group call for everyone signed in.
realtime.group_calls("meeting:{id}", lambda user: user is not None)
```

- **`with_user`** is the other person: whom `user` calls, or who calls `user`. Your server is asked again when the callee answers, with the callee as `user`.
- **`call` and `side`**, the fourth and fifth arguments when the rule takes them, are the call name (`pro:42:7`) and which side asks: `side["role"]` is `caller` or `callee`. A rule that says yes to every callee and checks only callers lets people answer calls they may not place.
- **The answer:** `False`, `True`, or a dict: `info` (what the others see of `user`: your `profile` by default), and in a group call `publish`, `subscribe`, `admin` and `hidden`. `admin` makes them its host: the call screen gives them mute, let speak or make a listener, and remove on the tile of each of the others, which your calls route takes only from a host ([permissions](https://docs.wordplus.cloud/apps/permissions/#group-calls)).
- **The rooms of a group call** can be encrypted end to end too: `realtime.group_calls("meeting:{id}", rule, encrypt=True)`. The rooms that come from a call always are.
- **User ids** are yours: a number, or text such as `user_2abc` or `auth0|5f7c`, up to 64 characters with no space. A rule gets an id of digits as a number and any other as text, so compare them with the name as text. An id calls cannot take is refused with `no_user`.

The calls route (`/api/realtime/calls`) is already among `wr.urls()`.

## The call screen

Optional, as every ready-made part: [your own call interface](#your-own-call-interface) below places, answers and draws calls with no element, and [your own interface](https://docs.wordplus.cloud/apps/interface/#calls) has the whole of it.

Start it on every page where a call may ring, and put buttons where people call from:

```js
await rt.callScreen();   // the ring and the call window, on this page
```

```html
<call-button to="{{ agent.pk }}" call="support:{pair}" type="video" name="{{ agent.get_full_name }}">Call {{ agent.first_name }}</call-button>
<room-button room="meeting:daily" type="video" title="Daily meeting">Join the meeting</room-button>
```

- **`{pair}`** in `call` is filled in with the page user and the one called, in order, so whichever of the two calls names the same call: `support:34:42`.
- **A list with call buttons:** `<online-list room="shop" call="support:{pair}">` puts one on the row of every member ([presence](presence.md#ready-made-who-is-online)).
- **Its words** come in English, German, Spanish, French, Italian, Dutch, Polish, Croatian and Hebrew, by the page `<html lang="{{ LANGUAGE_CODE }}">`. `rt.callScreen( { strings: { … } } )` changes any of them.
- **Its look** is that of Better Messages, in a shadow root: your styles do not reach in, and its colours are CSS custom properties your page sets.
- **Group calls** load the room client and its encryption worker from the routes, which the page settings name: nothing to add.

![Ann has answered: each browser shows the other person camera, their own in a corner, and the call controls. The cameras are illustrations](https://docs.wordplus.cloud/img/apps/calls-connected.webp)

## The call in the page

The call screen opens a call in a window in the corner, over the page. To show it in the page itself, above a chat or in place of a picture, put a `<call-spot>` where it goes, naming the calls it takes:

```html
<call-spot call="support:{a}:{b}" style="height: 480px"></call-spot>
```

A call shows there as it starts, or as soon as a page with the spot opens. On another page it goes on in the window in the corner, its camera, microphone and time as they were, and comes back when the page with the spot opens again. With no call, the spot takes no place, or shows what you put inside it ([`<call-spot>`](https://docs.wordplus.cloud/apps/elements/#call-spot)).

## The call in its chat

A conversation between two can hold its own call instead: the other person on the chat's top bar with a video and an audio call button, and their call in the chat itself while it is on, beside the messages. Give the chat the other person, with their name and picture as your page has them, and `call`, the call named as the room, which your calls rule for `chat:{a}:{b}` decides:

```html
<chat-room room="chat:34:42" to="42" name="Ben" avatar="/photos/42.jpg" call style="height: 560px"></chat-room>
```

Narrower than 600px, the call takes the whole chat, and Show Chat in its controls puts the messages under it. `start-call="video"` calls them once as the chat opens, for a Video button elsewhere that links to the chat ([`<chat-room>`](https://docs.wordplus.cloud/apps/elements/#chat-room)).

## Adding people

Once a call is up, either side may ring someone else in, and it goes on as a group call. Say whom the call screen offers:

```python
# The staff not in the call, each still asked of may_call.
def staff_to_add(user, call):
    return list(User.objects.filter(is_staff=True).exclude(pk__in=call.split(":")[1:]).values_list("pk", flat=True))

realtime.calls("support:{a}:{b}", may_call, people=staff_to_add)
```

The screen then shows an Add person button, listing them with the names and pictures from your `profile`.

## Your own call interface

The call screen is built on this, and nothing else:

```js
const calls = await rt.calls();

const call = await calls.start( 'support:34:42', { to: 34, type: 'video' } );
call.on( 'state', ( state ) => show( state ) );   // ringing, connecting, connected, reconnecting, ended
call.on( 'remote', () => call.remote.camera?.attach( video ) );

calls.on( 'incoming', async ( incoming ) => {
    const answered = await incoming.accept();     // the call, or the group call it rings into. Or incoming.decline( 'busy' )
} );

const meeting = await calls.group( 'meeting:daily', { type: 'video' } );
meeting.on( 'person', ( person ) => person.camera?.attach( tileFor( person ) ) );
```

![Ann, Ben and Cara in one group call from three browsers, with the call screen grid: each sees the other two and their own camera, then the call controls. The cameras are illustrations](https://docs.wordplus.cloud/img/apps/rooms-meeting.webp)

## From your server

Your server sees the group calls going on and runs them, with no page open:

```python
realtime.list_calls()                     # [{"name", "people", "started_at"}]
call = realtime.call("meeting:daily")
call.get()                                # {"people", "started_at", "list": [{"user", "joined_at", "camera", "microphone", "screen"}]}
call.permit(43, publish=True)             # a listener let speak, publish=False back to listening
call.mute(43, "microphone")               # "camera" or "screen" too: they may turn it on again
call.remove(43)                           # out now, their tokens from before refused
call.end()                                # out, everyone
```

- **A host's buttons** are on the call screen already, for whom the rule answers `admin`: mute, let speak or make a listener, and remove. Buttons of your own call a route of yours that checks who asks, then these. A rule that answers `{"publish": False}` makes a listener, whom `permit()` lets speak while the call runs.
- **`get()`** with nobody in the call answers `people` 0, `started_at` None and an empty list. `started_at` is when this call began: one named again after everyone left begins again.

Every event, why a call ended, and what WordPlus Cloud sees: [calls in depth](https://docs.wordplus.cloud/apps/calls/).
