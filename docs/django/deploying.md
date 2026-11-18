# Deploying a Django app

Under Gunicorn or uWSGI behind nginx, on a PaaS, or under an ASGI server: nothing realtime is kept on your servers, so any of them answers any request.

## Its settings

| | |
|---|---|
| `WORDPLUS_SITE`, `WORDPLUS_SECRET` | from your app in WordPlus Cloud |
| `WORDPLUS_LOCAL_KEY` | yours: kept as long as the app |

Set them in the server environment, as you do `SECRET_KEY`. Keep the secret and the local key out of your repository and out of every page. The key reaches pages through `{% wordplus_realtime %}`, which is what it is for.

## Its addresses

Add every address your pages are served from to the app in WordPlus Cloud: scheme, host and port exactly (`https://shop.example.com`, `https://www.shop.example.com`). A page anywhere else is refused with `wrong_origin`. Up to 20 addresses an app. If your server hears [webhooks](sending.md#webhooks), set their address there too.

## Its files

`realtime.js`, `realtime-worker.js`, `realtime-rooms.min.js`, `realtime-rooms-e2ee.worker.js`, `realtime-ui.min.js` and `realtime-ui-streams.min.js` come with the package, and the app `wordplus_realtime.django`, through `include("wordplus_realtime.django.routes")`, serves them at `/api/realtime/files/{version}/{name}`, from the address of your pages, where a browser runs a worker. Each release serves the ones its package came with, nothing is copied, and each answer is kept for a year as immutable, so a CDN in front of your app keeps them too. They are not static files, so `collectstatic` and a CDN on another host for static files leave them alone.

## Another address

A page served from another address than your routes, such as a single-page app at `https://app.shop.example.com` asking an API at `https://api.shop.example.com`, names your routes in full and sends its user in a header, as a browser sends no cookie to another address:

```js
const rt = await connect( { app: 's1500000007', endpoint: 'https://api.shop.example.com/api/realtime', headers: { Authorization: 'Bearer ' + token } } );
```

- **In WordPlus Cloud,** add the page address to the app, as every other ([its addresses](#its-addresses)).
- **The user** comes from that header, `WORDPLUS_REALTIME["user"]`, a function of the request, as the rest of your API finds it.
- **Django asks a CSRF token of every POST,** which a page on another address does not have, so the routes it asks go before the package URLs exempt from it (the header is the proof here, not a cookie).
- **CORS comes from django-cors-headers, not this package,** so a page never gets the header twice, which a browser refuses. For the page address alone:
  - the address back exactly in `Access-Control-Allow-Origin`, with `Vary: Origin`
  - `POST` for the routes and `GET` for the files, as a group call fetches its encryption worker from there, and the `OPTIONS` asked before them
  - `Content-Type` and the headers the page sends (`Authorization` above)
  - no `Access-Control-Allow-Credentials`, as the page sends no cookie
- **The worker** at another address is one a browser never starts, so each tab of that page connects by itself.

```python
# settings.py (pip install django-cors-headers)
INSTALLED_APPS = [..., "corsheaders"]
MIDDLEWARE = ["corsheaders.middleware.CorsMiddleware", ...]   # before CommonMiddleware
CORS_ALLOWED_ORIGINS = ["https://app.shop.example.com"]
CORS_URLS_REGEX = r"^/api/realtime/.*$"
CORS_ALLOW_METHODS = ["GET", "OPTIONS", "POST"]
CORS_ALLOW_HEADERS = ["content-type", "authorization"]
CORS_PREFLIGHT_MAX_AGE = 600
WORDPLUS_REALTIME = {"user": "shop.auth.user_of_token"}

# urls.py
from django.urls import include, path, re_path
from django.views.decorators.csrf import csrf_exempt
import wordplus_realtime.django as wr

urlpatterns = [
    re_path(r"^api/realtime/(?P<action>auth|calls|keys)$", csrf_exempt(wr.view(wr.get_realtime(), wr.settings_user()))),
    path("api/realtime/", include("wordplus_realtime.django.routes")),
]
```

## Behind a proxy

Set `SECURE_PROXY_SSL_HEADER` and `CSRF_TRUSTED_ORIGINS` as for any Django app behind TLS: the browser routes use the session and the Django CSRF check.

## Several servers

The routes and the rules are plain functions, so every Gunicorn worker on every server answers them. An emit is an HTTPS request to WordPlus Cloud, done in the view. For many emits, or ones you do not want a request to wait on, send them from Celery or a task queue. Only moving keys on keeps a little state, the key generations, in a store they share ([encryption](encryption.md#when-someone-loses-access)).

## Content Security Policy

If your pages send one, let them reach the WordPlus Cloud servers (the realtime servers, which may move a connection to another of them, and the media servers for group calls) and run the workers from your own address:

```text
connect-src 'self' https://*.wordplus.cloud wss://*.wordplus.cloud;
worker-src 'self';
```

## Clocks

Your server signs what it sends with the time. Keep its clock synced (NTP): one more than 5 minutes off has its emits refused with `stale_signature`.
