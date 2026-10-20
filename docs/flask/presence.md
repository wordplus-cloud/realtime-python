# Presence in Flask

Three ways to show people: a presence room lists who is in it to everyone in it (who is in the shop, who is viewing a document). A count says how many, at any size. And who is online is known across your whole app, for a dot on every avatar.

![The browsers of Ann, Ben and Cara, each listing the three of them in the shop now, with their roles from the info of each member](https://docs.wordplus.cloud/img/apps/presence-shop.webp)

## A presence room

```python
# Who is in the shop: everyone signed in, with their name and role.
def in_the_shop(user):
    person = find_person(user) if user is not None else None
    return {"info": {"name": person.name, "role": person.role}} if person else False

realtime.room("shop", in_the_shop, presence=True)
```

- **`info`** is what the others see of the member: a name, a role, anything small (up to 4 KB). It is sealed with the room key.
- **`True`** lets them in with your profile ([your users](encryption.md#your-users)).
- **Up to 1,000 members** are listed in full, with `join` and `leave`. Past that, the room counts them, and `members()` pages through them, up to 100,000.

```js
const shop = rt.join( 'shop' );
const draw = () => list( [ ...shop.members ] );        // [ [ id, info ], … ]
shop.on( 'joined', draw );                             // the members as the page joins
shop.on( 'join', ( { id, info } ) => draw() );
shop.on( 'leave', ( { id } ) => draw() );
```

A user is a member once, however many tabs and devices they have in the room, and leaves when the last one does.

## Counting

`count=True` gives a room a live count, without a list:

```python
realtime.room("product:{id}", public=True, count=True)
```

```js
const product = rt.join( 'product:7' );
product.on( 'count', ( n ) => showLooking( n ) );   // at most once a second
```

A presence room counts too.

## Who is online, across your app

Every page whose user your server vouched for makes that user online. They go offline 10 seconds after their last page closes, so a reload does not flicker.

```js
rt.online.watch( [ 34, 43 ] ).on( 'change', ( { id, online, at } ) => dot( id, online ) );
rt.online.has( 34 );          // true or false, for a user watched
rt.online.lastSeen( 43 );     // when, in ms, for one offline
rt.online.on( 'count', ( n ) => showOnline( n ) );
```

- **A page watches** up to 1,000 users, and gets their status now and every change.
- **Your server asks too:** `realtime.online().has(42)`, `.count()`, `.list()`.
- **Hiding:** a user who chose not to show their status is never online to anyone:

```python
realtime = Realtime.from_environment(
    # …
    hidden=lambda user: find_person(user).hide_status,
)
```

## Ready-made: who is online

Optional, as every ready-made part: the presence room above is all a list needs, drawn your way ([your own interface](https://docs.wordplus.cloud/apps/interface/#who-is-in-a-room)). This is the ready-made one.

The Better Messages list of members, on a presence room, with a call button for each of the others. It is one element:

```html
<online-list room="shop" title="In the shop now" call="support:{pair}" type="video"></online-list>
<online-count room="product:7"></online-count>
```

```js
await rt.callScreen();   // loads the elements and the call screen, rt.ui() the elements without calls
```

- **`call`** names the call the button of each row places: `{pair}` is the two user ids in order (`support:34:42`), `{me}` and `{id}` each one. Without it, the rows have no button.
- **Only those the user may call** get a button: the list asks your calls route once for all its members, which runs your `calls()` rule for each as for the caller. Nothing to add on your server.
- **Names and pictures** come from the member info, then from your [directory](encryption.md#your-users).
- **Its look** is that of Better Messages, in a shadow root: your styles do not reach in, and its colours are CSS custom properties your page sets.

More, with Node and PHP side by side: [presence in depth](https://docs.wordplus.cloud/apps/presence/).
