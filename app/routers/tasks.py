"""Task pages: list with live search, detail, create / edit, status changes (HTMX),
comments, attachments, the Kanban board, and links to JIRA / Azure DevOps."""
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.provider import ai_enabled
from app.database import get_db
from app.deps import csrf_protect, get_current_user
from app.integrations import service as integration_service
from app.models import Attachment, Integration, TaskComment, TaskPriority, TaskStatus, TaskType, User
from app.routers.forms import redirect, to_date, to_float, to_int
from app.services import audit, time_tracking
from app.services import projects as project_service
from app.services import requirements as requirement_service
from app.services import tasks as task_service
from app.services.errors import NotFound, ServiceError
from app.services.tasks import TaskFilters
from app.templating import render, toast

router = APIRouter(prefix="/tasks", tags=["tasks"], dependencies=[Depends(csrf_protect)], include_in_schema=False)
board_router = APIRouter(dependencies=[Depends(csrf_protect)], include_in_schema=False)

PAGE_SIZE = 50


def parse_filters(q: str | None, project_id: str | None, status: list[str] | None, assignee_id: str | None,
                  task_type: str | None, priority: str | None, overdue: str | None, source: str | None,
                  sort: str | None) -> TaskFilters:
    return TaskFilters(
        q=(q or "").strip() or None, project_id=to_int(project_id), status=[s for s in (status or []) if s],
        assignee_id=to_int(assignee_id), task_type=task_type or None, priority=priority or None,
        overdue=overdue in ("1", "true", "on"), source=source or None, sort=sort or "updated",
    )


def filter_dependency(
    q: str | None = None, project_id: str | None = None, status: list[str] | None = Query(None),
    assignee_id: str | None = None, task_type: str | None = None, priority: str | None = None,
    overdue: str | None = None, source: str | None = None, sort: str | None = None,
) -> TaskFilters:
    return parse_filters(q, project_id, status, assignee_id, task_type, priority, overdue, source, sort)


def form_options(db: Session, user: User) -> dict:
    projects = project_service.list_projects(db, user)
    people: dict[int, User] = {}
    for project in projects:
        for member in project_service.project_members(project):
            people[member.id] = member
    return {"projects": projects, "people": sorted(people.values(), key=lambda u: u.full_name)}


