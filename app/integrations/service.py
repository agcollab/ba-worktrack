"""What the app does with a connector: test, import, push, two-way status sync.

Status sync keeps two markers on each linked task:
  external_status = the remote status at the last sync
  synced_status   = our status at the last sync
If only one side changed since then, the change is copied to the other side.
If both changed, that is a conflict, resolved by the integration's conflict_policy
("remote_wins" by default, "local_wins", or "manual" = leave both and log it).
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urlparse

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.config import settings
from app.integrations.base import BaseConnector, ConnectorError, RemoteItem
from app.integrations.registry import CONNECTORS, build_connector
from app.models import (
    Integration,
    IntegrationMapping,
    Requirement,
    SyncLog,
    Task,
    TaskPriority,
    TaskStatus,
    TaskStatusHistory,
    TaskType,
    User,
)
from app.security import encrypt_secret
from app.services import item_types as item_type_service
from app.services import tasks as task_service
from app.services.errors import NotFound, ServiceError
from app.services.requirements import format_criterion

logger = logging.getLogger("app.integrations")

CONFLICT_POLICIES = {"remote_wins": "Remote wins", "local_wins": "Local wins", "manual": "Log only (manual)"}
DEFAULT_TYPE_MAP = {
    "story": TaskType.REQUIREMENTS, "user story": TaskType.REQUIREMENTS, "requirement": TaskType.REQUIREMENTS,
    "epic": TaskType.ANALYSIS, "feature": TaskType.ANALYSIS, "spike": TaskType.ANALYSIS,
    "bug": TaskType.TESTING, "test": TaskType.TESTING, "test case": TaskType.TESTING, "issue": TaskType.OTHER,
}


@dataclass
class SyncResult:
    processed: int = 0
    created: int = 0
    updated: int = 0
    pushed: int = 0
    conflicts: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        if self.errors and not (self.created or self.updated or self.pushed):
            return "error"
        return "partial" if self.errors else "ok"

    def summary(self) -> str:
        text = (f"{self.processed} checked, {self.created} created, {self.updated} updated here, "
                f"{self.pushed} pushed, {len(self.conflicts)} conflicts")
        if self.errors:
            text += f", {len(self.errors)} errors"
        return text


# ---- admin CRUD ----------------------------------------------------------------

def list_integrations(db: Session) -> list[Integration]:
    return list(db.scalars(select(Integration).options(selectinload(Integration.local_project)).order_by(Integration.name)))


def get_integration(db: Session, integration_id: int) -> Integration:
    integration = db.scalar(
        select(Integration).options(selectinload(Integration.mappings)).where(Integration.id == integration_id)
    )
    if integration is None:
        raise NotFound("Integration not found.")
    return integration


def _check_url(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    parsed = urlparse(url)
    if parsed.scheme not in ("https", "http") or not parsed.netloc:
        raise ServiceError("Base URL must look like https://your-site.atlassian.net or https://dev.azure.com/your-org.")
    if parsed.scheme == "http" and settings.is_production:
        raise ServiceError("Use an https:// URL so tokens are never sent unencrypted.")
    return url


def save_integration(
    db: Session,
    name: str,
    kind: str,
    base_url: str,
    remote_project: str,
    username: str | None,
    token: str | None,
    local_project_id: int | None,
    config: dict,
    is_enabled: bool = True,
    auto_sync: bool = False,
    integration: Integration | None = None,
) -> Integration:
    if kind not in CONNECTORS:
        raise ServiceError("Choose JIRA or Azure DevOps.")
    if not name.strip():
        raise ServiceError("Name is required.")
    if not remote_project.strip():
        raise ServiceError("Remote project (JIRA key / ADO project name) is required.")
    if not local_project_id:
        raise ServiceError("Choose the local project that imported items go into.")
    other = db.scalar(select(Integration).where(Integration.name == name.strip()))
    if other and (integration is None or other.id != integration.id):
        raise ServiceError("Another integration already has that name.")
    if config.get("conflict_policy") not in CONFLICT_POLICIES:
        config["conflict_policy"] = "remote_wins"
    creating = integration is None
    if creating:
        if not token:
            raise ServiceError("API token / PAT is required.")
        integration = Integration(kind=kind)
        db.add(integration)
    integration.name = name.strip()
    integration.kind = kind
    integration.base_url = _check_url(base_url)
    integration.remote_project = remote_project.strip()
    integration.username = (username or "").strip() or None
    if token:  # blank on edit = keep the stored token
        integration.encrypted_token = encrypt_secret(token.strip())
    integration.local_project_id = local_project_id
    if not creating and "import_types" in integration.config:
        # Chosen on the integration page, not on this form: keep it
        config.setdefault("import_types", integration.config["import_types"])
    integration.config = config
    integration.is_enabled = is_enabled
    integration.auto_sync = auto_sync
    db.flush()
    if creating:
        reset_default_mappings(db, integration)
    return integration


def reset_default_mappings(db: Session, integration: Integration) -> None:
    for mapping in list(integration.mappings):
        if mapping.field == "status":
            integration.mappings.remove(mapping)
            db.delete(mapping)
    db.flush()
    for local, remote in CONNECTORS[integration.kind].default_status_map.items():
        integration.mappings.append(IntegrationMapping(field="status", local_value=local, remote_value=remote))
    db.flush()


def save_status_mappings(db: Session, integration: Integration, values: dict[str, str]) -> None:
    existing = {m.local_value: m for m in integration.mappings if m.field == "status"}
    for status in TaskStatus:
        remote = (values.get(status.value) or "").strip()
        mapping = existing.get(status.value)
        if remote and mapping:
            mapping.remote_value = remote
        elif remote:
            integration.mappings.append(IntegrationMapping(field="status", local_value=status.value, remote_value=remote))
        elif mapping:
            integration.mappings.remove(mapping)
            db.delete(mapping)
    db.flush()


def status_map(integration: Integration) -> dict[str, str]:
    """Our status -> remote status."""
    return {m.local_value: m.remote_value for m in integration.mappings if m.field == "status"}


def to_local_status(integration: Integration, item: RemoteItem) -> TaskStatus | None:
    reverse = {remote.lower(): local for local, remote in status_map(integration).items()}
    local = reverse.get(item.status.lower()) or item.status_hint or BaseConnector.guess_local_status(item.status)
    return TaskStatus(local) if local in TaskStatus._value2member_map_ else None


def _log(db: Session, integration: Integration, action: str, result: SyncResult, user: User | None) -> SyncLog:
    details = result.summary()
    if result.conflicts:
        details += "\nConflicts:\n" + "\n".join(f"- {c}" for c in result.conflicts[:100])
    if result.errors:
        details += "\nErrors:\n" + "\n".join(f"- {e}" for e in result.errors[:100])
    log = SyncLog(
        integration_id=integration.id, action=action, status=result.status, items_processed=result.processed,
        items_created=result.created, items_updated=result.updated + result.pushed,
        conflicts=len(result.conflicts), message=details, triggered_by_id=user.id if user else None,
    )
    db.add(log)
    integration.last_sync_at = datetime.now()
    integration.last_sync_status = result.status
    integration.last_sync_message = result.summary() if not result.errors else result.errors[0][:500]
    return log


# ---- test connection ----------------------------------------------------------------

def test_connection(db: Session, integration: Integration, user: User | None = None) -> tuple[bool, str]:
    try:
        with build_connector(integration) as connector:
            info = connector.test_connection()
        ok, message = info.ok, info.message
    except (ConnectorError, ValueError) as exc:
        ok, message = False, str(exc)
    result = SyncResult(errors=[] if ok else [message])
    log = _log(db, integration, "test", result, user)
    log.message = message
    integration.last_sync_message = message
    db.flush()
    return ok, message


# ---- import ---------------------------------------------------------------------------

def _apply_fields(db: Session, task: Task, item: RemoteItem, integration: Integration) -> bool:
    """Copy remote title / description / priority / dates onto the task. True if anything changed."""
    changed = False
    values = {
        "title": item.title[:200],
        "description": item.description,
        "due_date": item.due_date,
        "external_url": item.url,
    }
    if item.priority in TaskPriority._value2member_map_:
        values["priority"] = TaskPriority(item.priority)
    if item.estimate_hours is not None:
        values["estimate_hours"] = item.estimate_hours
    if item.item_type:
        # Keep the remote type exactly as named there; also file it under one of our categories for reports
        values["item_type_id"] = item_type_service.find_or_create(db, integration.kind, item.item_type)[0].id
        mapped = DEFAULT_TYPE_MAP.get(item.item_type.lower())
        if mapped:
            values["task_type"] = mapped
    if item.assignee_email:
        assignee = db.scalar(select(User).where(func.lower(User.email) == item.assignee_email.lower(),
                                                User.is_active.is_(True)))
        if assignee:
            values["assignee_id"] = assignee.id
    for name, value in values.items():
        if getattr(task, name) != value:
            setattr(task, name, value)
            changed = True
    return changed


def _reconcile_status(db: Session, connector: BaseConnector, integration: Integration, task: Task,
                      item: RemoteItem, result: SyncResult) -> None:
    remote_local = to_local_status(integration, item)
    mapping = status_map(integration)
    local_changed = task.synced_status is not None and task.status.value != task.synced_status
    remote_changed = task.external_status is not None and item.status != task.external_status
    first_sync = task.synced_status is None

    def pull() -> None:
        if remote_local is not None and remote_local != task.status:
            task_service.change_status(db, None, task, remote_local, force=True)
            result.updated += 1

    def push() -> None:
        target = mapping.get(task.status.value)
        if not target:
            result.errors.append(f"{task.key}: no remote status mapped for '{task.status}'.")
            return
        connector.update_status(item.external_id, target)
        item.status = target
        result.pushed += 1

    policy = integration.config.get("conflict_policy", "remote_wins")
    try:
        if first_sync:
            pull()
        elif local_changed and remote_changed:
            result.conflicts.append(
                f"{task.key}: here '{task.synced_status}' → '{task.status}', "
                f"remote '{task.external_status}' → '{item.status}' ({CONFLICT_POLICIES[policy]})")
            if policy == "remote_wins":
                pull()
            elif policy == "local_wins":
                push()
            else:
                return  # manual: keep the old markers so the conflict shows again next time
        elif remote_changed:
            pull()
        elif local_changed:
            push()
    except ConnectorError as exc:
        result.errors.append(f"{task.key}: {exc}")
        return
    task.external_status = item.status
    task.synced_status = task.status.value
    task.synced_at = datetime.now()


def _linked_tasks(db: Session, integration: Integration) -> dict[str, Task]:
    tasks = db.scalars(select(Task).where(Task.integration_id == integration.id))
    return {t.external_id: t for t in tasks if t.external_id}


def import_items(db: Session, integration: Integration, user: User | None = None, limit: int | None = None) -> SyncResult:
    """Create tasks for new remote items, update the linked ones, and sync their status."""
    result = SyncResult()
    if integration.local_project_id is None:
        raise ServiceError("Choose a local project for this integration first.")
    limit = limit or int(integration.config.get("max_items") or 200)
    try:
        with build_connector(integration) as connector:
            items = connector.fetch_items(limit=limit)
            linked = _linked_tasks(db, integration)
            for item in items:
                result.processed += 1
                task = linked.get(item.external_id)
                if task is None:
                    task = Task(project_id=integration.local_project_id, title=item.title[:200],
                                status=TaskStatus.TODO, external_source=integration.kind,
                                external_id=item.external_id, integration_id=integration.id,
                                created_by_id=user.id if user else None)
                    _apply_fields(db, task, item, integration)
                    initial = to_local_status(integration, item) or TaskStatus.TODO
                    task.status = initial
                    db.add(task)
                    db.flush()
                    db.add(TaskStatusHistory(task_id=task.id, from_status=None, to_status=initial,
                                             changed_by_id=user.id if user else None))
                    task.external_status = item.status
                    task.synced_status = initial.value
                    task.synced_at = datetime.now()
                    result.created += 1
                    continue
                if _apply_fields(db, task, item, integration):
                    task.updated_at = datetime.now()
                    result.updated += 1
                _reconcile_status(db, connector, integration, task, item, result)
    except ConnectorError as exc:
        result.errors.append(str(exc))
    _log(db, integration, "import", result, user)
    db.flush()
    return result


# ---- item types ------------------------------------------------------------------------

def fetch_item_types(db: Session, integration: Integration, user: User | None = None) -> SyncResult:
    """Read the project's item types from JIRA / ADO and add the ones we don't have yet (as editable)."""
    result = SyncResult()
    try:
        with build_connector(integration) as connector:
            for name, description in connector.fetch_item_types():
                result.processed += 1
                if item_type_service.find_or_create(db, integration.kind, name, description)[1]:
                    result.created += 1
    except ConnectorError as exc:
        result.errors.append(str(exc))
    _log(db, integration, "types", result, user)
    db.flush()
    return result


def save_item_type_settings(db: Session, integration: Integration, user: User, import_ids: set[int],
                            read_only_ids: set[int], request=None) -> None:
    """Which of this source's item types to import (none ticked = all), and which are read-only here."""
    types = [t for t, _ in item_type_service.list_item_types(db, integration.kind)]
    config = integration.config
    config["import_types"] = [t.name for t in types if t.id in import_ids]
    integration.config = config
    for item_type in types:
        item_type_service.set_read_only(db, user, item_type, item_type.id in read_only_ids, request=request)
    db.flush()


