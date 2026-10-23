"""Admin pages for JIRA / Azure DevOps connections: settings, test, import, sync, mappings, logs."""
from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import csrf_protect, require_admin
from app.integrations import service
from app.integrations.registry import CONNECTORS
from app.models import SyncLog, Task, TaskStatus, User
from app.routers.forms import redirect, to_int
from app.services import audit
from app.services import projects as project_service
from app.templating import render

router = APIRouter(prefix="/integrations", tags=["integrations"], dependencies=[Depends(csrf_protect)],
                   include_in_schema=False)


@router.get("")
def integration_list(request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    integrations = service.list_integrations(db)
    counts = dict(db.execute(select(Task.integration_id, func.count(Task.id)).where(Task.integration_id.is_not(None))
                             .group_by(Task.integration_id)).all())
    return render(request, "integrations/list.html", {"integrations": integrations, "counts": counts,
                                                       "connectors": CONNECTORS})


def _form_context(db: Session, user: User, integration=None, kind: str = "jira") -> dict:
    return {"integration": integration, "kind": integration.kind if integration else kind,
            "projects": project_service.list_projects(db, user), "connectors": CONNECTORS,
            "policies": service.CONFLICT_POLICIES, "config": integration.config if integration else {}}


@router.get("/new")
def new_integration(request: Request, kind: str = "jira", user: User = Depends(require_admin),
                    db: Session = Depends(get_db)):
    return render(request, "integrations/form.html", _form_context(db, user, kind=kind if kind in CONNECTORS else "jira"))


async def _save(request: Request, db: Session, user: User, integration=None):
    form = await request.form()
    data = {k: str(v) for k, v in form.items() if k != "csrf_token"}
    kind = data.get("kind", integration.kind if integration else "jira")
    saved = service.save_integration(
        db, name=data.get("name", ""), kind=kind, base_url=data.get("base_url", ""),
        remote_project=data.get("remote_project", ""), username=data.get("username"), token=data.get("token"),
        local_project_id=to_int(data.get("local_project_id")), config=service.config_from_form(kind, data),
        is_enabled=bool(data.get("is_enabled")), auto_sync=bool(data.get("auto_sync")), integration=integration,
    )
    audit.record(db, "integration.update" if integration else "integration.create", user=user, entity=saved,
                 details={"name": saved.name, "kind": saved.kind, "token_changed": bool(data.get("token"))},
                 request=request)
    db.commit()
    return saved


@router.post("")
async def create_integration(request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    integration = await _save(request, db, user)
    return redirect(f"/integrations/{integration.id}", "Integration saved. Use 'Test connection' to check it.")


@router.get("/{integration_id}")
def integration_detail(request: Request, integration_id: int, user: User = Depends(require_admin),
                       db: Session = Depends(get_db)):
    integration = service.get_integration(db, integration_id)
    logs = db.scalars(select(SyncLog).where(SyncLog.integration_id == integration.id)
                      .order_by(SyncLog.id.desc()).limit(25)).all()
    linked = db.scalar(select(func.count(Task.id)).where(Task.integration_id == integration.id)) or 0
    return render(request, "integrations/detail.html", {
        "integration": integration, "logs": logs, "linked": linked, "mapping": service.status_map(integration),
        "statuses": list(TaskStatus), "policies": service.CONFLICT_POLICIES,
    })


@router.get("/{integration_id}/edit")
def edit_integration(request: Request, integration_id: int, user: User = Depends(require_admin),
                     db: Session = Depends(get_db)):
    return render(request, "integrations/form.html", _form_context(db, user, service.get_integration(db, integration_id)))


@router.post("/{integration_id}/edit")
async def update_integration(request: Request, integration_id: int, user: User = Depends(require_admin),
                             db: Session = Depends(get_db)):
    integration = await _save(request, db, user, service.get_integration(db, integration_id))
    return redirect(f"/integrations/{integration.id}", "Integration saved.")


@router.post("/{integration_id}/test")
def test(integration_id: int, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    integration = service.get_integration(db, integration_id)
    ok, message = service.test_connection(db, integration, user)
    db.commit()
    return redirect(f"/integrations/{integration_id}", message, "success" if ok else "danger")


@router.post("/{integration_id}/import")
def run_import(request: Request, integration_id: int, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    integration = service.get_integration(db, integration_id)
    result = service.import_items(db, integration, user)
    audit.record(db, "integration.import", user=user, entity=integration, details={"summary": result.summary()},
                 request=request)
    db.commit()
    category = {"ok": "success", "partial": "warning"}.get(result.status, "danger")
    message = f"Import finished: {result.summary()}." if result.status != "error" else f"Import failed: {result.errors[0]}"
    return redirect(f"/integrations/{integration_id}", message, category)


@router.post("/{integration_id}/sync")
def run_sync(integration_id: int, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    integration = service.get_integration(db, integration_id)
    result = service.sync_statuses(db, integration, user)
    db.commit()
    category = {"ok": "success", "partial": "warning"}.get(result.status, "danger")
    message = f"Status sync finished: {result.summary()}." if result.status != "error" else f"Sync failed: {result.errors[0]}"
    return redirect(f"/integrations/{integration_id}", message, category)


@router.post("/{integration_id}/mappings")
async def save_mappings(request: Request, integration_id: int, user: User = Depends(require_admin),
                        db: Session = Depends(get_db)):
    integration = service.get_integration(db, integration_id)
    form = await request.form()
    if form.get("reset"):
        service.reset_default_mappings(db, integration)
    else:
        service.save_status_mappings(db, integration, {s.value: str(form.get(f"status-{s.name}", "")) for s in TaskStatus})
    audit.record(db, "integration.mappings", user=user, entity=integration, request=request)
    db.commit()
    return redirect(f"/integrations/{integration_id}#mapping", "Status mapping saved.")


@router.post("/{integration_id}/delete")
def delete_integration(request: Request, integration_id: int, user: User = Depends(require_admin),
                       db: Session = Depends(get_db)):
    integration = service.get_integration(db, integration_id)
    audit.record(db, "integration.delete", user=user, entity=integration, details={"name": integration.name},
                 request=request)
    for task in db.scalars(select(Task).where(Task.integration_id == integration.id)):
        task.integration_id = None  # keep the tasks and their external ids, just unlink
    db.delete(integration)
    db.commit()
    return redirect("/integrations", "Integration deleted. Imported tasks were kept.")
