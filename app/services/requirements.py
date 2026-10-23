"""Requirements with their acceptance criteria (Given / When / Then) and test cases."""
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import AcceptanceCriterion, Requirement, TaskPriority, TestCase, TestCaseStatus, User
from app.services.errors import NotFound, ServiceError
from app.services.projects import get_project, visible_project_ids

KINDS = ["Functional", "Non-functional", "Business rule", "Data", "Integration"]
STATUSES = ["Draft", "In Review", "Approved", "Rejected"]


def list_requirements(db: Session, user: User, project_id: int | None = None, task_id: int | None = None,
                      q: str | None = None) -> list[Requirement]:
    query = (
        select(Requirement)
        .options(selectinload(Requirement.criteria), selectinload(Requirement.test_cases),
                 selectinload(Requirement.project), selectinload(Requirement.task))
        .order_by(Requirement.project_id, Requirement.id.desc())
    )
    ids = visible_project_ids(db, user)
    if ids is not None:
        query = query.where(Requirement.project_id.in_(ids))
    if project_id:
        query = query.where(Requirement.project_id == project_id)
    if task_id:
        query = query.where(Requirement.task_id == task_id)
    if q:
        query = query.where(Requirement.title.ilike(f"%{q}%") | Requirement.description.ilike(f"%{q}%"))
    return list(db.scalars(query))


def get_requirement(db: Session, user: User, requirement_id: int) -> Requirement:
    requirement = db.scalar(
        select(Requirement)
        .options(selectinload(Requirement.criteria), selectinload(Requirement.test_cases))
        .where(Requirement.id == requirement_id)
    )
    if requirement is None:
        raise NotFound("Requirement not found.")
    get_project(db, user, requirement.project_id)
    return requirement


def save_requirement(db: Session, user: User, project_id: int, title: str, description: str | None,
                     kind: str = "Functional", status: str = "Draft", task_id: int | None = None,
                     source: str = "Manual", requirement: Requirement | None = None) -> Requirement:
    get_project(db, user, project_id)
    if not title.strip():
        raise ServiceError("Requirement title is required.")
    if kind not in KINDS:
        kind = "Functional"
    if status not in STATUSES:
        status = "Draft"
    if requirement is None:
        requirement = Requirement(created_by_id=user.id, source=source)
        db.add(requirement)
    requirement.project_id = project_id
    requirement.task_id = task_id or None
    requirement.title = title.strip()[:200]
    requirement.description = (description or "").strip() or None
    requirement.kind, requirement.status = kind, status
    db.flush()
    return requirement


def add_criterion(db: Session, requirement: Requirement, given: str | None, when: str | None, then: str) -> AcceptanceCriterion:
    if not (then or "").strip():
        raise ServiceError("The 'Then' part of a criterion is required.")
    position = max((c.position for c in requirement.criteria), default=0) + 1
    criterion = AcceptanceCriterion(
        requirement_id=requirement.id, position=position,
        given_text=(given or "").strip() or None, when_text=(when or "").strip() or None, then_text=then.strip(),
    )
    db.add(criterion)
    requirement.criteria.append(criterion)
    db.flush()
    return criterion


def add_test_case(db: Session, requirement: Requirement, title: str, steps: str, expected_result: str,
                  preconditions: str | None = None, priority: str = "Medium") -> TestCase:
    if not title.strip() or not steps.strip() or not expected_result.strip():
        raise ServiceError("A test case needs a title, steps and an expected result.")
    test_case = TestCase(
        requirement_id=requirement.id, title=title.strip()[:200], steps=steps.strip(),
        expected_result=expected_result.strip(), preconditions=(preconditions or "").strip() or None,
        priority=TaskPriority(priority) if priority in TaskPriority._value2member_map_ else TaskPriority.MEDIUM,
    )
    db.add(test_case)
    requirement.test_cases.append(test_case)
    db.flush()
    return test_case


def set_test_status(test_case: TestCase, status: str) -> None:
    if status not in TestCaseStatus._value2member_map_:
        raise ServiceError("Unknown test status.")
    test_case.status = TestCaseStatus(status)


def format_criterion(c: AcceptanceCriterion) -> str:
    parts = []
    if c.given_text:
        parts.append(f"Given {c.given_text}")
    if c.when_text:
        parts.append(f"When {c.when_text}")
    parts.append(f"Then {c.then_text}")
    return "\n".join(parts)
