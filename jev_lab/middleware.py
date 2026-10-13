"""Small local-app boundary around the HTTP server."""

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

MAX_BODY_BYTES = 64000
SECURITY_HEADERS = {
    "cache-control": "no-store",
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "content-security-policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self' data:; connect-src 'self'; frame-src 'self'; "
        "frame-ancestors 'self'; base-uri 'none'; form-action 'none'"
    ),
}


class LocalOnlyMiddleware:
    def __init__(self, app: ASGIApp, port: int) -> None:
        self.app = app
        self.hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        self.origins = {f"http://{host}" for host in self.hosts}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = [(k, v) for k, v in message["headers"] if k.decode().lower() not in SECURITY_HEADERS]
                headers.extend((k.encode(), v.encode()) for k, v in SECURITY_HEADERS.items())
                message["headers"] = headers
            await send(message)

        async def reject(status: int, message: str) -> None:
            await JSONResponse({"error": message}, status_code=status)(scope, receive, send_with_headers)

        headers = Headers(scope=scope)
        if headers.get("host") not in self.hosts:
            await reject(403, "Use the local address printed by the server.")
            return
        if headers.get("origin") and headers["origin"] not in self.origins:
            await reject(403, "Requests must come from this local app.")
            return
        if scope["method"] != "POST":
            await self.app(scope, receive, send_with_headers)
            return
        if headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
            await reject(415, "Send application/json.")
            return

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > MAX_BODY_BYTES:
                await reject(413, "The request is too large.")
                return
            if not message.get("more_body", False):
                break

        delivered = False

        async def replay_body() -> Message:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay_body, send_with_headers)
