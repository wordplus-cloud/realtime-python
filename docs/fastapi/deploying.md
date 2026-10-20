# Deploying a FastAPI app

Under Uvicorn or Gunicorn with Uvicorn workers, behind nginx or on a PaaS: nothing realtime is kept on your servers, so any worker answers any request.

## Its settings

| | |
|---|---|
| `WORDPLUS_SITE`, `WORDPLUS_SECRET` | from your app in WordPlus Cloud |
| `WORDPLUS_LOCAL_KEY` | yours: kept as long as the app |

Set them in the server environment. Keep the secret and the local key out of your repository and out of every page. The key reaches pages through `realtime.head()`, which is what it is for.

## Its addresses

Add every address your pages are served from to the app in WordPlus Cloud: scheme, host and port exactly (`https://shop.example.com`, `https://www.shop.example.com`). A page anywhere else is refused with `wrong_origin`. Up to 20 addresses an app. If your server hears [webhooks](sending.md#webhooks), set their address there too.

## Its files

`realtime.js`, `realtime-worker.js`, `realtime-rooms.min.js`, `realtime-rooms-e2ee.worker.js`, `realtime-ui.min.js` and `realtime-ui-streams.min.js` come with the package, and its router serves them at `/api/realtime/files/{version}/{name}`, from the address of your pages, where a browser runs a worker. Each release serves the ones its package came with, nothing is copied, and each answer is kept for a year as immutable, so a CDN in front of your app keeps them too.

## Workers

The router runs the rules on a worker thread, and `aemit()` its request on one too, so neither holds up the event loop. Any number of Uvicorn workers answer the routes: they share nothing but your database and, for moving keys on, the generation store.

## Another address

A page or app served from another address than your API, such as a single-page app on its own domain or one in Capacitor, connects with `endpoint: 'https://api.example.com/api/realtime'`, and your server answers that address with CORS:

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(CORSMiddleware, allow_origins=["https://app.example.com"], allow_credentials=True, allow_methods=["POST"], allow_headers=["*"])
```

Add that address to the app in WordPlus Cloud too.

## Content Security Policy

If your pages send one, let them reach the WordPlus Cloud servers (the realtime servers, which may move a connection to another of them, and the media servers for group calls) and run the workers from your own address:

```text
connect-src 'self' https://*.wordplus.cloud wss://*.wordplus.cloud;
worker-src 'self';
```

## Clocks

Your server signs what it sends with the time. Keep its clock synced (NTP): one more than 5 minutes off has its emits refused with `stale_signature`.
