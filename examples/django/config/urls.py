from django.urls import include, path

import wordplus_realtime.django as wr
from store import views
from store.realtime import realtime

urlpatterns = [
    # The browser routes: POST /api/realtime/auth, /calls and /keys, for the user of the session (or the window of a demo, its
    # bearer), with the Django CSRF check. And /api/realtime/webhook, which the realtime server signs itself.
    path("api/realtime/", include(wr.urls(realtime, user=views.current_user))),
    path("login/", views.sign_in),
    path("logout/", views.sign_out),
    path("", views.shop),
    # On a demo, a window as one of the shop people (demo.py).
    path("as/<str:token>", views.shop),
    path("orders/<int:pk>/status", views.order_status),
    path("orders/<int:pk>/wire", views.order_wire),
    path("chat/messages", views.chat_messages),
]
