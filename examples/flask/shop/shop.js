// The API demo page: the same in every example, whatever its server speaks. The server renders two JSON blocks
// into the page and this module does the rest:
//
//   <script type="application/json" id="realtime">  the server config() for the signed-in user (in Laravel
//                                                    @wordplusRealtime writes window.wordplusRealtimeConfig instead)
//   <script type="application/json" id="shop">      who is signed in, the people, the order, the product, the chat with its
//                                                    two people, and the server routes, rooms and event names
//
// What it shows: the order of Ben moving on (a room the server emits to, with a notice to Ben himself), its timeline from
// the room history, and what the cloud carried of it, sealed. The product with a live count of who is looking (a
// public room), the chat of Ann and Ben (the Better Messages conversation on a room, <chat-room>: messages emitted from the
// browser with an ack, which the server keeps from its webhook and the chat pages through, typing and read ticks as
// volatile events, reactions. The name and picture of the other side from the directory), the shop members, a private call
// to each (<call-button>), who is in the shop (a presence room, <online-list>, with a call button for each, and who
// is online across the shop), the webhooks the server got. The live show of the new mugs (a live stream,
// <live-stream>). And the daily meeting (a group call), with the call screen. The elements come from
// @wordplus/realtime-ui, which rt.callScreen() and rt.streamScreen() load.
//
// On a demo site, the server adds `demo` to the shop data: this window person (a token it sends with every
// request), links that open the other people of the shop in windows of their own (or turn this window into theirs, from the
// top bar), the other stacks, and "Try this".
import { connect } from '@wordplus/realtime';

const shop = JSON.parse(document.getElementById('shop').textContent);
const config = window.wordplusRealtimeConfig ?? JSON.parse(document.getElementById('realtime').textContent);
const root = document.getElementById('shop-root');
const demo = shop.demo ?? null;

const STEPS = ['placed', 'packed', 'shipped', 'delivered'];
const LABELS = { placed: 'Placed', packed: 'Packed', shipped: 'Shipped', delivered: 'Delivered' };
const me = shop.me;
const person = (id) => shop.people.find((p) => String(p.id) === String(id));
const named = (local) => shop.people.find((p) => p.id % 100 === local);
// Times in the page language, as its words are.
const LANG = document.documentElement.lang || 'en';
const when = (at) => new Date(at).toLocaleTimeString(LANG, { hour: '2-digit', minute: '2-digit', second: '2-digit' });

/** An element of the shop page with its attributes and children, as the page is plain DOM. */
function h(tag, attributes = {}, ...children) {
    const el = document.createElement(tag);
    for (const [name, value] of Object.entries(attributes)) {
        if (name.startsWith('on')) el.addEventListener(name.slice(2), value);
        else if (value !== false && value != null) el.setAttribute(name, value === true ? '' : value);
    }
    el.append(...children.flat().filter((c) => c != null && c !== false));
    return el;
}

/**
 * A WordPlus element written as the HTML it is, each value put in as text:
 * html`<chat-room room="${room}"></chat-room>`. In a page your server renders, write the same HTML there.
 */
function html(strings, ...values) {
    const template = document.createElement('template');
    template.innerHTML = strings.reduce((out, part, i) => out + escapeHtml(values[i - 1]) + part);
    return template.content.firstElementChild;
}
const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

// A demo window is the person its token names, sent with each request to the server. The cookie is that of the browser.
const headers = { ...shop.headers };
if (demo) {
    headers.Authorization = 'Bearer ' + demo.token;
    for (const route of [config.auth, config.calls, config.keys]) if (route) route.headers = { ...route.headers, Authorization: headers.Authorization };
}

const rt = await connect(config);
await rt.callScreen();

/** A request to one of the app routes, naming this tab so the server emit skips it. */
async function request(url, body) {
    const response = await fetch(url, {
        method: body ? 'POST' : 'GET',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json', 'X-Realtime-Tab': rt.tab, ...headers },
        ...(body ? { body: JSON.stringify({ ...body, tab: rt.tab }) } : {}),
    });
    return response.ok ? response.json() : null;
}

