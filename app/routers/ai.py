"""AI Studio: describe a need -> generate -> review and edit -> save to a task."""
from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import studio
from app.ai.provider import AIUnavailable, ai_enabled
from app.ai.schemas import FEATURES
from app.database import get_db
from app.deps import csrf_protect, get_current_user
from app.models import AIGenerationLog, User
from app.routers.forms import redirect, to_int
from app.services import projects as project_service
from app.services import requirements as requirement_service
from app.services.errors import NotFound, ServiceError
from app.services.tasks import TaskFilters, get_task, search_tasks
from app.templating import render

router = APIRouter(prefix="/ai", tags=["ai"], dependencies=[Depends(csrf_protect)], include_in_schema=False)

ITEM_FIELDS = {
    "requirements": ["title", "description", "kind"],
    "uac": ["given", "when", "then"],
    "test_cases": ["title", "preconditions", "steps", "expected_result", "priority"],
}


@router.get("")
def studio_page(request: Request, task_id: str | None = None, feature: str = "uac",
                user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    tid = to_int(task_id)
    task = get_task(db, user, tid) if tid else None
    history = db.scalars(select(AIGenerationLog).where(AIGenerationLog.user_id == user.id)
                         .order_by(AIGenerationLog.id.desc()).limit(10)).all()
    return render(request, "ai/studio.html", {
        "features": FEATURES, "feature": feature if feature in FEATURES else "uac", "task": task,
        "tasks": search_tasks(db, user, TaskFilters(sort="updated"), limit=300),
        "projects": project_service.list_projects(db, user),
        "requirements": requirement_service.list_requirements(db, user, task_id=task.id) if task else [],
        "history": history, "enabled": ai_enabled(),
    })


@router.post("/generate")
def generate(request: Request, feature: str = Form(...), source_text: str = Form(...), task_id: str = Form(""),
             user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    tid = to_int(task_id)
    task = get_task(db, user, tid) if tid else None
    try:
        output, log = studio.generate(db, user, feature, source_text, task)
    except AIUnavailable as exc:
        db.commit()  # keep the failed attempt in the AI log
        return render(request, "ai/_error.html", {"message": str(exc), "unavailable": True})
    except ServiceError as exc:
        db.commit()
        return render(request, "ai/_error.html", {"message": exc.message, "unavailable": False})
    db.commit()
    items = next(iter(output.model_dump().values()))
    requirements = requirement_service.list_requirements(db, user, task_id=task.id) if task else []
    return render(request, "ai/_review.html", {
        "feature": feature, "label": FEATURES[feature][0], "items": items, "log": log, "task": task,
        "projects": project_service.list_projects(db, user), "requirements": requirements,
        "kinds": requirement_service.KINDS,
    })


def _items_from_form(form, feature: str) -> list[dict]:
    items = []
    index = 0
    while f"items-{index}-{ITEM_FIELDS[feature][0]}" in form:
        if form.get(f"items-{index}-keep"):
            item = {name: str(form.get(f"items-{index}-{name}", "")).strip() for name in ITEM_FIELDS[feature]}
            if feature == "test_cases":
                item["steps"] = [s.strip() for s in item["steps"].splitlines() if s.strip()]
            items.append(item)
        index += 1
    return items


@router.post("/save")
async def save(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    form = await request.form()
    log = db.get(AIGenerationLog, to_int(str(form.get("log_id", ""))) or 0)
    if log is None or log.user_id != user.id:
        raise NotFound("Generation not found.")
    feature = log.feature
    task_id = to_int(str(form.get("task_id", "")))
    project_id = to_int(str(form.get("project_id", "")))
    if task_id:
        project_id = get_task(db, user, task_id).project_id
    if not project_id:
        raise ServiceError("Choose a project (or a task) to save into.")
    saved = studio.save_generation(
        db, user, log, feature, _items_from_form(form, feature), project_id, task_id,
        to_int(str(form.get("requirement_id", ""))), str(form.get("requirement_title", "")),
    )
    db.commit()
    count = len(saved) if feature == "requirements" else len(_items_from_form(form, feature))
    target = f"/tasks/{task_id}#requirements" if task_id else f"/requirements/{saved[0].id}"
    return redirect(target, f"Saved {count} AI-generated item(s). Review status is Draft.")


@router.post("/{log_id}/reject")
def reject(log_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    log = db.get(AIGenerationLog, log_id)
    if log is None or log.user_id != user.id:
        raise NotFound("Generation not found.")
    studio.reject(log)
    db.commit()
    return redirect("/ai", "Discarded. Thanks, that feedback improves the prompts.", "info")
