"""Tasks: search with filters, create, edit, the status workflow, comments, attachments."""
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import Select, case, func, or_, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.config import settings
from app.models import (
    Attachment,
    Project,
    Task,
    TaskComment,
    TaskPriority,
    TaskStatus,
    TaskStatusHistory,
    TaskType,
    TimeEntry,
    User,
)
from app.services.errors import Forbidden, NotFound, ServiceError
from app.services.projects import get_project, visible_project_ids

# Where a task may go next. Integrations may override this when the remote system moved it.
WORKFLOW: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.TODO: {TaskStatus.IN_PROGRESS},
    TaskStatus.IN_PROGRESS: {TaskStatus.TODO, TaskStatus.IN_REVIEW},
    TaskStatus.IN_REVIEW: {TaskStatus.IN_PROGRESS, TaskStatus.DONE},
    TaskStatus.DONE: {TaskStatus.IN_PROGRESS},
}

ALLOWED_UPLOAD_EXTENSIONS = {
    ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".txt", ".csv", ".md",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".vsdx", ".json", ".xml", ".zip",
}


@dataclass
class TaskFilters:
    q: str | None = None
    project_id: int | None = None
    status: list[str] = field(default_factory=list)
    assignee_id: int | None = None  # -1 = unassigned
    task_type: str | None = None
    priority: str | None = None
    overdue: bool = False
    due_before: date | None = None
    source: str | None = None  # local / jira / ado
    sort: str = "updated"

    def as_query(self) -> dict:
        """The filters as query-string pairs, so export links keep the same filters."""
        out: dict = {}
        for key in ("q", "project_id", "assignee_id", "task_type", "priority", "source", "sort"):
            value = getattr(self, key)
            if value not in (None, "", "updated"):
                out[key] = value
        if self.status:
            out["status"] = self.status
        if self.overdue:
            out["overdue"] = "1"
        return out


PRIORITY_RANK = case(
    (Task.priority == TaskPriority.CRITICAL, 4),
    (Task.priority == TaskPriority.HIGH, 3),
    (Task.priority == TaskPriority.MEDIUM, 2),
    else_=1,
)

SORTS = {
    "updated": Task.updated_at.desc(),
    "due": Task.due_date.asc().nulls_last(),
    "priority": PRIORITY_RANK.desc(),
    "created": Task.created_at.desc(),
    "title": Task.title.asc(),
}


def task_query(db: Session, user: User, filters: TaskFilters) -> Select:
    query = select(Task).options(
        joinedload(Task.project), joinedload(Task.assignee), selectinload(Task.time_entries)
    )
    ids = visible_project_ids(db, user)
    if ids is not None:
        query = query.where(Task.project_id.in_(ids))
    if filters.q:
        like = f"%{filters.q.strip()}%"
        conditions = [Task.title.ilike(like), Task.description.ilike(like), Task.external_id.ilike(like)]
        if filters.q.strip().isdigit():
            conditions.append(Task.id == int(filters.q.strip()))
        query = query.where(or_(*conditions))
    if filters.project_id:
        query = query.where(Task.project_id == filters.project_id)
    if filters.status:
        query = query.where(Task.status.in_([TaskStatus(s) for s in filters.status if s in TaskStatus._value2member_map_]))
    if filters.assignee_id == -1:
        query = query.where(Task.assignee_id.is_(None))
    elif filters.assignee_id:
        query = query.where(Task.assignee_id == filters.assignee_id)
    if filters.task_type and filters.task_type in TaskType._value2member_map_:
        query = query.where(Task.task_type == TaskType(filters.task_type))
    if filters.priority and filters.priority in TaskPriority._value2member_map_:
        query = query.where(Task.priority == TaskPriority(filters.priority))
    if filters.overdue:
        query = query.where(Task.due_date < date.today(), Task.status != TaskStatus.DONE)
    if filters.due_before:
        query = query.where(Task.due_date <= filters.due_before)
    if filters.source == "local":
        query = query.where(Task.external_source.is_(None))
    elif filters.source in ("jira", "ado"):
        query = query.where(Task.external_source == filters.source)
    return query.order_by(SORTS.get(filters.sort, SORTS["updated"]), Task.id.desc())


