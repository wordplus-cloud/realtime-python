"""``{% load wordplus_realtime %}`` then ``{% wordplus_realtime %}`` in a page's head: the settings for the request's
user, with Django's CSRF token, and the import map of the client the routes serve, so the page's own module imports
``@wordplus/realtime`` with no bundler. ``{% wordplus_realtime importmap=False %}`` for a page whose bundler resolves
it, and ``{% wordplus_realtime user=… %}`` for a page whose view knows its user another way than the routes do. It
needs the request in the template's context (django.template.context_processors.request)."""

from django import template
from django.utils.safestring import mark_safe

from .. import head_for

register = template.Library()

_ROUTES_USER = object()


@register.simple_tag(takes_context=True)
def wordplus_realtime(context, importmap=True, user=_ROUTES_USER):
    request = context.get("request")
    if request is None:
        raise template.TemplateSyntaxError("{% wordplus_realtime %} needs the request: add django.template.context_processors.request to the template context processors")
    if user is _ROUTES_USER:
        return mark_safe(head_for(request, importmap=importmap))
    return mark_safe(head_for(request, importmap=importmap, user=lambda _: user))
