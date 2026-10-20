# The API demo on Flask

Sign in as Ann (support), Ben (a customer) or Cara (the warehouse), each in a browser of their own: the order of Ben follows as Ann moves it on and Ben alone gets a notice, Ann and Ben chat with “typing…” and the server keeps the conversation from its webhook, everyone sees who is in the shop and who is online and can call them, a call can bring in more staff, and all three can meet in the daily meeting. The guide is at [docs.wordplus.cloud/flask](https://docs.wordplus.cloud/flask/getting-started/).

```bash
cp .env.example .env              # the key and secret of your app, with http://localhost:8000 among its addresses, and a local key
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/flask --app app run --port 8000      # http://localhost:8000
```

| File | |
|---|---|
| `app.py` | the realtime server part with its rooms and calls, `wordplus_realtime.flask.init_app()` for its routes, webhook and browser files, signing in, the order route, and the page |
| `templates/page.html` | the page, with `wordplus_realtime()`, the settings and the import map of the client, and the shop data through `tojson` |
| `shop/shop.js` | the page script, the same in every example, served as it is from the static folder: no Node and no bundler |