def sync_statuses(db: Session, integration: Integration, user: User | None = None) -> SyncResult:
    """Two-way status sync for every task already linked to this integration."""
    result = SyncResult()
    linked = _linked_tasks(db, integration)
    if linked:
        try:
            with build_connector(integration) as connector:
                for item in connector.get_items(list(linked)):
                    result.processed += 1
                    task = linked[item.external_id]
                    _reconcile_status(db, connector, integration, task, item, result)
        except ConnectorError as exc:
            result.errors.append(str(exc))
    _log(db, integration, "sync", result, user)
    db.flush()
    return result


# ---- push -----------------------------------------------------------------------------

def push_task(db: Session, integration: Integration, task: Task, user: User) -> RemoteItem:
    """Create a remote issue / work item from a local task and link them."""
    if task.external_id:
        raise ServiceError(f"This task is already linked to {task.external_source.upper()} {task.external_id}.")
    result = SyncResult(processed=1)
    try:
        with build_connector(integration) as connector:
            item = connector.create_item(task.title, task.description)
            target = status_map(integration).get(task.status.value)
            if target and task.status != TaskStatus.TODO and item.status.lower() != target.lower():
                try:
                    connector.update_status(item.external_id, target)
                    item.status = target
                except ConnectorError as exc:
                    result.errors.append(str(exc))
    except ConnectorError as exc:
        result.errors.append(str(exc))
        _log(db, integration, "push", result, user)
        db.flush()
        raise ServiceError(str(exc)) from exc
    task.external_source, task.external_id, task.external_url = integration.kind, item.external_id, item.url
    task.integration_id = integration.id
    if item.item_type:
        task.item_type_id = item_type_service.find_or_create(db, integration.kind, item.item_type)[0].id
    task.external_status, task.synced_status, task.synced_at = item.status, task.status.value, datetime.now()
    result.created = 1
    _log(db, integration, "push", result, user)
    db.flush()
    return item