// #region demo: presence
// Who is online across the shop: a dot on every avatar, kept current.
const online = rt.online;
const dots = () => {
    for (const img of document.querySelectorAll('img.avatar[data-user]')) img.classList.toggle('online', online.has(img.dataset.user));
};
online.watch(shop.people.map((p) => p.id)).on('change', dots);
// #endregion

// A notice at the foot of the page for a few seconds.
const notices = h('div', { class: 'notices', 'aria-live': 'polite' });
const say = (text) => {
    const note = h('p', { class: 'notice' }, text);
    notices.append(note);
    setTimeout(() => note.remove(), 6000);
};

// #region demo: order
// What the server sends the signed-in user alone, such as a notice that their order moved on.
rt.on('notice', (data) => say(data.text));
// #endregion

// The calls of a demo end after 10 minutes and its meetings after 15, as its server `limits` say: it runs on WordPlus
// Cloud for anyone who opens it. `call` and `group` hear the call screen calls too.
if (demo?.limits) {
    const span = (s) => (s % 60 ? `${s} seconds` : `${s / 60} minutes`);
    const keep = (held, seconds, stop, text) => {
        const timer = setTimeout(() => {
            stop();
            say(text);
        }, seconds * 1000);
        held.on('ended', () => clearTimeout(timer));
    };
    void rt.calls().then((calls) => {
        calls?.on('call', (call) => keep(call, demo.limits.call, () => call.end(), `Calls in this demo end after ${span(demo.limits.call)}.`));
        calls?.on('group', (group) => keep(group, demo.limits.meeting, () => group.leave(), `Meetings in this demo end after ${span(demo.limits.meeting)}.`));
    });
}

/** The order status as this page last heard it, for "Try this". */
let orderStatus = shop.order.status;
const statusListeners = [];

// The order: its customer watches it move on, the staff move it. Its timeline is the room history, and "What the
// cloud sees" shows the update as WordPlus Cloud carried it.
function orderCard() {
    const steps = h('ol', { class: 'steps' });
    const buttons = h('div', { class: 'actions' });
    const live = h('p', { class: 'live' }, 'Connecting…');
    const timeline = h('ol', { class: 'timeline', 'data-empty': 'No updates yet' });
    const wire = h('div', { class: 'wire', hidden: true });
    const wireSwitch = h('input', { type: 'checkbox', onchange: () => showWire() });

    const draw = () => {
        const reached = STEPS.indexOf(orderStatus);
        steps.replaceChildren(...STEPS.map((step, i) => h('li', { class: i < reached ? 'done' : i === reached ? 'now' : '' }, LABELS[step])));
        if (me.staff) {
            buttons.replaceChildren(
                h('span', { class: 'muted' }, 'Mark as'),
                ...STEPS.slice(1).map((next) => h('button', { disabled: STEPS.indexOf(next) <= reached, onclick: () => move(next) }, LABELS[next])),
                // On a demo, the order can go back to placed, so its steps can be tried again.
                ...(demo && reached > 0 ? [h('button', { class: 'quiet', onclick: () => move('placed') }, 'Start over')] : []),
            );
        }
        statusListeners.forEach((fn) => fn(orderStatus));
    };

    // An order put back to placed (a demo "Start over") starts its timeline again.
    const moment = (status, at) => h('li', {}, h('span', {}, LABELS[status] ?? status), h('time', {}, when(at)));
    const changed = (status, at) => {
        orderStatus = status;
        if (status === 'placed') timeline.replaceChildren(moment(status, at));
        else timeline.append(moment(status, at));
        draw();
        if (wireSwitch.checked) void showWire();
    };

    // #region demo: order
    // Staff move the order on: this page shows it at once, and the route of your server sends it to everyone else.
    const move = async (next) => {
        changed(next, Date.now());
        await request(shop.routes.status, { status: next });
    };
    // #endregion

    // What the cloud carries: the room and event as they are, the data sealed with the room key. Beside it, the
    // update as this page opened it.
    async function showWire() {
        wire.hidden = !wireSwitch.checked;
        if (wire.hidden) return;
        const seen = await request(shop.routes.wire);
        if (!seen) return;
        wire.replaceChildren(
            h('p', { class: 'wire-label' }, 'What WordPlus Cloud carried'),
            h('pre', {}, `room   ${seen.room}\nevent  ${seen.event}\ndata   ${seen.data}`),
            h('p', { class: 'wire-label' }, 'What this page opened'),
            h('pre', {}, JSON.stringify({ id: shop.order.id, status: orderStatus })),
        );
    }

    const connected = () => {
        live.textContent = 'Live';
        live.className = 'live subscribed';
    };
    // The timeline from the updates the room kept, since the order was last placed.
    const drawTimeline = (updates) => {
        const start = Math.max(0, updates.map((e) => e.data.status).lastIndexOf('placed'));
        timeline.replaceChildren(...updates.slice(start).map((e) => moment(e.data.status, e.at)));
    };

    // #region demo: order
    // The room of the order: each update as your server sends it, and those the room kept for a page opened later.
    const room = rt.join(shop.rooms.order);
    room.on(shop.events.order, (data, meta) => changed(data.status, meta.at ?? Date.now()));
    room.on('joined', async () => {
        connected();
        const kept = await room.history({ limit: 20 }).catch(() => null);
        if (kept) drawTimeline(kept.events.filter((e) => e.event === shop.events.order));
    });
    // #endregion
    room.on('error', (error) => {
        live.textContent = 'Not connected: ' + error.code;
        live.className = 'live failed';
    });

    draw();
    const customer = person(shop.order.customer);
    return h('section', { class: 'card', id: 'order' },
        h('h2', {}, me.staff ? `Order #${shop.order.number ?? shop.order.id} · ${customer?.name}` : `Your order #${shop.order.number ?? shop.order.id}`),
        h('p', { class: 'muted' }, shop.order.item),
        steps,
        me.staff ? buttons : live,
        h('details', { class: 'history', open: true }, h('summary', {}, 'Timeline'), timeline),
        h('label', { class: 'switch' }, wireSwitch, ' What the cloud sees'),
        wire,
    );
}

