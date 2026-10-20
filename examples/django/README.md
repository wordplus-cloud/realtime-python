# The API demo on Django

Sign in as Ann (support), Ben (a customer) or Cara (the warehouse), each in a browser of their own: the order of Ben follows as Ann moves it on and Ben alone gets a notice, Ann and Ben chat with “typing…” and the server keeps the conversation from its webhook, everyone sees who is in the shop and who is online and can call them, a call can bring in more staff, and all three can meet in the daily meeting. The guide is at [docs.wordplus.cloud/django](https://docs.wordplus.cloud/django/getting-started/).

```bash
cp .env.example .env              # the key and secret of your app, with http://localhost:8000 among its addresses, and a local key
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python manage.py migrate        # the people of the shop (Ann 34, Ben 42, Cara 43), the order of Ben and the chat
.venv/bin/python manage.py runserver      # http://localhost:8000
```

| File | |
|---|---|
| `store/realtime.py` | the realtime server part: credentials, profiles, and its rooms and calls and who may use them |
| `config/settings.py` | `wordplus_realtime.django` among the apps, and `shop/` as the static files |
| `config/urls.py` | the browser routes, the webhook and the browser files with `wr.urls()`, and the shop |
| `store/views.py` | signing in, the page, and moving the order on with a notice to its customer |
| `store/templates/store/page.html` | the page, with `{% wordplus_realtime %}`, the settings and the import map of the client |
| `store/models.py`, `store/migrations/` | the profiles of the people, the order and the first messages of the chat, and the data they start with |
| `shop/shop.js` | the page script, the same in every example, served as it is as a static file: no Node and no bundler |
