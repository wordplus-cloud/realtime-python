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

## Workers and threads

The routes and the rules are plain functions, so every Gunicorn worker answers them. An emit is an HTTPS request to WordPlus Cloud, done in the view. For many emits, or ones you do not want a request to wait on, send them from Celery or a task queue.

## Behind a proxy

Set `SECURE_PROXY_SSL_HEADER` and `CSRF_TRUSTED_ORIGINS` as for any Django app behind TLS: the browser routes use the session and the Django CSRF check.

## Content Security Policy

If your pages send one, let them reach the WordPlus Cloud servers (the realtime servers, which may move a connection to another of them, and the media servers for group calls) and run the workers from your own address:

```text
connect-src 'self' https://*.wordplus.cloud wss://*.wordplus.cloud;
worker-src 'self';
```

## Clocks

Your server signs what it sends with the time. Keep its clock synced (NTP): one more than 5 minutes off has its emits refused with `stale_signature`.