@router.get("")
def task_list(request: Request, page: int = 1, filters: TaskFilters = Depends(filter_dependency),
              user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    page = max(1, page)
    total = task_service.count_tasks(db, user, filters)
    rows = task_service.search_tasks(db, user, filters, limit=PAGE_SIZE, offset=(page - 1) * PAGE_SIZE)
    context = {"tasks": rows, "filters": filters, "fq": filters.as_query(), "total": total, "page": page,
               "pages": max(1, -(-total // PAGE_SIZE)), **form_options(db, user)}
    if request.headers.get("hx-request") and request.headers.get("hx-target") == "task-results":
        return render(request, "tasks/_results.html", context)
    return render(request, "tasks/list.html", context)


@router.get("/new")
def new_task(request: Request, project_id: str | None = None, user: User = Depends(get_current_user),
             db: Session = Depends(get_db)):
    options = form_options(db, user)
    if not options["projects"]:
        return redirect("/projects", "You need to be on a project before creating tasks.", "warning")
    return render(request, "tasks/form.html", {"task": None, "selected_project": to_int(project_id), **options})


@router.post("")
def create_task(request: Request, project_id: str = Form(...), title: str = Form(...), description: str = Form(""),
                priority: TaskPriority = Form(TaskPriority.MEDIUM), task_type: TaskType = Form(TaskType.OTHER),
                assignee_id: str = Form(""), estimate_hours: str = Form(""), due_date: str = Form(""),
                user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    task = task_service.create_task(
        db, user, to_int(project_id) or 0, title, description, priority, task_type, to_int(assignee_id),
        to_float(estimate_hours), to_date(due_date),
    )
    db.commit()
    return redirect(f"/tasks/{task.id}", f"Task {task.key} created.")


def _detail_context(db: Session, user: User, task) -> dict:
    integrations = list(db.scalars(select(Integration).where(Integration.is_enabled.is_(True)).order_by(Integration.name)))
    return {
        "task": task,
        "next_statuses": task_service.allowed_next(task),
        "requirements": requirement_service.list_requirements(db, user, task_id=task.id),
        "integrations": integrations,
        "timer": time_tracking.running_timer(db, user),
        "can_edit": task_service.can_edit(user, task),
        "ai_enabled": ai_enabled(),
    }


@router.get("/{task_id}")
def task_detail(request: Request, task_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    task = task_service.get_task(db, user, task_id)
    return render(request, "tasks/detail.html", _detail_context(db, user, task))


@router.get("/{task_id}/edit")
def edit_task(request: Request, task_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    task = task_service.get_task(db, user, task_id)
    return render(request, "tasks/form.html", {"task": task, "selected_project": task.project_id,
                                                **form_options(db, user)})


@router.post("/{task_id}/edit")
def update_task(task_id: int, project_id: str = Form(""), title: str = Form(...), description: str = Form(""),
                priority: TaskPriority = Form(...), task_type: TaskType = Form(...), assignee_id: str = Form(""),
                estimate_hours: str = Form(""), due_date: str = Form(""),
                user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    task = task_service.get_task(db, user, task_id)
    task_service.update_task(db, user, task, title, description, priority, task_type, to_int(assignee_id),
                             to_float(estimate_hours), to_date(due_date), to_int(project_id))
    db.commit()
    return redirect(f"/tasks/{task.id}", "Task saved.")


@router.post("/{task_id}/status")
def set_status(request: Request, task_id: int, status: TaskStatus = Form(...),
               user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    task = task_service.get_task(db, user, task_id)
    task_service.change_status(db, user, task, status)
    db.commit()
    if request.headers.get("hx-request"):
        task = task_service.get_task(db, user, task_id)
        response = render(request, "tasks/_status.html", {"task": task, "next_statuses": task_service.allowed_next(task)})
        response.headers["HX-Trigger-After-Swap"] = "statusChanged"
        return toast(response, f"{task.key} moved to {task.status}.")
    return redirect(f"/tasks/{task_id}", f"Moved to {status}.")


@router.post("/{task_id}/delete")
def delete_task(request: Request, task_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    task = task_service.get_task(db, user, task_id)
    key = task.key
    audit.record(db, "task.delete", user=user, entity=task, details={"key": key, "title": task.title}, request=request)
    task_service.delete_task(db, user, task)
    db.commit()
    return redirect("/tasks", f"Task {key} deleted.")


# ---- comments -------------------------------------------------------------------

@router.post("/{task_id}/comments")
def add_comment(request: Request, task_id: int, body: str = Form(...), user: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    task = task_service.get_task(db, user, task_id)
    task_service.add_comment(db, user, task, body)
    db.commit()
    if request.headers.get("hx-request"):
        task = task_service.get_task(db, user, task_id)
        return render(request, "tasks/_comments.html", {"task": task})
    return redirect(f"/tasks/{task_id}#comments")


@router.post("/{task_id}/comments/{comment_id}/delete")
def delete_comment(request: Request, task_id: int, comment_id: int, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    task_service.get_task(db, user, task_id)
    comment = db.get(TaskComment, comment_id)
    if comment is None or comment.task_id != task_id:
        raise NotFound("Comment not found.")
    task_service.delete_comment(db, user, comment)
    db.commit()
    if request.headers.get("hx-request"):
        return render(request, "tasks/_comments.html", {"task": task_service.get_task(db, user, task_id)})
    return redirect(f"/tasks/{task_id}#comments")


# ---- attachments ------------------------------------------------------------------

@router.post("/{task_id}/attachments")
async def upload(task_id: int, file: UploadFile = File(...), user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    task = task_service.get_task(db, user, task_id)
    content = await file.read()
    task_service.save_attachment(db, user, task, file.filename or "file", content, file.content_type)
    db.commit()
    return redirect(f"/tasks/{task_id}#files", f"{file.filename} uploaded.")


def _attachment(db: Session, user: User, task_id: int, attachment_id: int) -> Attachment:
    task_service.get_task(db, user, task_id)
    attachment = db.get(Attachment, attachment_id)
    if attachment is None or attachment.task_id != task_id:
        raise NotFound("File not found.")
    return attachment


@router.get("/{task_id}/attachments/{attachment_id}")
def download(task_id: int, attachment_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    attachment = _attachment(db, user, task_id, attachment_id)
    if not Path(attachment.stored_path).exists():
        raise NotFound("The file is missing from storage.")
    return FileResponse(attachment.stored_path, filename=attachment.filename,
                        media_type=attachment.content_type or "application/octet-stream")


@router.post("/{task_id}/attachments/{attachment_id}/delete")
def delete_upload(task_id: int, attachment_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    attachment = _attachment(db, user, task_id, attachment_id)
    task_service.delete_attachment(db, user, attachment)
    db.commit()
    return redirect(f"/tasks/{task_id}#files", "File deleted.")


# ---- JIRA / Azure DevOps ------------------------------------------------------------

@router.post("/{task_id}/push")
def push_to_integration(request: Request, task_id: int, integration_id: str = Form(...),
                        user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    task = task_service.get_task(db, user, task_id)
    integration = integration_service.get_integration(db, to_int(integration_id) or 0)
    item = integration_service.push_task(db, integration, task, user)
    audit.record(db, "integration.push_task", user=user, entity=task,
                 details={"integration": integration.name, "external_id": item.external_id}, request=request)
    db.commit()
    return redirect(f"/tasks/{task_id}", f"Created {integration.kind.upper()} item {item.external_id}.")


@router.post("/{task_id}/push-requirements")
def push_requirements(request: Request, task_id: int, user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    task = task_service.get_task(db, user, task_id)
    count = integration_service.push_requirements(db, task, user)
    db.commit()
    return redirect(f"/tasks/{task_id}", f"Posted {count} requirement(s) with UAC and test cases to {task.external_id}.")


@router.post("/{task_id}/sync")
def sync_one(task_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    task = task_service.get_task(db, user, task_id)
    if not task.integration_id:
        raise ServiceError("This task is not linked to JIRA or Azure DevOps.")
    integration = integration_service.get_integration(db, task.integration_id)
    result = integration_service.sync_statuses(db, integration, user)
    db.commit()
    category = "success" if result.status == "ok" else "warning"
    return redirect(f"/tasks/{task_id}", f"Sync finished: {result.summary()}.", category)


# ---- Kanban board -----------------------------------------------------------------------

@board_router.get("/board")
def board(request: Request, project_id: str | None = None, assignee_id: str | None = None, q: str | None = None,
          user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    filters = TaskFilters(project_id=to_int(project_id), assignee_id=to_int(assignee_id), q=q, sort="priority")
    tasks = task_service.search_tasks(db, user, filters, limit=500)
    columns = {status: [t for t in tasks if t.status == status] for status in TaskStatus}
    return render(request, "tasks/board.html", {"columns": columns, "filters": filters,
                                                 "workflow": {s.value: [n.value for n in task_service.WORKFLOW[s]]
                                                              for s in TaskStatus},
                                                 **form_options(db, user)})


@board_router.get("/tasks-search", response_class=HTMLResponse)
def quick_search(request: Request, q: str = "", user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Top-bar search: the first few matching tasks as a dropdown."""
    results = task_service.search_tasks(db, user, TaskFilters(q=q), limit=8) if len(q.strip()) >= 2 else []
    return render(request, "tasks/_quick_search.html", {"results": results, "q": q})
