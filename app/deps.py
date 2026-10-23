"""FastAPI dependencies shared by the routers: the logged-in user, role checks, CSRF."""
from collections.abc import Callable

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.models import User
from app.security import csrf_tokens_match, decode_access_token

COOKIE_NAME = "access_token"
CSRF_COOKIE = "csrf_token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class LoginRequired(Exception):
    """Raised on HTML pages when nobody is logged in; turned into a redirect to /login."""


def _token_from_request(request: Request) -> tuple[str | None, bool]:
    """(token, came_from_bearer_header)."""
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip(), True
    return request.cookies.get(COOKIE_NAME), False


def get_optional_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    token, _ = _token_from_request(request)
    if not token:
        return None
    user_id = decode_access_token(token)
    if user_id is None:
        return None
    user = db.scalar(select(User).options(selectinload(User.roles)).where(User.id == user_id))
    if user is None or not user.is_active:
        return None
    request.state.user = user
    return user


def is_api_request(request: Request) -> bool:
    return request.url.path.startswith("/api/")


def get_current_user(request: Request, user: User | None = Depends(get_optional_user)) -> User:
    if user is None:
        if is_api_request(request):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated",
                                headers={"WWW-Authenticate": "Bearer"})
        raise LoginRequired()
    return user


def require_role(*roles: str) -> Callable[..., User]:
    """Dependency factory: require_role("Admin") lets only admins through."""

    def checker(user: User = Depends(get_current_user)) -> User:
        if not user.has_role(*roles):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not have permission for this page.")
        return user

    return checker


require_admin = require_role("Admin")
require_manager = require_role("Admin", "PM")


async def csrf_protect(request: Request) -> None:
    """Double-submit check for every form post made with the login cookie.

    The page embeds the csrf_token cookie value in each form (and HTMX sends it as
    the X-CSRF-Token header). Another site can make the browser send our cookie,
    but cannot read it, so it cannot send the matching value. API clients that use
    a Bearer token, or send JSON, are not exposed to CSRF and skip the check.
    """
    if request.method in SAFE_METHODS:
        return
    _, bearer = _token_from_request(request)
    if bearer:
        return
    if request.headers.get("content-type", "").startswith("application/json"):
        # Browsers only send cross-site JSON after a CORS preflight, which this app never allows
        return
    cookie = request.cookies.get(CSRF_COOKIE)
    sent = request.headers.get("x-csrf-token")
    if not sent:
        content_type = request.headers.get("content-type", "")
        if content_type.startswith(("application/x-www-form-urlencoded", "multipart/form-data")):
            form = await request.form()
            sent = form.get("csrf_token")  # type: ignore[assignment]
    if not csrf_tokens_match(cookie, sent if isinstance(sent, str) else None):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Your session form expired. Reload the page and try again.")
