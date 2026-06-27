from __future__ import annotations

import asyncio
import http.client
from contextlib import suppress
from http.cookies import SimpleCookie
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from fastapi.responses import RedirectResponse, Response

from app.core.config import Settings
from app.models import UserRead

HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "content-length",
}


def create_router(settings: Settings) -> APIRouter:
    router = APIRouter(include_in_schema=False)

    @router.get("/browser")
    async def browser_redirect() -> RedirectResponse:
        return RedirectResponse(settings.desktop_proxy_path)

    @router.api_route(
        "/browser/{path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    )
    async def proxy_browser_http(path: str, request: Request) -> Response:
        return await proxy_browser_request(path, request, settings)

    @router.websocket("/browser/{path:path}")
    async def proxy_browser_websocket(websocket: WebSocket, path: str) -> None:
        session = websocket_session(websocket, settings)
        if session is None:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        await proxy_websocket(path, websocket, settings)

    return router


async def proxy_browser_request(
    path: str,
    request: Request,
    settings: Settings,
) -> Response:
    upstream = urlsplit(settings.desktop_upstream)
    if upstream.scheme not in {"http", "https"} or not upstream.hostname:
        raise HTTPException(status_code=500, detail="Desktop upstream is invalid.")

    upstream_path = browser_upstream_path(settings, path, request.url.query)
    body = await request.body()
    headers = proxy_request_headers(request, upstream)
    connection_class = http.client.HTTPSConnection if upstream.scheme == "https" else http.client.HTTPConnection
    port = upstream.port or (443 if upstream.scheme == "https" else 80)

    try:
        connection = connection_class(upstream.hostname, port, timeout=30)
        connection.request(request.method, upstream_path, body=body or None, headers=headers)
        upstream_response = connection.getresponse()
        content = upstream_response.read()
    except OSError as exc:
        raise HTTPException(status_code=502, detail="Browser desktop is unavailable.") from exc
    finally:
        with suppress(NameError):
            connection.close()

    response = Response(content=content, status_code=upstream_response.status)
    for name, value in upstream_response.getheaders():
        if name.lower() in HOP_BY_HOP_HEADERS:
            continue
        response.headers.append(name, value)
    return response


def proxy_request_headers(request: Request, upstream) -> dict[str, str]:  # type: ignore[no-untyped-def]
    headers: dict[str, str] = {}
    for name, value in request.headers.items():
        lowered = name.lower()
        if lowered in HOP_BY_HOP_HEADERS or lowered == "host":
            continue
        headers[name] = value
    host = upstream.hostname or "127.0.0.1"
    if upstream.port:
        host = f"{host}:{upstream.port}"
    headers["Host"] = host
    return headers


def browser_upstream_path(settings: Settings, path: str, query: str) -> str:
    prefix = "/" + settings.desktop_proxy_path.strip("/")
    suffix = f"/{path}" if path else "/"
    upstream_path = f"{prefix}{suffix}"
    if query:
        upstream_path = f"{upstream_path}?{query}"
    return upstream_path


def websocket_session(
    websocket: WebSocket,
    settings: Settings,
) -> UserRead | None:
    cookie_header = websocket.headers.get("cookie", "")
    cookie = SimpleCookie(cookie_header)
    morsel = cookie.get(settings.session_cookie_name)
    if morsel is None:
        return None
    return websocket.app.state.user_repository.current_user_from_token(morsel.value)


async def proxy_websocket(
    path: str,
    websocket: WebSocket,
    settings: Settings,
) -> None:
    try:
        import websockets
    except ImportError as exc:
        raise HTTPException(status_code=500, detail="WebSocket proxy dependency is missing.") from exc

    upstream = urlsplit(settings.desktop_upstream)
    if upstream.scheme not in {"http", "https"} or not upstream.hostname:
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        return
    scheme = "wss" if upstream.scheme == "https" else "ws"
    port = upstream.port or (443 if upstream.scheme == "https" else 80)
    upstream_path = browser_upstream_path(settings, path, websocket.url.query)
    upstream_url = f"{scheme}://{upstream.hostname}:{port}{upstream_path}"

    await websocket.accept()
    try:
        async with websockets.connect(upstream_url, max_size=None) as upstream_socket:
            client_task = asyncio.create_task(forward_client_to_upstream(websocket, upstream_socket))
            upstream_task = asyncio.create_task(forward_upstream_to_client(websocket, upstream_socket))
            done, pending = await asyncio.wait(
                {client_task, upstream_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            for task in done:
                task.result()
    except WebSocketDisconnect:
        return
    except Exception:
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR)


async def forward_client_to_upstream(websocket: WebSocket, upstream_socket) -> None:  # type: ignore[no-untyped-def]
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            break
        if "text" in message:
            await upstream_socket.send(message["text"])
        elif "bytes" in message:
            await upstream_socket.send(message["bytes"])


async def forward_upstream_to_client(websocket: WebSocket, upstream_socket) -> None:  # type: ignore[no-untyped-def]
    async for message in upstream_socket:
        if isinstance(message, bytes):
            await websocket.send_bytes(message)
        else:
            await websocket.send_text(message)