// The product: a public room anyone may join, signed in or not, whose live count says who is looking.
function productCard() {
    if (!shop.product || !shop.rooms.product) return null;
    const count = h('p', { class: 'muted', id: 'looking' }, ' ');
    // #region demo: product
    // A public room: its count says how many people are looking.
    const room = rt.join(shop.rooms.product);
    const showCount = (n) => {
        count.textContent = n > 1 ? `${n} people are looking at this` : 'Only you are looking at this';
    };
    // The count as it changes, and as it is when this tab joins (another tab of the browser may have heard it first).
    room.on('count', showCount);
    room.on('joined', () => room.count != null && showCount(room.count));
    // #endregion
    return h('section', { class: 'card product', id: 'product' },
        h('img', { src: shop.product.picture, alt: '', width: 480, height: 320 }),
        h('div', {}, h('h2', {}, shop.product.name), count),
    );
}

// The chat of Ann and Ben: the Better Messages conversation on the chat room (<chat-room>), its messages emitted with an ack,
// typing and read ticks as volatile events, and reactions. Above it, the name and picture of the other side from the app
// directory. The conversation belongs to the server, which keeps each message and reaction its webhook brings: the chat pages
// through it (`routes.messages`, asked as this window person), and the room only fills in what came since.
function chatCard() {
    const otherId = String(me.id) === String(shop.chat.between[0]) ? shop.chat.between[1] : shop.chat.between[0];
    const title = h('strong', {}, person(otherId)?.name ?? ' ');
    const head = h('header', { class: 'chat-head' }, title);
    let known = false;

    // A user is in the directory once they have connected: asked now, and again when they come online.
    const lookUp = () => rt.users([otherId]).then((users) => {
        const other = users[otherId];
        if (!other || known) return;
        known = true;
        title.textContent = other.name ?? person(otherId)?.name ?? '';
        if (other.avatar) head.prepend(h('img', { class: 'avatar', src: other.avatar, alt: '', width: 30, height: 30, 'data-user': otherId }));
        dots();
    }, () => {});
    void lookUp();
    online.on('change', ({ id, online: on }) => {
        if (on && !known && String(id) === String(otherId)) void lookUp();
    });

    // #region demo: chat
    const chat = html`<chat-room room="${shop.rooms.chat}" placeholder="Write a message"></chat-room>`;
    // The conversation your server keeps, a page at a time as the reader scrolls up (`before`: the oldest message shown).
    chat.load = async (before) => {
        const page = await request(shop.routes.messages + (before ? '?before=' + encodeURIComponent(before.id) : ''));
        if (!page) throw new Error('the shop did not give its messages');
        return page;
    };
    // #endregion
    return h('section', { class: 'chat', id: 'chat' }, head, chat);
}