def requirement_blocks(requirements: list[Requirement]) -> list[tuple[str, list[str]]]:
    blocks: list[tuple[str, list[str]]] = []
    for r in requirements:
        blocks.append((f"REQ-{r.id}: {r.title}", [r.description] if r.description else []))
        if r.criteria:
            blocks.append(("Acceptance criteria", [f"AC{c.position}: " + format_criterion(c).replace("\n", " ")
                                                   for c in r.criteria]))
        for tc in r.test_cases:
            steps = " | ".join(s.strip() for s in tc.steps.splitlines() if s.strip())
            lines = [f"Steps: {steps}", f"Expected: {tc.expected_result}"]
            if tc.preconditions:
                lines.insert(0, f"Preconditions: {tc.preconditions}")
            blocks.append((f"Test case: {tc.title} [{tc.priority}]", lines))
    return blocks


def push_requirements(db: Session, task: Task, user: User, requirement_ids: list[int] | None = None) -> int:
    """Post the task's requirements, UAC and test cases as a comment on the linked item."""
    if not task.integration_id or not task.external_id:
        raise ServiceError("Link this task to JIRA or Azure DevOps first (Push task).")
    integration = get_integration(db, task.integration_id)
    query = select(Requirement).options(selectinload(Requirement.criteria), selectinload(Requirement.test_cases)) \
        .where(Requirement.task_id == task.id)
    if requirement_ids:
        query = query.where(Requirement.id.in_(requirement_ids))
    requirements = list(db.scalars(query))
    if not requirements:
        raise ServiceError("This task has no requirements, UAC or test cases to push yet.")
    result = SyncResult(processed=len(requirements))
    try:
        with build_connector(integration) as connector:
            connector.add_comment(task.external_id, f"Requirements & acceptance criteria for {task.title}",
                                  requirement_blocks(requirements))
        result.pushed = len(requirements)
    except ConnectorError as exc:
        result.errors.append(str(exc))
        _log(db, integration, "push", result, user)
        db.flush()
        raise ServiceError(str(exc)) from exc
    _log(db, integration, "push", result, user)
    db.flush()
    return len(requirements)


