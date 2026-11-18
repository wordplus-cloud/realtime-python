# Python reference: `wordplus-realtime`

The package needs Python 3.9 or later, with PyNaCl. It takes the same options as the Node and PHP packages, and answers the browser the same way. The guides: [Django](django/getting-started.md), [FastAPI](fastapi/getting-started.md) and [Flask](flask/getting-started.md).

## `Realtime( app, secret, local_key, **options )`

`Realtime.from_environment( **options )` is the same, with `app`, `secret` and `local_key` taken from `WORDPLUS_SITE`, `WORDPLUS_SECRET` and `WORDPLUS_LOCAL_KEY`.

| Option | |
|---|---|
| `app`, `secret` | your app key and secret. `site=` is the same as `app` in its old word |
| `local_key` | 64 hex characters of your own ([encryption](https://docs.wordplus.cloud/apps/encryption/#your-local-key)) |
| `profile` | `lambda user: {"name": …, "avatar": …, "url": …}` or `None`: the user directory entry, and by default their presence info and call info |
| `hidden` | `lambda user: True` for a user never shown online |
| `has_keys` | `lambda user: False` cuts a user off every key |
| `generations` | a `GenerationStore`, for `remove()`, `rotate_room()` and `rotate_user()` |
| `seal` | `False` sends everything plain |
| `base` | where your routes are, `/api/realtime` by default, for `config()` |
| `routes` | a route at an address of its own, in place of `{base}/{name}`: `{"calls": "/check-call"}`. Then include the Django URLs at the root, and the FastAPI router with no prefix |
| `headers` | headers the browser sends to your routes, such as a CSRF token, for `config()` |
| `files` | `False` when your app serves the browser files itself: `file()` then answers nothing, and `config()` names only the `worker` and `rooms` you give |
| `worker`, `rooms` | where your app serves the worker and the room client itself, for `config()`: from the routes by default |
| `rooms_worker` | where it serves the room client encryption worker, beside `rooms` by default |
| `token_ttl`, `call_token_ttl` | seconds: 6 hours by default. A room token lasts at most a day, a call token at most 6 hours |
| `server`, `api` | WordPlus Cloud by default |
| `http` | `(method, url, headers, body) -> (status, body)`, your own client for sending |

A user is the id your app gives, an integer or a string, or `None` for nobody. Calls take any of them: an id of digits as a number, and any other id of up to 64 characters with no space as it is.

## Tokens

Who may call, join or watch is your app's own logic, in a route of your own. These sign what your route decided and check nothing else, so check first ([who may call](https://docs.wordplus.cloud/apps/calls/#who-may-call)). Each answers a string for the page.

| Method | |
|---|---|
| `call_token(user, to, type="video", name=None, info=None, into=None)` | for `rt.startCall()`: `user` calls `to`, two different users. `type` is `audio`, or `video` for anything else. `name` is a name of your own for the call, which `call.ended` and the other webhooks give back, `call:` and a random id by default. `info` is what the person called sees of the caller, your `profile` by default. It rings once, within `call_token_ttl`. The person called needs no token. With `into`, the `call.ref` the page sent, it is for `call.add()` and rings `to` into that call |
| `group_call_token(user, name, type="video", publish=True, subscribe=True, admin=False, hidden=False, encrypt=False, info=None)` | for `rt.joinGroupCall()`: `user` joins the group call `name`, which starts as the first person joins. `admin` hosts it. `hidden` is listed to nobody. `encrypt` encrypts its media end to end, the same in every token for the call. `info` is what the others see, your `profile` by default ([group calls](https://docs.wordplus.cloud/apps/calls/#group-calls)) |
| `stream_token(user, name, role="viewer", info=None, chat=None, mod=None, src=None, quality=None, settings=None)` | for `rt.joinStream()`: `user`, or `None` for a visitor, who can only be a viewer, joins the live stream `name`. `role` is `viewer` by default, or `host`. `chat` is `write` or `read`. `mod` keeps the chat. `src` is what a host or guest may send, and `quality` the best picture they send. `settings` is `{"stage", "reactions", "people", "chat": {"offline", "links", "fresh"}}`, the same in every token for it. It lasts ten minutes ([live streams](https://docs.wordplus.cloud/apps/streams/#who-is-who)) |

They raise `ValueError` for what they cannot sign: a user id calls do not take, calling oneself, a name a call or a stream cannot have, an `into` of a call this user is not in, or a visitor given more than a viewer's place.

## Rules

| Method | |
|---|---|
| `room(pattern, rule=None, *, presence, count, history, emit, webhook, public, seal)` | rooms by pattern (`order:{id}`): `rule(user, params, room)` answers `False`, `True`, or `{"info": …, "emit": …, "readOnly": …}`. `history` is a number or `{"last", "seconds"}`, `emit` and `webhook` names or `"*"`. A public room may have no rule ([rooms](https://docs.wordplus.cloud/apps/rooms/)). `chat:{pair}` is a room of the two people its name holds, `chat:34:42`, and nobody else: it needs no rule, and a rule it has is asked only about those two, with `other` in `params`. A public room takes no `{pair}` |
| `kind(kind, lambda rest, user, label: bool, newest=None)` | keys of your own kind ([encryption](https://docs.wordplus.cloud/apps/encryption/#your-own-sealed-values)) |
| `fallback(rule, options=None)` | the rooms no pattern owns, and what they are |
| `on(type, handler)` | the events of a [webhook](https://docs.wordplus.cloud/apps/sending/#webhooks): the name of a browser event, `room.occupied`, `room.vacated`, `member.joined`, `member.left`, `user.online`, `user.offline`, `stream.live`, `stream.ended`, `call.ended`, `group.joined`, `group.left`, `stream.joined`, `stream.left`, `webhook.test`, or `"*"` |

`{name}` matches one or more characters other than `:` and `.`. The pattern with the most characters of its own decides, and on a tie the one declared first. Each rule is called with as many of its arguments as it takes, so `lambda user: …` works. The rules are plain functions, not `async`. Each method returns the instance, so calls chain.

**Apps with call rules:** `calls(pattern, rule, people=None)`, `group_calls(pattern, rule, encrypt=False)` and `streams(pattern, rule, stage=, reactions=, people=, chat=)` keep working, for pages on `rt.call()`, `rt.groupCall()` and `rt.stream()`. A `calls()` rule that owns the name of a call is still asked as someone answers it, and a `group_calls()` rule still decides a host's acts. `people(user, call)` answers the user ids the call screen's Add Person lists, each still asked of the rule. On the package's calls route, a call, a group call or a stream no rule owns is refused `forbidden`.

## Routes

| Method | |
|---|---|
| `answer_request(method, content_type, action, body, user)` | → `(status, body)`: one route, `auth`, `calls` or `keys`, for the raw body of a request |
| `address(name)`, `route_of(path)` | where a route is, and which route a path asks for (`None` for none) |
| `webhook(raw, headers, path)` | → `(status, body)`: the webhook request checked, and its events handed to the handlers of `on()` |
| `file(method, path, if_none_match=None)`, `file_named(method, version, name, if_none_match=None)` | → `(status, headers, body)` for a browser file, or `None` (`file()`) for any other request, for a framework of your own |
| `file_at(name)` | where the routes serve a browser file, in the folder of this version: `realtime.js`, `realtime-worker.js`, `realtime-rooms.min.js` … |
| `handle(action, body, user)` | → `(status, body)`, for a body already decoded |
| `wordplus_realtime.django` | the app for `INSTALLED_APPS`: `realtime`, made from `WORDPLUS_REALTIME`, `include("wordplus_realtime.django.routes")`, `urls(realtime, user=…)` for a Realtime of your own, and `{% wordplus_realtime %}` ([Django](django/getting-started.md)) |
| `wordplus_realtime.fastapi.router(realtime, user)` | the routes, the webhook and the browser files in FastAPI and Starlette ([FastAPI](fastapi/getting-started.md)) |
| `wordplus_realtime.flask.init_app(app, realtime, user=…)` | the routes, the webhook and the browser files in Flask, and `wordplus_realtime()` for the templates ([Flask](flask/getting-started.md)) |

The routes take JSON POSTs, and GETs for the browser files alone: another method gets `405`, and a body that is not JSON `415`. A refusal is part of the answer (`denied`), not an HTTP error.

| Method | What it answers |
|---|---|
| `authorize(rooms, user)` | `{"token", "exp", "keys", "denied"}` |
| `authorize_call(request, user)` | what the package's calls route answers: the page's line, the answer to a call, a renewal, each on the proofs only your server makes. `{"token", "exp", "key", "media_key", "pair", "member", "ring"?}` for a call, `{"token", "exp", "media_key"?}` for a group call by name, `{"token", "exp"}` for a live stream by name, `{"people"}`, `{"may"}` (whom the user may call, as `<online-list call>` asks), `{"done"}` (an act of a host), or `{"denied": …}` |
| `keys_answer(labels, user)` | `{"keys", "identity"?}` |
| `identity(user)` | `{"token", "exp"}` or `None` |
| `public_grants()` | the grants of the rooms declared `public`, which `config()` puts in every page |
| `config(user=None, headers=None)` | the browser settings for `connect()`, with a signed-in user keys and identity |
| `head(user=None, headers=None, importmap=True)` | the settings as a page `<head>` takes them, `window.wordplusRealtimeConfig`, with an import map naming `@wordplus/realtime` the client the routes serve |
| `may_join(room, user)`, `may_have(label, user)` | what the routes decide, for your own checks |

## Sending

| Method | |
|---|---|
| `to(rooms).except_tab(tab).emit(event, data=None, *, seal=True)` | to one room or up to 1,000. Data up to 1 MB. The kept event ids, by room ([sending](https://docs.wordplus.cloud/apps/sending/)) |
| `await … .aemit(…)` | the same from async code, on a worker thread |
| `aio` | all of this from async code, each request on a worker thread: `await realtime.aio.room("chat:7").members()`, `await realtime.aio.to("order:42").emit("updated", data)`, `await realtime.aio.online.count()` |
| `to_user(users).emit(event, data)` | to every tab and device of one user or up to 1,000, sealed with the key of each. Chains with `to()` |
| `to_everyone().except_tab(tab).emit(event, data)` | to every page and app connected now, signed in or not, never sealed or kept |
| `batch([{"rooms", "users", "everyone", "event", "data", "except", "seal"}, …])` | several events, each sent as its own emit, one after another: any number. The kept ids, by room, for each |
| `room(name)` | one room, by its name alone: `.emit(event, data, seal=True, except_tab=None)`, `.count()`, `.members()` → `{"count", "list"}` (the first 1,000 members of a presence room, their info opened), `.history(before=, after=, limit=, days=)`, `.forget(event_id=None)`, `.remove(user)`, `.remove_everyone()`, `.recheck(user)`, `.recheck_everyone()`. `in_room(room)` and `.kick(user)` are their old names, and still work |
| `online` | a property: `.has(user)`, `.states(users)`, `.count()`, `.list(cursor, limit)`, as in `realtime.online.has(42)` |
| `list_rooms(prefix=, cursor=, limit=)` | `{"count", "rooms": [{"name", "count", "connections"}], "next"?}`: the rooms someone is in now ([sending](https://docs.wordplus.cloud/apps/sending/#the-rooms-in-use)) |
| `user(id)` | one user: `.emit(event, data, seal=True, except_tab=None)`, as `to_user(id)` sends it, `.get()`, `.disconnect()`, `.ask(event, data, timeout=, all=, seal=)`: their state, out of everything at once, and their pages asked, `timeout` 1,000 to 60,000 ms, 10,000 by default ([a user](https://docs.wordplus.cloud/apps/sending/#a-user)) |
| `await … .aask(…)` | `ask()` from async code, on a worker thread, as `aemit()`: in an async route, the wait for the pages never holds the event loop |
| `usage()` | `{"connections": {"now", "limit"}, "credits"}` ([what your app uses](https://docs.wordplus.cloud/apps/sending/#what-your-app-uses)) |
| `webhooks` | a property: `.deliveries()`, the last 100 tries. `.resend(batch_id)` → `{"delivered", "status", "error"?}`. `.test()` → the same: one `webhook.test` event sent now, which `on("webhook.test", …)` hears ([deliveries](https://docs.wordplus.cloud/apps/sending/#deliveries-a-resend-and-a-test)) |
| `list_calls()`, `call(name)` | the group calls going on, and `.get()`, `.mute(user, track="microphone")` (or `camera` or `screen`, → whether it was on), `.let_speak(user)` and `.make_listener(user)` (→ whether they were in it), `.remove(user)` (→ whether they were in it), `.spotlight_on(user)` and `.spotlight_off(user=None)` (on the main tiles for everyone, up to four, off for them, or for everyone with no user, → whether it changed anything), `.end()`, the words a host has on the page. `.permit(user, publish=None, subscribe=None)` changes either, `subscribe` stopping or starting what they get of the others, and `.spotlight(user, on)` is the last two in one ([calls](https://docs.wordplus.cloud/apps/calls/#from-your-server)). What the call holds until it ends, as a host does on the page: `.mute(user, "microphone", hold=True)` and `.unmute(user)` (Mute and Allow Microphone), `.permit(user, publish=…, hold=True)` (Make Listener and its promotion), `.ban(user, minutes=None)` (→ `{"removed", "until"}`, until the call ends with no minutes, at most a week), `.unban(user)` and `.bans()`, `.rules(mode=…, locked=…, muted=…)` (→ the rules now, until everyone has left), `.hand(user, up)` and `.lower_hands()`, and `.ask(user, devices, by)`, which keeps nothing. Each takes `by`, the host acted for, named in the `call.moderated` webhook ([moderating a group call](https://docs.wordplus.cloud/apps/calls/#moderating-a-group-call)) |
| `list_streams()`, `stream(name)` | the streams live now, and `.get()`, `.people()`, `.chat(limit)`, `.say(text, name, avatar)`, `.delete_message(id)`, `.clear_chat()`, `.pin(id)`, `.slow(seconds)`, `.timeout(user, seconds)`, `.untimeout(user)`, `.remove(user)` (`.kick(user)` is the same), `.ban(user)`, `.unban(user)`, `.bans()`, `.reactions(on)`, `.end()` ([live streams](https://docs.wordplus.cloud/apps/streams/#from-your-server)) |
| `rotate_room(room)`, `rotate_user(user)` | moves a key on. Needs `generations` |

They raise `RealtimeError` when WordPlus Cloud refuses: `e.code` holds the [code](https://docs.wordplus.cloud/apps/errors/), and `e.status` the HTTP status.

## Keys

`realtime.keys` is the app `Keys`: `seal(text, label)`, `seal_json(data, label)`, `open(value)`, `entry(label)`, `day_label()`, `room_label(room)`, `user_label(user)`.

## Generations

```python
class GenerationStore(Protocol):
    def get(self, name: str) -> Optional[int]: ...
    def set(self, name: str, generation: int) -> None: ...
```

Keep them where all your servers see them, and for good: a database row, or a cache that does not evict.

## Helpers

`valid_room(name)` says whether WordPlus Cloud takes the name of a room, and `valid_pattern(pattern)` a pattern. `label_of(value)` names the key a sealed value needs. All three come from `wordplus_realtime`.
