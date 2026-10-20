# Python reference: `wordplus-realtime`

The package needs Python 3.9 or later, with PyNaCl. It takes the same options as the Node and PHP packages, and answers the browser the same way. The guides: [Django](django/getting-started.md), [FastAPI](fastapi/getting-started.md) and [Flask](flask/getting-started.md).

## `Realtime( site, secret, local_key, **options )`

`Realtime.from_environment( **options )` is the same, with `site`, `secret` and `local_key` taken from `WORDPLUS_SITE`, `WORDPLUS_SECRET` and `WORDPLUS_LOCAL_KEY`.

| Option | |
|---|---|
| `site`, `secret` | your app key and secret |
| `local_key` | 64 hex characters of your own ([encryption](https://docs.wordplus.cloud/apps/encryption/#your-local-key)) |
| `profile` | `lambda user: {"name": …, "avatar": …, "url": …}` or `None`: the user directory entry, and by default their presence info and call info |
| `hidden` | `lambda user: True` for a user never shown online |
| `has_keys` | `lambda user: False` cuts a user off every key |
| `generations` | a `GenerationStore`, for `kick()`, `rotate_room()` and `rotate_user()` |
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

## Rules

| Method | |
|---|---|
| `room(pattern, rule=None, *, presence, count, history, emit, webhook, public, seal)` | rooms by pattern (`order:{id}`): `rule(user, params, room)` answers `False`, `True`, or `{"info": …, "emit": …, "readOnly": …}`. `history` is a number or `{"last", "days"}`, `emit` and `webhook` names or `"*"`. A public room may have no rule ([rooms](https://docs.wordplus.cloud/apps/rooms/)) |
| `calls(pattern, rule, *, people=None)` | calls between two people: `rule(user, with_user, params, call, side)`, `side["role"]` `"caller"` or `"callee"`, answers `False`, `True`, or `{"info", "publish", "subscribe", "admin", "hidden"}`. `people(user, call)` answers the user ids the call screen offers to add ([calls](https://docs.wordplus.cloud/apps/calls/)) |
| `group_calls(pattern, rule, *, encrypt=False)` | group calls: `rule(user, params, name)`. `encrypt` encrypts their rooms end to end |
| `streams(pattern, rule, *, reactions=None, people=None, chat=None)` | live streams: `rule(user, params, name)` answers `False`, a role (`host`, `viewer`), or a dict (`role`, `info`, `chat`, `mod`, `src`, `quality`). A visitor (`user` None) is a viewer at most. The settings are each a value or a function of the parts of the name ([live streams](https://docs.wordplus.cloud/apps/streams/#who-is-who)) |
| `kind(kind, lambda rest, user, label: bool, newest=None)` | keys of your own kind ([encryption](https://docs.wordplus.cloud/apps/encryption/#your-own-sealed-values)) |
| `fallback(rule, options=None)` | the rooms no pattern owns, and what they are |
| `on(type, handler)` | the events of a [webhook](https://docs.wordplus.cloud/apps/sending/#webhooks): the name of a browser event, `room.occupied`, `room.vacated`, `member.joined`, `member.left`, `user.online`, `user.offline`, `stream.live`, `stream.ended`, `call.ended`, `group.joined`, `group.left`, `stream.joined`, `stream.left`, or `"*"` |

`{name}` matches one or more characters other than `:` and `.`. The pattern with the most characters of its own decides, and on a tie the one declared first. Each rule is called with as many of its arguments as it takes, so `lambda user: …` works. The rules are plain functions, not `async`. Each method returns the instance, so calls chain.

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

The routes take JSON POSTs, and GETs for the browser files alone, and answer anything else with `415`. A refusal is part of the answer (`denied`), not an HTTP error.

| Method | What it answers |
|---|---|
| `authorize(rooms, user)` | `{"token", "exp", "keys", "denied"}` |
| `authorize_call(request, user)` | `{"token", "exp", "key", "media_key", "pair", "member", "ring"?}` for a call, `{"token", "exp", "media_key"?}` for a group call, `{"people"}`, `{"may"}` (whom the user may call, as the online list asks), or `{"denied": …}` |
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
| `to_user(users).emit(event, data)` | to every tab and device of one user or up to 1,000, sealed with the key of each. Chains with `to()` |
| `batch([{"rooms", "users", "event", "data", "except", "seal"}, …])` | 100 events a request |
| `in_room(room)` | `.count()`, `.members()` (of a presence room, their info opened), `.history(before=, after=, limit=, days=)`, `.forget(event_id=None)`, `.kick(user)` |
| `online` | `.has(user)`, `.states(users)`, `.count()`, `.list(cursor, limit)` |
| `list_rooms(prefix=, cursor=, limit=)` | `{"count", "rooms": [{"name", "count", "connections"}], "next"?}`: the rooms someone is in now ([sending](https://docs.wordplus.cloud/apps/sending/#the-rooms-in-use)) |
| `user(id)` | `.get()`, `.disconnect()`, `.ask(event, data, timeout=, all=, seal=)`: their state, out of everything at once, and their pages asked ([a user](https://docs.wordplus.cloud/apps/sending/#a-user)) |
| `usage()` | `{"connections": {"now", "limit"}, "credits"}` ([what your app uses](https://docs.wordplus.cloud/apps/sending/#what-your-app-uses)) |
| `webhooks` | `.deliveries()`, `.resend(batch_id)`, `.test()` ([deliveries](https://docs.wordplus.cloud/apps/sending/#deliveries-a-resend-and-a-test)) |
| `list_calls()`, `call(name)` | the group calls going on, and `.get()`, `.mute(user, track)`, `.permit(user, publish=True)`, `.remove(user)`, `.end()` ([calls](https://docs.wordplus.cloud/apps/calls/#from-your-server)) |
| `list_streams()`, `stream(name)` | the streams live now, and `.get()`, `.people()`, `.chat(limit)`, `.say(text, name, avatar)`, `.delete_message(id)`, `.clear_chat()`, `.pin(id)`, `.slow(seconds)`, `.timeout(user, seconds)`, `.untimeout(user)`, `.kick(user)`, `.ban(user)`, `.unban(user)`, `.bans()`, `.reactions(on)`, `.end()` ([live streams](https://docs.wordplus.cloud/apps/streams/#from-your-server)) |
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