// Everyone in the shop now (<online-list>: the presence room members, with a call button for each of the others).
// Stepping out takes the list away, which leaves the room.
function presenceCard() {
    const place = h('div', { class: 'people' });
    const toggle = h('button', { class: 'quiet' }, 'Step out');
    // #region demo: presence
    // Who is in the shop now, with a video call button on the row of each of the others.
    const enter = () => place.replaceChildren(html`
        <online-list room="${shop.rooms.shop}" title="In the shop now"
            call="support:{pair}" type="video"></online-list>`);
    // #endregion

    toggle.addEventListener('click', () => {
        const inside = place.querySelector('online-list') !== null;
        if (inside) place.replaceChildren(h('p', { class: 'muted' }, 'You stepped out.'));
        else enter();
        toggle.textContent = inside ? 'Come back' : 'Step out';
    });

    enter();
    return h('section', { class: 'card', id: 'presence' }, place, h('div', { class: 'actions' }, toggle));
}

// The webhooks the server got from WordPlus Cloud (a message or reaction from a page, someone coming online …), which
// it sends on to the shop webhooks room. The room keeps the last of them.
function webhooksCard() {
    if (!shop.rooms.webhooks) return null;
    const list = h('ol', { class: 'webhooks' });
    const empty = h('p', { class: 'muted' }, 'None yet. Send a message in the chat: your server hears it by webhook.');
    const name = (id) => person(id)?.name ?? (id ? 'User ' + id : 'Someone');
    // The shop rooms in words: `order:1042` is the order.
    const rooms = Object.fromEntries(Object.entries(shop.rooms).map(([kind, room]) => [room, { order: 'the order', chat: 'the chat', shop: 'the shop', meeting: 'the meeting', product: 'the product page', webhooks: 'this list' }[kind] ?? room]));
    const place = (room) => rooms[room] ?? room;
    const say = (w) => ({
        message: `${name(w.user)} sent a message`,
        reaction: `${name(w.user)} reacted to a message`,
        'user.online': `${name(w.user)} came online`,
        'user.offline': `${name(w.user)} went offline`,
        'member.joined': `${name(w.user)} came into ${place(w.room)}`,
        'member.left': `${name(w.user)} left ${place(w.room)}`,
        'room.occupied': `Someone is on ${place(w.room)}`,
        'room.vacated': `Nobody is on ${place(w.room)} now`,
        'stream.live': 'The live show went live',
        'stream.ended': 'The live show ended',
        'group.joined': `${name(w.user)} joined the meeting`,
        'group.left': `${name(w.user)} left the meeting`,
        'stream.joined': `${name(w.user)} came to the live show`,
        'stream.left': `${name(w.user)} left the live show`,
    })[w.type] ?? w.type;
    const showWebhook = (w, at) => {
        empty.remove();
        list.prepend(h('li', {}, h('code', {}, w.type), h('span', {}, say(w)), h('time', {}, when(at))));
        while (list.children.length > 8) list.lastChild.remove();
    };

    // #region demo: webhooks
    // Your server sends each webhook it gets on to this room: shown as it comes, and the last ones the room kept.
    const room = rt.join(shop.rooms.webhooks);
    room.on('webhook', (w, meta) => showWebhook(w, w.at ?? meta.at));
    room.on('joined', async () => {
        const kept = await room.history({ limit: 8 }).catch(() => null);
        if (!kept) return;
        list.replaceChildren();
        for (const e of kept.events) if (e.event === 'webhook') showWebhook(e.data, e.data.at ?? e.at);
    });
    // #endregion
    // On the mobile demo, the phone at the top is Ben in the app, inside this page: a reload connects both again.
    const phone = demo?.phone ? h('p', { class: 'muted' }, `The phone of ${demo.phone.name} at the top is part of this page, so each reload connects both of you again.`) : null;
    return h('section', { class: 'card', id: 'webhooks' }, h('h2', {}, 'Webhooks your server got'), phone, empty, list);
}

