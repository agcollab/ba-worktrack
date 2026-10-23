"""Projects: list, create / edit (PM, Admin), members."""
from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import csrf_protect, get_current_user, require_manager
from app.models import TaskStatus, User
from app.routers.forms import redirect, to_date, to_int
from app.services import audit
from app.services import projects as project_service
from app.services.tasks import TaskFilters, search_tasks
from app.services.users import list_users
from app.templating import render

router = APIRouter(prefix="/projects", tags=["projects"], dependencies=[Depends(csrf_protect)], include_in_schema=False)


@router.get("")
def project_list(request: Request, archived: int = 0, user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    projects = project_service.list_projects(db, user, include_inactive=bool(archived))
    all_tasks = search_tasks(db, user, TaskFilters())
    stats = {}
    for project in projects:
        tasks = [t for t in all_tasks if t.project_id == project.id]
        done = sum(1 for t in tasks if t.status == TaskStatus.DONE)
        stats[project.id] = {"total": len(tasks), "done": done, "overdue": sum(1 for t in tasks if t.is_overdue),
                             "hours": round(sum(t.total_hours for t in tasks), 1),
                             "percent": round(done / len(tasks) * 100) if tasks else 0}
    return render(request, "projects/list.html", {"projects": projects, "stats": stats, "archived": archived})


@router.get("/new")
def new_project(request: Request, user: User = Depends(require_manager), db: Session = Depends(get_db)):
    return render(request, "projects/form.html", {"project": None, "people": list_users(db, include_inactive=False)})


@router.post("")
def create_project(request: Request, key: str = Form(...), name: str = Form(...), description: str = Form(""),
                   owner_id: str = Form(""), start_date: str = Form(""), end_date: str = Form(""),
                   user: User = Depends(require_manager), db: Session = Depends(get_db)):
    project = project_service.save_project(db, user, key, name, description, to_int(owner_id),
                                           to_date(start_date), to_date(end_date))
    audit.record(db, "project.create", user=user, entity=project, details={"key": project.key}, request=request)
    db.commit()
    return redirect(f"/projects/{project.id}", f"Project {project.key} created.")


@router.get("/{project_id}")
def project_detail(request: Request, project_id: int, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    project = project_service.get_project(db, user, project_id)
    tasks = search_tasks(db, user, TaskFilters(project_id=project.id, sort="due"))
    member_ids = {m.user_id for m in project.members}
    candidates = [u for u in list_users(db, include_inactive=False) if u.id not in member_ids] if user.is_manager else []
    by_status = {s: sum(1 for t in tasks if t.status == s) for s in TaskStatus}
    return render(request, "projects/detail.html", {
        "project": project, "tasks": tasks[:15], "task_count": len(tasks), "by_status": by_status,
        "hours": round(sum(t.total_hours for t in tasks), 1), "candidates": candidates,
        "overdue": [t for t in tasks if t.is_overdue],
    })


@router.get("/{project_id}/edit")
def edit_project(request: Request, project_id: int, user: User = Depends(require_manager), db: Session = Depends(get_db)):
    project = project_service.get_project(db, user, project_id)
    return render(request, "projects/form.html", {"project": project, "people": list_users(db, include_inactive=False)})


@router.post("/{project_id}/edit")
def update_project(request: Request, project_id: int, key: str = Form(...), name: str = Form(...),
                   description: str = Form(""), owner_id: str = Form(""), start_date: str = Form(""),
                   end_date: str = Form(""), user: User = Depends(require_manager), db: Session = Depends(get_db)):
    project = project_service.get_project(db, user, project_id)
    project_service.save_project(db, user, key, name, description, to_int(owner_id), to_date(start_date),
                                 to_date(end_date), project=project)
    audit.record(db, "project.update", user=user, entity=project, request=request)
    db.commit()
    return redirect(f"/projects/{project.id}", "Project saved.")


@router.post("/{project_id}/archive")
def toggle_archive(request: Request, project_id: int, user: User = Depends(require_manager), db: Session = Depends(get_db)):
    project = project_service.get_project(db, user, project_id)
    project.is_active = not project.is_active
    audit.record(db, "project.archive" if not project.is_active else "project.restore", user=user, entity=project,
                 request=request)
    db.commit()
    return redirect(f"/projects/{project.id}", "Project archived." if not project.is_active else "Project restored.")


@router.post("/{project_id}/members")
def add_member(request: Request, project_id: int, user_id: str = Form(...), role_in_project: str = Form("BA"),
               user: User = Depends(require_manager), db: Session = Depends(get_db)):
    project = project_service.get_project(db, user, project_id)
    project_service.add_member(db, user, project, to_int(user_id) or 0, role_in_project)
    audit.record(db, "project.add_member", user=user, entity=project, details={"user_id": user_id}, request=request)
    db.commit()
    return redirect(f"/projects/{project_id}#members", "Member added.")


@router.post("/{project_id}/members/{member_id}/remove")
def remove_member(request: Request, project_id: int, member_id: int, user: User = Depends(require_manager),
                  db: Session = Depends(get_db)):
    project = project_service.get_project(db, user, project_id)
    project_service.remove_member(db, user, project, member_id)
    audit.record(db, "project.remove_member", user=user, entity=project, details={"member_id": member_id},
                 request=request)
    db.commit()
    return redirect(f"/projects/{project_id}#members", "Member removed.")
