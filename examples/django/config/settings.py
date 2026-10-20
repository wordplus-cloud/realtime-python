"""The API demo settings: the Django defaults for a small app, SQLite, the realtime app, and the shop page as its static
files, as it is: no Node and no bundler, as {% wordplus_realtime %} names @wordplus/realtime the client the routes serve."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# .env, for the development server: a real host sets these in its environment.
if (BASE_DIR / ".env").exists():
    for line in (BASE_DIR / ".env").read_text().splitlines():
        name, _, value = line.partition("=")
        if name.strip() and not name.startswith("#") and value.strip():
            os.environ.setdefault(name.strip(), value.strip())

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "example-shop-not-for-production")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.staticfiles",
    "wordplus_realtime.django",
    "store",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
]

ROOT_URLCONF = "config.urls"
LOGIN_URL = "/login/"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": ["django.template.context_processors.request"]},
    }
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "shop"]
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True

# A demo (WORDPLUS_DEMO=1, demo.py), behind its site proxy, which speaks HTTPS for it: its address, and cookies only
# for its own host, sent over HTTPS alone.
if os.environ.get("WORDPLUS_DEMO") == "1":
    DEMO_HOSTS = [host for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",") if host]
    ALLOWED_HOSTS += DEMO_HOSTS
    CSRF_TRUSTED_ORIGINS = [f"https://{host}" for host in DEMO_HOSTS]
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_NAME, SESSION_COOKIE_SECURE = "__Host-shop", True
    CSRF_COOKIE_NAME, CSRF_COOKIE_SECURE = "__Host-csrf", True