def run_scheduled_sync(db: Session) -> list[tuple[str, str]]:
    """Called by the scheduler: status sync for every enabled integration with auto sync on."""
    out = []
    for integration in db.scalars(select(Integration).where(Integration.is_enabled.is_(True),
                                                            Integration.auto_sync.is_(True))):
        integration = get_integration(db, integration.id)
        try:
            result = sync_statuses(db, integration)
            db.commit()
            out.append((integration.name, result.summary()))
        except Exception as exc:  # keep going with the next integration
            db.rollback()
            logger.exception("Scheduled sync failed for %s", integration.name)
            out.append((integration.name, f"failed: {exc}"))
    return out


def config_from_form(kind: str, form: dict) -> dict:
    """Pick the settings that apply to this kind of integration out of a submitted form."""
    config = {"conflict_policy": form.get("conflict_policy") or "remote_wins"}
    try:
        config["max_items"] = max(1, min(2000, int(form.get("max_items") or 200)))
    except ValueError:
        config["max_items"] = 200
    if kind == "jira":
        config["deployment"] = "server" if form.get("deployment") == "server" else "cloud"
        for key in ("jql", "issue_type"):
            if form.get(key):
                config[key] = str(form[key]).strip()
    else:
        for key in ("wiql_filter", "work_item_type", "area_path"):
            if form.get(key):
                config[key] = str(form[key]).strip()
    return config

