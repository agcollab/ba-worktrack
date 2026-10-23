"""Middleware that runs around every request: security headers, CSRF cookie, flash
messages, a request id and one structured log line per request."""
import json
import logging
import time
import uuid
from urllib.parse import quote, unquote

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.config import settings
from app.security import new_csrf_token

logger = logging.getLogger("app.request")

FLASH_COOKIE = "flash"

CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)


def flash(response: Response, message: str, category: str = "success") -> None:
    """Show a one-time message on the next page the browser renders."""
    response.set_cookie(
        FLASH_COOKIE,
        quote(json.dumps({"message": message, "category": category})),
        max_age=60,
        httponly=True,
        samesite="lax",
        secure=settings.is_production,
    )


def read_flash(request: Request) -> dict | None:
    raw = request.cookies.get(FLASH_COOKIE)
    if not raw:
        return None
    request.state.flash_consumed = True
    try:
        data = json.loads(unquote(raw))
        return data if isinstance(data, dict) else None
    except ValueError:
        return None


class AppMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        request.state.request_id = request_id
        csrf = request.cookies.get("csrf_token")
        request.state.csrf_token = csrf or new_csrf_token()
        request.state.flash_consumed = False

        started = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - started) * 1000, 1)

        if not csrf:
            # Readable by nobody but our own pages (HttpOnly); forms carry a copy of it
            response.set_cookie("csrf_token", request.state.csrf_token, httponly=True,
                                samesite="lax", secure=settings.is_production)
        if request.state.flash_consumed:
            # Shown once: forget it, unless this response sets a new message
            new_flash = any(h.startswith(FLASH_COOKIE + "=") for h in response.headers.getlist("set-cookie"))
            if not new_flash:
                response.delete_cookie(FLASH_COOKIE)

        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if not request.url.path.startswith(("/docs", "/redoc")):
            response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
        if settings.is_production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        if not request.url.path.startswith("/static"):
            logger.info(json.dumps({
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": duration_ms,
                "user_id": getattr(getattr(request.state, "user", None), "id", None),
            }))
        return response
