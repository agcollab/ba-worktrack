"""Requirements with their acceptance criteria and test cases."""
from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import csrf_protect, get_current_user
from app.models import AcceptanceCriterion, TestCase, TestCaseStatus, User
from app.routers.forms import redirect, to_int
from app.services import projects as project_service
from app.services import requirements as service
from app.services.errors import NotFound
from app.services.tasks import TaskFilters, get_task, search_tasks
from app.templating import render

router = APIRouter(prefix="/requirements", tags=["requirements"], dependencies=[Depends(csrf_protect)],
                   include_in_schema=False)


@router.get("")
def requirement_list(request: Request, project_id: str | None = None, q: str | None = None,
                     user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    pid = to_int(project_id)
    requirements = service.list_requirements(db, user, project_id=pid, q=q)
    return render(request, "requirements/list.html", {
        "requirements": requirements, "projects": project_service.list_projects(db, user),
        "project_id": pid, "q": q or "", "fq": {"project_id": pid, "q": q},
    })


def _form_context(db: Session, user: User, requirement=None, task_id: int | None = None, project_id: int | None = None):
    return {"requirement": requirement, "projects": project_service.list_projects(db, user),
            "tasks": search_tasks(db, user, TaskFilters(sort="updated"), limit=300),
            "kinds": service.KINDS, "statuses": service.STATUSES, "task_id": task_id, "project_id": project_id}


@router.get("/new")
def new_requirement(request: Request, task_id: str | None = None, project_id: str | None = None,
                    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    tid, pid = to_int(task_id), to_int(project_id)
    if tid and not pid:
        pid = get_task(db, user, tid).project_id
    return render(request, "requirements/form.html", _form_context(db, user, task_id=tid, project_id=pid))


@router.post("")
def create_requirement(project_id: str = Form(...), title: str = Form(...), description: str = Form(""),
                       kind: str = Form("Functional"), status: str = Form("Draft"), task_id: str = Form(""),
                       user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    requirement = service.save_requirement(db, user, to_int(project_id) or 0, title, description, kind, status,
                                           to_int(task_id))
    db.commit()
    return redirect(f"/requirements/{requirement.id}", "Requirement created.")


@router.get("/{requirement_id}")
def requirement_detail(request: Request, requirement_id: int, user: User = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    requirement = service.get_requirement(db, user, requirement_id)
    return render(request, "requirements/detail.html", {"requirement": requirement, "statuses": service.STATUSES,
                                                         "test_statuses": list(TestCaseStatus)})


@router.get("/{requirement_id}/edit")
def edit_requirement(request: Request, requirement_id: int, user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    requirement = service.get_requirement(db, user, requirement_id)
    return render(request, "requirements/form.html", _form_context(db, user, requirement, requirement.task_id,
                                                                   requirement.project_id))


@router.post("/{requirement_id}/edit")
def update_requirement(requirement_id: int, project_id: str = Form(...), title: str = Form(...),
                       description: str = Form(""), kind: str = Form("Functional"), status: str = Form("Draft"),
                       task_id: str = Form(""), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    requirement = service.get_requirement(db, user, requirement_id)
    service.save_requirement(db, user, to_int(project_id) or 0, title, description, kind, status, to_int(task_id),
                             source=requirement.source, requirement=requirement)
    db.commit()
    return redirect(f"/requirements/{requirement_id}", "Requirement saved.")


@router.post("/{requirement_id}/delete")
def delete_requirement(requirement_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    requirement = service.get_requirement(db, user, requirement_id)
    db.delete(requirement)
    db.commit()
    return redirect("/requirements", "Requirement deleted.")


@router.post("/{requirement_id}/criteria")
def add_criterion(requirement_id: int, given_text: str = Form(""), when_text: str = Form(""),
                  then_text: str = Form(...), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    requirement = service.get_requirement(db, user, requirement_id)
    service.add_criterion(db, requirement, given_text, when_text, then_text)
    db.commit()
    return redirect(f"/requirements/{requirement_id}#criteria", "Criterion added.")


@router.post("/{requirement_id}/criteria/{criterion_id}/delete")
def delete_criterion(requirement_id: int, criterion_id: int, user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    service.get_requirement(db, user, requirement_id)
    criterion = db.get(AcceptanceCriterion, criterion_id)
    if criterion is None or criterion.requirement_id != requirement_id:
        raise NotFound("Criterion not found.")
    db.delete(criterion)
    db.commit()
    return redirect(f"/requirements/{requirement_id}#criteria", "Criterion removed.")


@router.post("/{requirement_id}/test-cases")
def add_test_case(requirement_id: int, title: str = Form(...), preconditions: str = Form(""), steps: str = Form(...),
                  expected_result: str = Form(...), priority: str = Form("Medium"),
                  user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    requirement = service.get_requirement(db, user, requirement_id)
    service.add_test_case(db, requirement, title, steps, expected_result, preconditions, priority)
    db.commit()
    return redirect(f"/requirements/{requirement_id}#tests", "Test case added.")


def _test_case(db: Session, user: User, requirement_id: int, test_case_id: int) -> TestCase:
    service.get_requirement(db, user, requirement_id)
    test_case = db.get(TestCase, test_case_id)
    if test_case is None or test_case.requirement_id != requirement_id:
        raise NotFound("Test case not found.")
    return test_case


@router.post("/{requirement_id}/test-cases/{test_case_id}/status")
def test_status(request: Request, requirement_id: int, test_case_id: int, status: str = Form(...),
                user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    test_case = _test_case(db, user, requirement_id, test_case_id)
    service.set_test_status(test_case, status)
    db.commit()
    return redirect(f"/requirements/{requirement_id}#tests", f"Marked '{test_case.title}' as {status}.")


@router.post("/{requirement_id}/test-cases/{test_case_id}/delete")
def delete_test_case(requirement_id: int, test_case_id: int, user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    db.delete(_test_case(db, user, requirement_id, test_case_id))
    db.commit()
    return redirect(f"/requirements/{requirement_id}#tests", "Test case removed.")
