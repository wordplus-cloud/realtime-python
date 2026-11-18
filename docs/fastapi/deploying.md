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

## Another address

A page served from another address than your routes, such as a single-page app at `https://app.shop.example.com` asking an API at `https://api.shop.example.com`, or one in Capacitor, names your routes in full and sends its user in a header, as a browser sends no cookie to another address:

```js
const rt = await connect( { app: 's1500000007', endpoint: 'https://api.shop.example.com/api/realtime', headers: { Authorization: 'Bearer ' + token } } );
```

- **In WordPlus Cloud,** add the page address to the app, as every other ([its addresses](#its-addresses)).
- **The user** comes from that header, the function you give `router()`, as the rest of your API finds it.
- **CORS comes from FastAPI, not this package,** so a page never gets the header twice, which a browser refuses. For the page address alone:
  - the address back exactly in `Access-Control-Allow-Origin`, with `Vary: Origin`
  - `POST` for the routes and `GET` for the files, as a group call fetches its encryption worker from there, and the `OPTIONS` asked before them
  - `Content-Type` and the headers the page sends (`Authorization` above)
  - no `Access-Control-Allow-Credentials`, as the page sends no cookie
- **The worker** at another address is one a browser never starts, so each tab of that page connects by itself.

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(CORSMiddleware, allow_origins=["https://app.shop.example.com"], allow_methods=["GET", "POST"], allow_headers=["Content-Type", "Authorization"], max_age=600)
```

## Behind a proxy

Run Uvicorn with `--proxy-headers`, and name your proxy in `--forwarded-allow-ips`, so the session cookie and redirects see HTTPS as the browser does:

```bash
uvicorn app:app --proxy-headers --forwarded-allow-ips 10.0.0.1
```

## Several servers

The router runs the rules on a worker thread, and `aemit()` and `aask()` their requests on one too, so none holds up the event loop. Any number of Uvicorn workers, on any number of servers, answer the routes: they share nothing but your database. Only moving keys on keeps a little state, the key generations, in a store they share ([encryption](encryption.md#when-someone-loses-access)).

## Content Security Policy

If your pages send one, let them reach the WordPlus Cloud servers (the realtime servers, which may move a connection to another of them, and the media servers for group calls) and run the workers from your own address:

```text
connect-src 'self' https://*.wordplus.cloud wss://*.wordplus.cloud;
worker-src 'self';
```

## Clocks

Your server signs what it sends with the time. Keep its clock synced (NTP): one more than 5 minutes off has its emits refused with `stale_signature`.