// The shop live show (a live stream, the server `streams()` rule): Ann presents the new mugs with her camera, and
// everyone else watches, signed in or not, and writes in its chat. The player, the chat and the studio where Ann goes
// live are <live-stream>, which rt.streamScreen() loads. Only where the server names a show room.
function showCard() {
    if (!shop.rooms.show) return null;
    // #region demo: show
    // The player and its chat for everyone, and for its host the studio to go live from: rt.streamScreen() loads them.
    rt.streamScreen();
    const stream = html`<live-stream name="${shop.rooms.show}" title="The new mugs"></live-stream>`;
    // #endregion
    return h('section', { class: 'card', id: 'show' }, h('h2', {}, 'Live show'), stream);
}

// The daily meeting: a group call everyone in the shop may join, and a look at your camera before you do.
function meetingCard() {
    const preview = h('video', { class: 'preview', muted: true, playsinline: true, autoplay: true, hidden: true });
    let stream = null;
    const check = h('button', { class: 'quiet', onclick: async () => {
        if (stream) {
            stream.getTracks().forEach((t) => t.stop());
            stream = null;
            preview.hidden = true;
            check.textContent = 'Check your camera';
            return;
        }
        stream = await navigator.mediaDevices.getUserMedia({ video: true }).catch(() => null);
        if (!stream) return;
        preview.srcObject = stream;
        preview.hidden = false;
        check.textContent = 'Stop the preview';
    } }, 'Check your camera');
    // #region demo: meeting
    const join = html`<room-button room="${shop.rooms.meeting}" type="video" title="Daily meeting">Join the meeting</room-button>`;
    // #endregion
    // Joining ends the look at the camera, which the call takes.
    join.addEventListener('click', () => stream && check.click());

    return h('section', { class: 'card', id: 'meeting' },
        h('h2', {}, 'Daily meeting'),
        h('p', { class: 'muted' }, 'Ann, Ben and Cara, with video.'),
        preview,
        h('div', { class: 'actions' }, join, check),
    );
}

// The frame of a demo: the stacks, the guide and the source in the top bar, and "Try this", each line ticked as it happens
// (in every window of this browser, which shares what it ticked).
function demoBar() {
    const bar = document.querySelector('.shop-bar');
    if (!bar) return;
    bar.replaceChildren(
        h('div', { class: 'demo-title' }, h('strong', {}, 'API demo'), h('span', { class: 'demo-stack' }, demo.name)),
        h('nav', { class: 'demo-stacks', 'aria-label': 'The same shop on other stacks' },
            ...demo.sites.map((site) => h('a', { href: site.url, 'aria-current': site.stack === demo.stack ? 'page' : false }, site.name))),
        h('div', { class: 'demo-links' },
            h('a', { href: demo.guide }, 'Guide'),
            h('a', { href: demo.source }, 'Source'),
            // Who this window is, and the other people of the shop a click away: the window becomes theirs, as their link
            // does in a window of its own.
            h('nav', { class: 'demo-people', 'aria-label': 'Who you are in this window' },
                ...shop.people.map((p) => {
                    const face = h('img', { class: 'avatar', src: p.avatar, alt: '', width: 24, height: 24, 'data-user': p.id });
                    if (String(p.id) === String(me.id)) return h('span', { class: 'shop-me', 'aria-current': 'true' }, face, p.name);
                    const open = demo.open.find((o) => String(o.id) === String(p.id));
                    return open ? h('a', { href: open.url, title: `Be ${p.name} in this window` }, face, p.name) : null;
                }))),
    );
}

