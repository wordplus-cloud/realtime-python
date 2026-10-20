"""``path("api/realtime/", include("wordplus_realtime.django.routes"))``: the routes of the Realtime made from settings
(``WORDPLUS_REALTIME``), for the user it names, else the session's."""

from . import get_realtime, settings_user, urls

urlpatterns = urls(get_realtime(), settings_user())