def search_tasks(db: Session, user: User, filters: TaskFilters, limit: int | None = None,
                 offset: int = 0) -> list[Task]:
    query = task_query(db, user, filters)
    if limit:
        query = query.limit(limit).offset(offset)
    return list(db.scalars(query).unique())


def count_tasks(db: Session, user: User, filters: TaskFilters) -> int:
    sub = task_query(db, user, filters).with_only_columns(Task.id).order_by(None).subquery()
    return db.scalar(select(func.count()).select_from(sub)) or 0


def get_task(db: Session, user: User, task_id: int) -> Task:
    task = db.scalar(
        select(Task)
        .options(
            joinedload(Task.project),
            joinedload(Task.assignee),
            selectinload(Task.comments).joinedload(TaskComment.author),
            selectinload(Task.attachments),
            selectinload(Task.status_history).joinedload(TaskStatusHistory.changed_by),
            selectinload(Task.time_entries).joinedload(TimeEntry.user),
        )
        .where(Task.id == task_id)
        .execution_options(populate_existing=True)  # fresh collections after a change in this request
    )
    if task is None:
        raise NotFound("Task not found.")
    get_project(db, user, task.project_id)  # raises Forbidden if not visible
    return task


def can_edit(user: User, task: Task) -> bool:
    """Anyone who can see the task (a project member, PM or admin) can edit it, unless its type is read-only."""
    if task.is_read_only:
        return False
    return user.is_manager or any(m.user_id == user.id for m in task.project.members)


def ensure_editable(task: Task) -> None:
    """Refuse changes to tasks whose JIRA / ADO item type an admin made read-only."""
    if task.is_read_only:
        source = "JIRA" if task.external_source == "jira" else "Azure DevOps"
        raise Forbidden(f"{task.key} is a {task.item_type.name}, which is read-only here. Change it in {source}.")


def _validate(title: str, estimate_hours: float | None, project: Project | None) -> None:
    if not title or not title.strip():
        raise ServiceError("Title is required.")
    if len(title) > 200:
        raise ServiceError("Title must be 200 characters or fewer.")
    if estimate_hours is not None and not 0 <= estimate_hours <= 1000:
        raise ServiceError("Estimate must be between 0 and 1000 hours.")
    if project is not None and not project.is_active:
        raise ServiceError("That project is archived.")


def _check_assignee(db: Session, project: Project, assignee_id: int | None) -> None:
    if not assignee_id:
        return
    assignee = db.get(User, assignee_id)
    if assignee is None or not assignee.is_active:
        raise ServiceError("Assignee not found.")
    if not assignee.is_manager and not any(m.user_id == assignee_id for m in project.members):
        raise ServiceError(f"{assignee.full_name} is not a member of {project.name}.")


def create_task(
    db: Session,
    user: User,
    project_id: int,
    title: str,
    description: str | None = None,
    priority: TaskPriority = TaskPriority.MEDIUM,
    task_type: TaskType = TaskType.OTHER,
    assignee_id: int | None = None,
    estimate_hours: float | None = None,
    due_date: date | None = None,
    status: TaskStatus = TaskStatus.TODO,
) -> Task:
    project = get_project(db, user, project_id)
    _validate(title, estimate_hours, project)
    _check_assignee(db, project, assignee_id)
    task = Task(
        project_id=project.id,
        title=title.strip(),
        description=(description or "").strip() or None,
        priority=priority,
        task_type=task_type,
        assignee_id=assignee_id or None,
        estimate_hours=estimate_hours,
        due_date=due_date,
        status=status,
        created_by_id=user.id,
    )
    db.add(task)
    db.flush()
    db.add(TaskStatusHistory(task_id=task.id, from_status=None, to_status=status, changed_by_id=user.id))
    db.flush()
    return task


