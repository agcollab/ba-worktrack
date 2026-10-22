"""Login, logout and the user's own profile / password."""
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.deps import COOKIE_NAME, csrf_protect, get_current_user, get_optional_user
from app.models import User
from app.routers.forms import redirect, safe_next, to_float
from app.security import create_access_token
from app.services import audit, users
from app.services.audit import client_ip
from app.services.errors import ServiceError
from app.templating import render

router = APIRouter(tags=["auth"], dependencies=[Depends(csrf_protect)], include_in_schema=False)

_attempts: dict[str, deque[float]] = defaultdict(deque)


def rate_limited(key: str, limit: int | None = None, window: float = 60.0) -> bool:
    """Simple sliding-window limit per IP (in memory, per process)."""
    limit = limit or settings.LOGIN_RATE_LIMIT_PER_MINUTE
    now = time.monotonic()
    bucket = _attempts[key]
    while bucket and now - bucket[0] > window:
        bucket.popleft()
    if len(bucket) >= limit:
        return True
    bucket.append(now)
    return False


def set_login_cookie(response: Response, user: User) -> None:
    response.set_cookie(
        COOKIE_NAME, create_access_token(user.id), max_age=settings.ACCESS_TOKEN_MINUTES * 60,
        httponly=True, samesite="lax", secure=settings.is_production,
    )


@router.get("/login")
def login_page(request: Request, next: str = "/", user: User | None = Depends(get_optional_user)):
    if user:
        return RedirectResponse(safe_next(next), status_code=303)
    return render(request, "auth/login.html", {"next": safe_next(next), "email": ""})


@router.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...), next: str = Form("/"),
          db: Session = Depends(get_db)):
    ip = client_ip(request) or "unknown"
    if rate_limited(ip):
        return render(request, "auth/login.html", {"error": "Too many attempts. Wait a minute and try again.",
                                                   "email": email, "next": safe_next(next)}, status_code=429)
    try:
        user = users.authenticate(db, email, password)
    except ServiceError as exc:
        audit.record(db, "auth.login_failed", details={"email": email}, request=request)
        db.commit()
        return render(request, "auth/login.html", {"error": exc.message, "email": email, "next": safe_next(next)},
                      status_code=401)
    audit.record(db, "auth.login", user=user, entity=user, request=request)
    db.commit()
    target = "/profile?must_change=1" if user.must_change_password else safe_next(next)
    response = RedirectResponse(target, status_code=303)
    set_login_cookie(response, user)
    return response


@router.post("/logout")
def logout():
    response = redirect("/login", "You are signed out.")
    response.delete_cookie(COOKIE_NAME)
    return response


@router.get("/profile")
def profile(request: Request, must_change: int = 0, user: User = Depends(get_current_user)):
    return render(request, "auth/profile.html", {"must_change": must_change or user.must_change_password})


@router.post("/profile")
def update_profile(full_name: str = Form(...), job_title: str = Form(""), weekly_capacity_hours: str = Form("40"),
                   user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    capacity = to_float(weekly_capacity_hours) or 40
    if not full_name.strip():
        raise ServiceError("Full name is required.")
    if not 0 < capacity <= 80:
        raise ServiceError("Weekly capacity must be between 1 and 80 hours.")
    user.full_name, user.job_title, user.weekly_capacity_hours = full_name.strip(), job_title.strip() or None, capacity
    db.commit()
    return redirect("/profile", "Profile saved.")


@router.post("/profile/password")
def change_password(request: Request, current_password: str = Form(...), new_password: str = Form(...),
                    confirm_password: str = Form(...), user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    users.change_own_password(user, current_password, new_password, confirm_password)
    audit.record(db, "user.change_password", user=user, entity=user, request=request)
    db.commit()
    response = redirect("/", "Password changed.")
    set_login_cookie(response, user)
    return response
