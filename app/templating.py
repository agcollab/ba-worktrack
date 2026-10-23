"""The Jinja2 template engine, created once and shared by every router, plus a few
helpers (render, toast) that every page uses."""
import json
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlencode

from fastapi import Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from app.ai.provider import ai_enabled
from app.config import settings
from app.middleware import read_flash
from app.models import TaskPriority, TaskStatus, TaskType

TEMPLATES_DIR = Path(__file__).parent / "templates"

templates = Jinja2Templates(directory=TEMPLATES_DIR)

STATUS_CLASSES = {
    TaskStatus.TODO: "status-todo",
    TaskStatus.IN_PROGRESS: "status-progress",
    TaskStatus.IN_REVIEW: "status-review",
    TaskStatus.DONE: "status-done",
}
PRIORITY_ICONS = {
    TaskPriority.LOW: ("bi-chevron-down", "prio-low"),
    TaskPriority.MEDIUM: ("bi-dash-lg", "prio-medium"),
    TaskPriority.HIGH: ("bi-chevron-up", "prio-high"),
    TaskPriority.CRITICAL: ("bi-chevron-double-up", "prio-critical"),
}


def _hours(value) -> str:
    if value is None:
        return "–"
    value = float(value)
    return f"{value:g}h" if value else "0h"


def _date(value, fmt: str = "%d %b %Y") -> str:
    if not value:
        return ""
    if isinstance(value, str):
        return value
    return value.strftime(fmt)


def _relative(value: datetime | date | None) -> str:
    if not value:
        return ""
    if isinstance(value, date) and not isinstance(value, datetime):
        days = (value - date.today()).days
        if days == 0:
            return "today"
        if days == 1:
            return "tomorrow"
        if days == -1:
            return "yesterday"
        return f"in {days} days" if days > 0 else f"{-days} days ago"
    seconds = (datetime.now() - value).total_seconds()
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)} min ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)} h ago"
    if seconds < 86400 * 7:
        return f"{int(seconds // 86400)} d ago"
    return value.strftime("%d %b %Y")


def _query(base: dict | None = None, **updates) -> str:
    """Build a query string, e.g. {{ query(filters, page=2) }}."""
    params = dict(base or {})
    params.update({k: v for k, v in updates.items()})
    clean = {k: v for k, v in params.items() if v not in (None, "", [])}
    return urlencode(clean, doseq=True)


def _json_script(value, element_id: str) -> Markup:
    """Data for JavaScript in a non-executable tag (keeps the Content-Security-Policy strict)."""
    text = json.dumps(value, default=str).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    # Safe: the JSON is escaped above and element_id comes from templates, never from users
    return Markup(f'<script type="application/json" id="{element_id}">{text}</script>')  # noqa: S704


templates.env.globals.update(
    app_name=settings.APP_NAME,
    TaskStatus=TaskStatus,
    TaskPriority=TaskPriority,
    TaskType=TaskType,
    STATUS_CLASSES=STATUS_CLASSES,
    PRIORITY_ICONS=PRIORITY_ICONS,
    query=_query,
    json_script=_json_script,
    today=date.today,
)
templates.env.filters.update(hours=_hours, date=_date, relative=_relative)


def render(request: Request, name: str, context: dict | None = None, status_code: int = 200,
           headers: dict | None = None) -> HTMLResponse:
    ctx = {
        "user": getattr(request.state, "user", None),
        "csrf_token": getattr(request.state, "csrf_token", ""),
        "flash": read_flash(request) if not request.headers.get("hx-request") else None,
        "ai_enabled": ai_enabled(),
        "nav": request.url.path,
    }
    ctx.update(context or {})
    return templates.TemplateResponse(request, name, ctx, status_code=status_code, headers=headers)


def toast(response: Response, message: str, category: str = "success") -> Response:
    """Ask the page to show a small notification (handled in app.js)."""
    response.headers["HX-Trigger"] = json.dumps({"toast": {"message": message, "category": category}})
    return response
