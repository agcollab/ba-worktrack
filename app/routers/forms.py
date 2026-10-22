"""Small helpers that turn form strings into Python values.

HTML forms send "" for an empty field, which FastAPI can't turn into int | None,
so routers take str and convert here.
"""
from datetime import date

from fastapi.responses import RedirectResponse

from app.middleware import flash
from app.services.errors import ServiceError


def to_int(value: str | None) -> int | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise ServiceError(f"'{value}' is not a whole number.") from exc


def to_float(value: str | None) -> float | None:
    value = (value or "").strip().replace(",", ".")
    if not value:
        return None
    try:
        return float(value)
    except ValueError as exc:
        raise ServiceError(f"'{value}' is not a number.") from exc


def to_date(value: str | None) -> date | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ServiceError(f"'{value}' is not a valid date.") from exc


def redirect(url: str, message: str | None = None, category: str = "success") -> RedirectResponse:
    response = RedirectResponse(url, status_code=303)
    if message:
        flash(response, message, category)
    return response


def safe_next(url: str | None, default: str = "/") -> str:
    """Only allow redirects to our own pages (no open redirect to another site)."""
    if url and url.startswith("/") and not url.startswith("//") and "\\" not in url:
        return url
    return default