// The shop members, everyone in it whether online or not: a private call to any of the others, named as the list of
// who is in the shop names it (support:{pair}), on a demo, their own window too, where the call rings for them.
function membersCard() {
    const row = (p) => {
        const mine = String(p.id) === String(me.id);
        const open = demo?.open.find((o) => String(o.id) === String(p.id));
        return h('li', { class: 'member' },
            h('img', { class: 'avatar', src: p.avatar, alt: '', width: 36, height: 36, 'data-user': p.id }),
            h('div', { class: 'member-who' }, h('strong', {}, mine ? `${p.name} (you)` : p.name), h('span', { class: 'muted' }, p.role)),
            mine ? null : h('div', { class: 'member-actions' },
                // #region demo: members
                // A private call to this member, by video or by voice, named by the two of them (support:{pair}).
                html`<call-button to="${p.id}" call="support:{pair}" type="video"
                    name="${p.name}" avatar="${p.avatar}">Video call</call-button>`,
                html`<call-button to="${p.id}" call="support:{pair}" type="audio"
                    name="${p.name}" avatar="${p.avatar}">Voice call</call-button>`,
                // #endregion
                open ? h('a', { class: 'button quiet', href: open.url, target: '_blank', rel: 'opener' }, `Open as ${p.name}`) : null),
        );
    };
    return h('section', { class: 'card', id: 'members' },
        h('h2', {}, 'Members'),
        h('ul', { class: 'members' }, ...shop.people.map(row)),
        demo ? h('p', { class: 'muted' }, 'A call rings for a member in their own window: open it with Open as to answer.') : null,
    );
}

function tryThis() {
    const key = 'example-shop-ticks-' + me.shop;
    const read = () => {
        try {
            return JSON.parse(localStorage.getItem(key) ?? '{}');
        } catch {
            return {};
        }
    };
    const ticks = read();
    const lines = {};
    const tick = (name) => {
        if (ticks[name]) return;
        ticks[name] = true;
        lines[name]?.classList.add('done');
        try {
            localStorage.setItem(key, JSON.stringify(ticks));
        } catch {}
    };
    window.addEventListener('storage', (e) => {
        if (e.key !== key) return;
        Object.assign(ticks, read());
        for (const [name, line] of Object.entries(lines)) line.classList.toggle('done', !!ticks[name]);
    });

    const ann = named(34), ben = named(42), cara = named(43);
    const link = (who) => {
        const found = demo.open.find((o) => o.id === who.id);
        return found ? h('a', { href: found.url, target: '_blank', rel: 'opener' }, `Open as ${who.name}`) : null;
    };
    const line = (name, text, action) => (lines[name] = h('li', { class: ticks[name] ? 'done' : '' }, h('span', {}, text), action));

    // Ben comes online. The order is shipped. A call rings.
    online.on('change', ({ id, online: on }) => on && String(id) === String(ben.id) && tick('ben'));
    if (online.has(ben.id) || me.id === ben.id) tick('ben');
    statusListeners.push((status) => STEPS.indexOf(status) >= STEPS.indexOf('shipped') && tick('shipped'));
    void rt.calls().then((calls) => calls?.on('incoming', () => tick('call')));

    const ends = new Date(demo.ends).toLocaleString(LANG, { weekday: 'long', hour: '2-digit', minute: '2-digit' });
    return h('section', { class: 'card try', id: 'try' },
        h('h2', {}, 'Try this'),
        h('ol', {},
            line('ben', `Open ${ben.name}, the customer, in another window`, link(ben)),
            line('shipped', `As ${cara.name}, mark the order shipped`, link(cara)),
            line('call', `As ${ben.name}, call ${ann.name} from the list of who is in the shop`, null),
        ),
        h('p', { class: 'muted' }, `This shop is yours until ${ends}. Send a window link to a colleague to share it.`),
    );
}

