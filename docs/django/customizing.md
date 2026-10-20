# Customizing the screens in Django

The call screen, the chat and the list of who is online can be made part of the design of your app, or changed down to their code, with your AI coding agent or by hand. Each step goes further than the last: [making the screens your own](https://docs.wordplus.cloud/apps/customizing/) has every detail.

## 1. The look

The elements draw in a shadow root, and their colours are custom properties your page sets:

```css
/* static/shop.css */
call-screen, chat-room, online-list {
    --bm-color-accent: 37, 99, 235;      /* red, green, blue */
    --bm-messenger-font: Inter, system-ui, sans-serif;
    --bm-radius-card: 14px;
}
```

## 2. A piece of your own

Your stylesheet reaches each piece by its name, and a `<template slot>` draws one with your own markup:

```css
chat-room::part(message) { font-size: 15px; }
call-screen::part(call-controls) { bottom: 24px; }
```

```html
{# shop/templates/shop/order.html #}
<chat-room room="order-chat:{{ order.pk }}" messages="{% url 'order-messages' order.pk %}">
    <template slot="empty-conversation"><p>{% translate "Ask us anything about this order." %}</p></template>
</chat-room>

<call-screen>
    <template slot="control" data-control="order" data-label="{% translate 'Show the order' %}" data-icon="edit"></template>
</call-screen>
```

```js
// order.js
document.addEventListener( 'realtime-control', ( e ) => { if ( e.detail.control === 'order' ) showOrder(); } );
```

Every part, every template and what fills it: [on any page](https://docs.wordplus.cloud/apps/customizing/#on-any-page-the-elements).

The names are plain words, so your pages name no one but your app. To put your own before each, `screen: { prefix: 'shop' }` in `connect()` makes `<shop-chat-room>` and `<shop-call-screen>` ([your own names](https://docs.wordplus.cloud/apps/elements/#your-own-names)).

## 3. The code itself

Copy a view into your project. It is React, built once into your own elements script with Node:

```bash
npm install @wordplus/realtime-ui
npm install -D react react-dom esbuild
npx @wordplus/realtime-ui add chat
node wordplus-ui.build.mjs          # static/realtime-ui.js, with your copy
```

```js
// order.js
const rt = await connect( { ...JSON.parse( document.getElementById( 'realtime' ).textContent ), ui: '/static/realtime-ui.js' } );
```

The view is yours now: `components/wordplus/chat/`, and what runs the conversation stays in the package. Build again after each change, before `collectstatic`. Check it with its tests (`npx vitest run components/wordplus`) and every state in the preview (`npx @wordplus/realtime-ui preview`). When ours changes, `npx @wordplus/realtime-ui diff` shows what to merge.

## 4. Your own interface

The elements are the ready-made option, never a must. Draw who is online, the chat, the calls and the live stream with your own components, on the same API they are built on: your rules, encryption and connection stay the same. [Your own interface](https://docs.wordplus.cloud/apps/interface/) shows the API under each element.

## With your AI coding agent

The agent skill of the package teaches it all of this. Ask for what you want, such as "put the order status at the top of the chat", and it changes the screens at the step that does it, then runs the tests and looks at the preview.
