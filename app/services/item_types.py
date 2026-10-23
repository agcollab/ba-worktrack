"""JIRA / Azure DevOps item types: find or create them, and the admin's read-only switch."""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ItemType, Task, User
from app.services import audit
from app.services.errors import NotFound


def list_item_types(db: Session, source: str | None = None) -> list[tuple[ItemType, int]]:
    """Every item type with the number of tasks using it, grouped by source then name."""
    counts = (
        select(Task.item_type_id, func.count(Task.id).label("n"))
        .where(Task.item_type_id.is_not(None))
        .group_by(Task.item_type_id)
        .subquery()
    )
    query = (
        select(ItemType, func.coalesce(counts.c.n, 0))
        .outerjoin(counts, counts.c.item_type_id == ItemType.id)
        .order_by(ItemType.source, func.lower(ItemType.name))
    )
    if source:
        query = query.where(ItemType.source == source)
    return [(item_type, count) for item_type, count in db.execute(query)]


def get_item_type(db: Session, item_type_id: int) -> ItemType:
    item_type = db.get(ItemType, item_type_id)
    if item_type is None:
        raise NotFound("Item type not found.")
    return item_type


def find_or_create(db: Session, source: str, name: str, description: str | None = None) -> tuple[ItemType, bool]:
    """The type with this exact name for this source, created (editable) on first sight. (type, created)."""
    name = name.strip()[:100]
    item_type = db.scalar(select(ItemType).where(ItemType.source == source, ItemType.name == name))
    if item_type is not None:
        if description and not item_type.description:
            item_type.description = description[:500]
        return item_type, False
    item_type = ItemType(source=source, name=name, description=(description or "")[:500] or None, is_read_only=False)
    db.add(item_type)
    db.flush()
    return item_type, True


def set_read_only(db: Session, user: User, item_type: ItemType, read_only: bool, request=None) -> bool:
    """Admin switch. Returns False when nothing changed."""
    if item_type.is_read_only == read_only:
        return False
    item_type.is_read_only = read_only
    audit.record(db, "item_type.read_only" if read_only else "item_type.editable", user=user, entity=item_type,
                 details={"source": item_type.source, "name": item_type.name}, request=request)
    db.flush()
    return True