// The mobile app demo: the phone of Ben, the Capacitor app signed in as him, beside this page. And where the other mobile
// apps are.
function phoneCard() {
    return h('section', { class: 'card phone-card', id: 'phone' },
        h('h2', {}, `${demo.phone.name}, on his phone`),
        h('p', { class: 'muted' }, 'The Capacitor app: this shop page, built into an app, on the same rooms.'),
        h('div', { class: 'phone' }, h('iframe', { src: demo.phone.url, title: `${demo.phone.name}, in the app`, allow: 'camera; microphone; autoplay' })),
    );
}

function appsCard() {
    const guide = (path, text) => h('a', { href: `https://docs.wordplus.cloud/${path}` }, text);
    return h('section', { class: 'card', id: 'apps' },
        h('h2', {}, 'The other mobile apps'),
        h('ul', { class: 'apps' },
            h('li', {}, h('strong', {}, 'React Native'), h('span', { class: 'muted' }, ' the same shop in native screens, on rooms. '), guide('mobile/example/', 'Run it')),
            h('li', {}, h('strong', {}, 'iOS'), h('span', { class: 'muted' }, ' in Swift, with the native call screen of Better Messages. '), guide('ios/example/', 'The example app')),
            h('li', {}, h('strong', {}, 'Android'), h('span', { class: 'muted' }, ' in Kotlin, with the native call screen of Better Messages. '), guide('android/example/', 'The example app')),
        ),
    );
}

const inChat = shop.chat.between.map(String).includes(String(me.id));

if (demo) demoBar();
root.replaceChildren(
    ...[notices, demo ? tryThis() : null].filter(Boolean),
    h('div', { class: 'shop-grid' },
        h('div', { class: 'shop-column' }, demo?.phone ? phoneCard() : null, orderCard(), productCard(), showCard(), meetingCard()),
        h('div', { class: 'shop-column' },
            inChat ? chatCard() : h('section', { class: 'card' }, h('h2', {}, 'Chat'), h('p', { class: 'muted' }, 'The chat is between Ann and Ben.')),
            membersCard(),
            presenceCard(),
            webhooksCard(),
            demo?.phone ? appsCard() : null,
        ),
    ),
);
if (demo?.code) showCode();
dots();

// On a demo, the code behind each card under it, from the source of this example: its server part first, then its page
// part. Inside the card, or under the chat, which keeps its height.
function showCode() {
    for (const card of root.querySelectorAll('section[id]')) {
        const parts = demo.code[card.id];
        if (!parts) continue;
        const code = h('details', { class: 'code' },
            h('summary', {}, 'See the code'),
            ...parts.map((part) => h('figure', {},
                h('figcaption', {}, h('strong', {}, part.side === 'server' ? 'Server' : 'Page'), h('code', {}, part.file)),
                h('pre', {}, h('code', {}, ...codeLines(part.text))),
                part.side === 'page' ? codeNotes(part.text) : null)));
        if (card.classList.contains('chat')) card.after(code);
        else card.append(code);
    }
}

// Each line of the code a block of its own: a long one wraps under its own indent, as an editor wraps it.
function codeLines(text) {
    const lines = text.split('\n');
    return lines.map((line, i) => {
        const indent = /^[ \t]*/.exec(line)[0].replace(/\t/g, '    ').length;
        return h('span', { class: 'line', style: `--indent: ${indent}ch` }, i < lines.length - 1 ? line + '\n' : line);
    });
}

// Under the page code, what it takes from the page: the room names, routes and event names your server put in it, with
// their values in this shop, and what html`…` does.
function codeNotes(text) {
    const given = [...new Set(text.match(/\bshop\.(?:rooms|routes|events)\.\w+/g) ?? [])]
        .map((ref) => [ref, ref.split('.').slice(1).reduce((value, key) => value?.[key], shop)])
        .filter(([, value]) => typeof value === 'string');
    const notes = [];
    if (given.length) {
        notes.push(h('p', {}, 'From your server, in this shop: ',
            ...given.map(([ref, value], i) => [i ? ', ' : '', h('code', {}, ref), ' is ', h('code', {}, value)]), '.'));
    }
    if (text.includes('html`')) notes.push(h('p', {}, h('code', {}, 'html`…`'), ' makes the element from the HTML in it.'));
    return notes.length ? h('div', { class: 'code-notes' }, ...notes) : null;
}
