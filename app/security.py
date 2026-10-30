"""Bound request bodies before JSON parsing and attach conservative headers."""

from starlette.responses import JSONResponse


class SecurityMiddleware:
    def __init__(self, app, max_body=64000):
        self.app, self.max_body = app, max_body

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        body = b""
        if scope["method"] in {"POST", "PUT", "PATCH"}:
            more = True
            while more:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                body += message.get("body", b"")
                if len(body) > self.max_body:
                    return await JSONResponse({"detail": {"code": "request_too_large"}}, status_code=413)(scope, receive, send)
                more = message.get("more_body", False)
            consumed = False

            async def bounded_receive():
                nonlocal consumed
                if not consumed:
                    consumed = True
                    return {"type": "http.request", "body": body}
                return await receive()
        else:
            bounded_receive = receive

        async def secure_send(message):
            if message["type"] == "http.response.start":
                csp = b"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
                if scope["path"] in {"/docs", "/redoc"}:
                    csp = b"default-src 'self'; script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; img-src 'self' https://fastapi.tiangolo.com; frame-ancestors 'none'"
                message.setdefault("headers", []).extend([
                    (b"x-content-type-options", b"nosniff"), (b"x-frame-options", b"DENY"),
                    (b"referrer-policy", b"no-referrer"), (b"cache-control", b"no-store"),
                    (b"content-security-policy", csp),
                ])
            await send(message)
        await self.app(scope, bounded_receive, secure_send)
