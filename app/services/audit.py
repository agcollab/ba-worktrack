"""Write rows to the audit log for admin and other sensitive actions."""
import json
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.models import AuditLog, User


def client_ip(request: Request | None) -> str | None:
    if request is None:
        return None
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()[:45]
    return request.client.host if request.client else None


def record(
    db: Session,
    action: str,
    user: User | None = None,
    entity: Any = None,
    details: dict | None = None,
    request: Request | None = None,
) -> AuditLog:
    """Add an audit row to the session. The caller commits."""
    row = AuditLog(
        user_id=user.id if user else None,
        action=action,
        entity_type=type(entity).__name__ if entity is not None else None,
        entity_id=getattr(entity, "id", None),
        details=json.dumps(details, default=str) if details else None,
        ip_address=client_ip(request),
    )
    db.add(row)
    return row