def update_task(
    db: Session,
    user: User,
    task: Task,
    title: str,
    description: str | None,
    priority: TaskPriority,
    task_type: TaskType,
    assignee_id: int | None,
    estimate_hours: float | None,
    due_date: date | None,
    project_id: int | None = None,
) -> Task:
    ensure_editable(task)
    if not can_edit(user, task):
        raise Forbidden("You cannot edit this task.")
    project = task.project
    if project_id and project_id != task.project_id:
        project = get_project(db, user, project_id)
        task.project_id = project.id
        task.project = project
    _validate(title, estimate_hours, project)
    _check_assignee(db, project, assignee_id)
    task.title = title.strip()
    task.description = (description or "").strip() or None
    task.priority, task.task_type = priority, task_type
    task.assignee_id = assignee_id or None
    task.estimate_hours, task.due_date = estimate_hours, due_date
    task.updated_at = datetime.now()
    db.flush()
    return task


def allowed_next(task: Task) -> list[TaskStatus]:
    if task.is_read_only:
        return []
    return [s for s in TaskStatus if s in WORKFLOW[task.status]]


def change_status(db: Session, user: User | None, task: Task, new_status: TaskStatus, force: bool = False) -> bool:
    """Move a task along the workflow. Returns False when it was already there.

    force=True skips the workflow and the read-only check (used when JIRA / ADO moved the item).
    """
    if new_status == task.status:
        return False
    if not force:
        ensure_editable(task)
    if not force and new_status not in WORKFLOW[task.status]:
        raise ServiceError(f"A task can't move from {task.status} to {new_status}. "
                           f"Next steps: {', '.join(allowed_next(task)) or 'none'}.")
    db.add(TaskStatusHistory(task_id=task.id, from_status=task.status, to_status=new_status,
                             changed_by_id=user.id if user else None))
    task.status = new_status
    task.updated_at = datetime.now()
    db.flush()
    return True


def delete_task(db: Session, user: User, task: Task) -> None:
    ensure_editable(task)
    if not user.is_manager and task.created_by_id != user.id:
        raise Forbidden("Only the creator, a PM or an admin can delete a task.")
    for attachment in task.attachments:
        Path(attachment.stored_path).unlink(missing_ok=True)
    db.delete(task)
    db.flush()


def add_comment(db: Session, user: User, task: Task, body: str) -> TaskComment:
    body = (body or "").strip()
    if not body:
        raise ServiceError("Comment cannot be empty.")
    if len(body) > 10_000:
        raise ServiceError("Comment is too long (10,000 characters max).")
    comment = TaskComment(task_id=task.id, author_id=user.id, body=body)
    db.add(comment)
    db.flush()
    return comment


def delete_comment(db: Session, user: User, comment: TaskComment) -> None:
    if comment.author_id != user.id and not user.is_admin:
        raise Forbidden("You can delete only your own comments.")
    db.delete(comment)
    db.flush()


def save_attachment(db: Session, user: User, task: Task, filename: str, content: bytes,
                    content_type: str | None) -> Attachment:
    safe_name = Path(filename or "file").name[:200] or "file"
    extension = Path(safe_name).suffix.lower()
    if extension not in ALLOWED_UPLOAD_EXTENSIONS:
        raise ServiceError(f"Files of type {extension or '(none)'} are not allowed.")
    if len(content) > settings.MAX_UPLOAD_MB * 1024 * 1024:
        raise ServiceError(f"File is larger than {settings.MAX_UPLOAD_MB} MB.")
    if not content:
        raise ServiceError("File is empty.")
    folder = Path(settings.UPLOAD_DIR) / str(task.id)
    folder.mkdir(parents=True, exist_ok=True)
    stored = folder / f"{uuid.uuid4().hex}{extension}"  # never trust the user's file name on disk
    stored.write_bytes(content)
    attachment = Attachment(
        task_id=task.id,
        uploaded_by_id=user.id,
        filename=safe_name,
        stored_path=str(stored),
        content_type=(content_type or "application/octet-stream")[:100],
        size_bytes=len(content),
    )
    db.add(attachment)
    db.flush()
    return attachment


def delete_attachment(db: Session, user: User, attachment: Attachment) -> None:
    if attachment.uploaded_by_id != user.id and not user.is_manager:
        raise Forbidden("You can delete only files you uploaded.")
    Path(attachment.stored_path).unlink(missing_ok=True)
    db.delete(attachment)
    db.flush()
