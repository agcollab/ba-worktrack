"""Admin: user management (create, edit, roles, deactivate, reset password, unlock) and the audit log."""
import json
import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app import scheduler
from app.config import settings
from app.database import get_db
from app.deps import csrf_protect, require_admin
from app.models import AuditLog, User
from app.routers.forms import redirect, to_float
from app.services import audit, users
from app.services import item_types as item_type_service
from app.templating import render

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(csrf_protect)], include_in_schema=False)


@router.get("/users")
def user_list(request: Request, q: str = "", admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    people = users.list_users(db)
    if q:
        needle = q.lower()
        people = [u for u in people if needle in u.full_name.lower() or needle in u.email.lower()]
    return render(request, "admin/users.html", {"people": people, "q": q, "roles": users.ROLE_NAMES,
                                                 "now": datetime.now()})


@router.get("/users/new")
def new_user(request: Request, admin: User = Depends(require_admin)):
    return render(request, "admin/user_form.html", {"person": None, "roles": users.ROLE_DESCRIPTIONS,
                                                     "suggested_password": _temp_password()})


def _temp_password() -> str:
    return secrets.token_urlsafe(9) + "7a"


@router.post("/users")
async def create_user(request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    form = await request.form()
    person = users.create_user(
        db, email=str(form.get("email", "")), full_name=str(form.get("full_name", "")),
        password=str(form.get("password", "")), role_names=[str(r) for r in form.getlist("roles")],
        job_title=str(form.get("job_title", "")) or None,
        weekly_capacity_hours=to_float(str(form.get("weekly_capacity_hours", ""))) or 40,
        must_change_password=True,
    )
    audit.record(db, "user.create", user=admin, entity=person, details={"email": person.email,
                                                                         "roles": person.role_names}, request=request)
    db.commit()
    return redirect(f"/admin/users/{person.id}", f"User {person.email} created. They must change the password at first login.")


@router.get("/users/{user_id}")
def edit_user(request: Request, user_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    person = users.get_user(db, user_id)
    return render(request, "admin/user_form.html", {"person": person, "roles": users.ROLE_DESCRIPTIONS,
                                                     "suggested_password": _temp_password()})


@router.post("/users/{user_id}")
async def update_user(request: Request, user_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    person = users.get_user(db, user_id)
    form = await request.form()
    before = {"email": person.email, "roles": person.role_names}
    users.update_user(db, person, str(form.get("full_name", "")), str(form.get("email", "")),
                      [str(r) for r in form.getlist("roles")], str(form.get("job_title", "")) or None,
                      to_float(str(form.get("weekly_capacity_hours", ""))) or 40, admin)
    audit.record(db, "user.update", user=admin, entity=person,
                 details={"before": before, "after": {"email": person.email, "roles": person.role_names}},
                 request=request)
    db.commit()
    return redirect(f"/admin/users/{user_id}", "User saved.")


@router.post("/users/{user_id}/active")
def toggle_active(request: Request, user_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    person = users.get_user(db, user_id)
    users.set_active(db, person, not person.is_active, admin)
    audit.record(db, "user.activate" if person.is_active else "user.deactivate", user=admin, entity=person,
                 request=request)
    db.commit()
    return redirect(f"/admin/users/{user_id}", f"{person.full_name} {'activated' if person.is_active else 'deactivated'}.")


@router.post("/users/{user_id}/reset-password")
def reset_password(request: Request, user_id: int, new_password: str = Form(...), admin: User = Depends(require_admin),
                   db: Session = Depends(get_db)):
    person = users.get_user(db, user_id)
    users.reset_password(person, new_password)
    audit.record(db, "user.reset_password", user=admin, entity=person, request=request)
    db.commit()
    return redirect(f"/admin/users/{user_id}", "Password reset. Share it securely; they must change it at next login.")


@router.post("/users/{user_id}/unlock")
def unlock(request: Request, user_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    person = users.get_user(db, user_id)
    users.unlock(person)
    audit.record(db, "user.unlock", user=admin, entity=person, request=request)
    db.commit()
    return redirect(f"/admin/users/{user_id}", "Account unlocked.")


@router.get("/item-types")
def item_type_list(request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return render(request, "admin/item_types.html", {"item_types": item_type_service.list_item_types(db)})


@router.post("/item-types/{item_type_id}")
async def set_item_type_mode(request: Request, item_type_id: int, admin: User = Depends(require_admin),
                             db: Session = Depends(get_db)):
    item_type = item_type_service.get_item_type(db, item_type_id)
    read_only = "1" in (await request.form()).getlist("read_only")
    item_type_service.set_read_only(db, admin, item_type, read_only, request=request)
    db.commit()
    mode = "read-only" if read_only else "editable"
    return redirect("/admin/item-types", f"{item_type.source_label} {item_type.name} is now {mode}.")


@router.get("/audit")
def audit_log(request: Request, action: str = "", page: int = 1, admin: User = Depends(require_admin),
              db: Session = Depends(get_db)):
    page = max(1, page)
    query = select(AuditLog).options(joinedload(AuditLog.user)).order_by(AuditLog.id.desc())
    count_query = select(func.count(AuditLog.id))
    if action:
        query = query.where(AuditLog.action.like(f"{action}%"))
        count_query = count_query.where(AuditLog.action.like(f"{action}%"))
    total = db.scalar(count_query) or 0
    rows = db.scalars(query.limit(50).offset((page - 1) * 50)).all()
    actions = sorted({a.split(".")[0] for a in db.scalars(select(AuditLog.action).distinct())})
    return render(request, "admin/audit.html", {
        "rows": [(r, json.loads(r.details) if r.details else None) for r in rows], "action": action,
        "actions": actions, "page": page, "pages": max(1, -(-total // 50)), "total": total,
    })


@router.get("/system")
def system(request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return render(request, "admin/system.html", {"jobs": scheduler.jobs(), "settings": settings})
