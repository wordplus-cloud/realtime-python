"""WordPlus Cloud's realtime SDK in FastAPI and Starlette: the browser's routes and the realtime server's webhook as a
router, for the user the app finds.

    realtime = Realtime.from_environment(profile=lambda user: {"name": name_of(user)})

    async def current_user(request: Request) -> Optional[int]:
        return (await session_of(request)).user_id

    app.include_router(wordplus_realtime.fastapi.router(realtime, current_user), prefix="/api/realtime")

    await realtime.to("order:42").aemit("updated", {"status": "paid"})

The rules and the webhook's handlers run on a worker thread, so they may query a database the plain way.
"""

from __future__ import annotations

import inspect
from typing import Any, Awaitable, Callable, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from .keys import UserId
from .realtime import ROUTES, Realtime, _path_of


def router(realtime: Realtime, user: Callable[[Request], Any]) -> APIRouter:
    """POST /auth, /calls, /keys and /webhook under the prefix it is included with. ``user(request)`` gives the request's
    user's id, or None; it may be async. The webhook asks no user: the realtime server signs it. With routes at addresses
    of their own (the ``routes`` option), each at its whole address: include it with no prefix."""
    routes = APIRouter()

    async def answer(action: str, request: Request) -> Response:
        body = await request.body()
        if action == "webhook":
            path = request.url.path + ("?" + request.url.query if request.url.query else "")
            status, answer = await run_in_threadpool(realtime.webhook, body, request.headers, path)
        else:
            who = user(request)
            if inspect.isawaitable(who):
                who = await who
            status, answer = await run_in_threadpool(realtime.answer_request, request.method, request.headers.get("content-type", ""), action, body, who)
        if status == 204:
            return Response(status_code=204, headers={"Cache-Control": "no-store"})
        return JSONResponse(answer, status_code=status, headers={"Cache-Control": "no-store"})

    def at(action: str) -> Callable[[Request], Awaitable[Response]]:
        # The route named here alone: a parameter of its own would be read from the query.
        async def at_address(request: Request) -> Response:
            return await answer(action, request)

        return at_address

    # The browser files the package carries: GET files/{version}/{name}, the same for every user.
    async def file(request: Request) -> Response:
        params = request.path_params
        status, headers, body = realtime.file_named(request.method, params.get("version"), params["name"], request.headers.get("if-none-match"))
        return Response(body or b"", status_code=status, headers=headers)

    def files(at: str) -> None:
        if realtime.serves_files:
            routes.add_api_route(at + "/files/{name}", file, methods=["GET", "HEAD"], include_in_schema=False)
            routes.add_api_route(at + "/files/{version}/{name}", file, methods=["GET", "HEAD"], include_in_schema=False)

    if realtime.own_routes:
        files(realtime.base)
        for name in ROUTES:
            routes.add_api_route(_path_of(realtime.address(name)), at(name), methods=["POST"], include_in_schema=False)
        return routes

    files("")

    @routes.post("/{action}", include_in_schema=False)
    async def wordplus_realtime(action: str, request: Request) -> Response:
        return await answer(action, request)

    return routes


def config_for(realtime: Realtime, user: Optional[UserId]) -> Any:
    """The browser's settings for a user, for a page or a route of the app's own that answers them."""
    return realtime.config(user)
