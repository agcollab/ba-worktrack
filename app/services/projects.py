"""Projects and their members. Admins and PMs see every project; BAs see their own."""
import re

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Project, ProjectMember, User
from app.services.errors import Forbidden, NotFound, ServiceError

KEY_PATTERN = re.compile(r"^[A-Z][A-Z0-9]{1,9}$")


def visible_project_ids(db: Session, user: User) -> list[int] | None:
    """None means "all projects" (Admin / PM)."""
    if user.is_manager:
        return None
    return list(db.scalars(select(ProjectMember.project_id).where(ProjectMember.user_id == user.id)))


def list_projects(db: Session, user: User, include_inactive: bool = False) -> list[Project]:
    query = (
        select(Project)
        .options(selectinload(Project.members).selectinload(ProjectMember.user), selectinload(Project.owner))
        .order_by(Project.name)
    )
    ids = visible_project_ids(db, user)
    if ids is not None:
        query = query.where(Project.id.in_(ids))
    if not include_inactive:
        query = query.where(Project.is_active.is_(True))
    return list(db.scalars(query))


def get_project(db: Session, user: User, project_id: int) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise NotFound("Project not found.")
    ids = visible_project_ids(db, user)
    if ids is not None and project.id not in ids:
        raise Forbidden("You are not a member of this project.")
    return project


def can_manage(user: User) -> bool:
    return user.is_manager


def save_project(
    db: Session,
    actor: User,
    key: str,
    name: str,
    description: str | None = None,
    owner_id: int | None = None,
    start_date=None,
    end_date=None,
    project: Project | None = None,
) -> Project:
    if not can_manage(actor):
        raise Forbidden("Only PMs and admins manage projects.")
    key = key.strip().upper()
    name = name.strip()
    if not KEY_PATTERN.match(key):
        raise ServiceError("Key must be 2-10 capital letters or digits, starting with a letter (e.g. PAY).")
    if not name:
        raise ServiceError("Project name is required.")
    if start_date and end_date and end_date < start_date:
        raise ServiceError("End date must be after the start date.")
    for other in db.scalars(select(Project).where((Project.key == key) | (Project.name == name))):
        if project is None or other.id != project.id:
            raise ServiceError("Another project already uses that key or name.")
    if project is None:
        project = Project(key=key, name=name)
        db.add(project)
    project.key, project.name = key, name
    project.description = description or None
    project.owner_id = owner_id or None
    project.start_date, project.end_date = start_date, end_date
    db.flush()
    if owner_id and not any(m.user_id == owner_id for m in project.members):
        db.add(ProjectMember(project_id=project.id, user_id=owner_id, role_in_project="PM"))
        db.flush()
    return project


def add_member(db: Session, actor: User, project: Project, user_id: int, role_in_project: str = "BA") -> None:
    if not can_manage(actor):
        raise Forbidden("Only PMs and admins manage members.")
    if db.get(User, user_id) is None:
        raise NotFound("User not found.")
    if any(m.user_id == user_id for m in project.members):
        raise ServiceError("That user is already a member.")
    db.add(ProjectMember(project_id=project.id, user_id=user_id, role_in_project=role_in_project or "BA"))
    db.flush()


def remove_member(db: Session, actor: User, project: Project, member_id: int) -> None:
    if not can_manage(actor):
        raise Forbidden("Only PMs and admins manage members.")
    member = db.get(ProjectMember, member_id)
    if member is None or member.project_id != project.id:
        raise NotFound("Member not found.")
    db.delete(member)
    db.flush()


def project_members(project: Project) -> list[User]:
    return sorted((m.user for m in project.members if m.user.is_active), key=lambda u: u.full_name)
