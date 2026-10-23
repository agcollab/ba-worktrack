"""The FastAPI application. Start it from the repository root with:

    uvicorn app.main:app --reload

then open http://127.0.0.1:8000 (app) and http://127.0.0.1:8000/docs (API docs).
"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException

from app import scheduler
from app.config import INSECURE_SECRET, settings
from app.database import SessionLocal
from app.deps import LoginRequired, get_optional_user, is_api_request
from app.middleware import AppMiddleware, flash
from app.routers import (
    admin,
    ai,
    api,
    auth,
    dashboard,
    exports,
    health,
    integrations,
    projects,
    reports,
    requirements,
    tasks,
    time_tracking,
)
from app.services.errors import ServiceError
from app.templating import render, toast

STATIC_DIR = Path(__file__).parent / "static"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if settings.is_production and settings.SECRET_KEY == INSECURE_SECRET:
        raise RuntimeError("Set SECRET_KEY in the environment before running in production.")
    if settings.SECRET_KEY == INSECURE_SECRET:
        logger.warning("SECRET_KEY is the development default; set a real one in .env")
    Path(settings.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
    if settings.FIRST_ADMIN_EMAIL and settings.FIRST_ADMIN_PASSWORD:
        from app.services.users import bootstrap_admin

        try:
            with SessionLocal() as db:
                if bootstrap_admin(db, settings.FIRST_ADMIN_EMAIL, settings.FIRST_ADMIN_PASSWORD):
                    logger.info("Created first admin %s", settings.FIRST_ADMIN_EMAIL)
        except Exception:  # tables missing: migrations not run yet
            logger.exception("Could not create the first admin; did you run 'alembic upgrade head'?")
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    description="Task, time and requirements tracking for Business Analysts. "
                "Authenticate with POST /api/v1/auth/token and send 'Authorization: Bearer <token>'.",
    lifespan=lifespan,
)
app.add_middleware(AppMiddleware)

# Files under app/static are served at /static/... (CSS, JavaScript, fonts)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

for module in (health, auth, dashboard, tasks, time_tracking, projects, requirements, ai, reports, exports,
               integrations, admin, api):
    app.include_router(module.router)
app.include_router(tasks.board_router)


def _is_htmx(request: Request) -> bool:
    return request.headers.get("hx-request") == "true"


@app.exception_handler(LoginRequired)
async def login_required_handler(request: Request, _exc: LoginRequired) -> Response:
    target = "/login"
    if request.method == "GET" and request.url.path not in ("/", "/login"):
        target += "?next=" + request.url.path
    if _is_htmx(request):
        return Response(status_code=204, headers={"HX-Redirect": target})
    return RedirectResponse(target, status_code=303)


@app.exception_handler(ServiceError)
async def service_error_handler(request: Request, exc: ServiceError) -> Response:
    """A broken business rule: a message for the user, never a stack trace."""
    if is_api_request(request):
        return JSONResponse({"detail": exc.message}, status_code=exc.status_code)
    if _is_htmx(request):
        response = Response(status_code=200, headers={"HX-Reswap": "none"})
        return toast(response, exc.message, "danger")
    if request.method != "GET":
        back = request.headers.get("referer") or "/"
        response = RedirectResponse(back, status_code=303)
        flash(response, exc.message, "danger")
        return response
    return render(request, "error.html", {"code": exc.status_code, "message": exc.message},
                  status_code=exc.status_code)


def _attach_user(request: Request) -> None:
    """Error pages for unknown URLs run without the login dependency; find the user so
    the page keeps its normal layout."""
    if getattr(request.state, "user", None) is not None:
        return
    with SessionLocal() as db:
        user = get_optional_user(request, db)
        if user is not None:
            db.expunge(user)


@app.exception_handler(HTTPException)
async def http_error_handler(request: Request, exc: HTTPException) -> Response:
    _attach_user(request)
    if is_api_request(request) or request.url.path in ("/health", "/docs", "/openapi.json"):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)
    if _is_htmx(request):
        return toast(Response(status_code=200, headers={"HX-Reswap": "none"}), str(exc.detail), "danger")
    messages = {403: "You don't have access to this page.", 404: "We couldn't find that page."}
    detail = exc.detail
    if not isinstance(detail, str) or detail == "Not Found":
        detail = messages.get(exc.status_code, "Something went wrong.")
    return render(request, "error.html", {"code": exc.status_code, "message": detail}, status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> Response:
    if is_api_request(request):
        return JSONResponse({"detail": exc.errors()}, status_code=422)
    first = exc.errors()[0] if exc.errors() else {}
    field = ".".join(str(p) for p in first.get("loc", [])[1:])
    message = f"Please check {field or 'the form'}: {first.get('msg', 'invalid value')}."
    if _is_htmx(request):
        return toast(Response(status_code=200, headers={"HX-Reswap": "none"}), message, "danger")
    if request.method != "GET":
        response = RedirectResponse(request.headers.get("referer") or "/", status_code=303)
        flash(response, message, "danger")
        return response
    return render(request, "error.html", {"code": 422, "message": message}, status_code=422)


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception) -> Response:
    logger.exception("Unhandled error on %s %s (request %s)", request.method, request.url.path,
                     getattr(request.state, "request_id", "-"))
    if is_api_request(request):
        return JSONResponse({"detail": "Internal server error"}, status_code=500)
    return render(request, "error.html", {"code": 500, "message": "Something went wrong on our side. "
                                          f"Reference: {getattr(request.state, 'request_id', '-')}"},
                  status_code=500)
