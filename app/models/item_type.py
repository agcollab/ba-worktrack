"""Work item types as JIRA / Azure DevOps name them (Story, Bug, User Story, Feature...).

Imported tasks keep their remote type. An admin decides per type whether such tasks
may be changed here (editable) or only in JIRA / ADO (read-only).
"""
from sqlalchemy import Boolean, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.mixins import TimestampMixin

SOURCE_LABELS = {"jira": "JIRA", "ado": "Azure DevOps"}


class ItemType(TimestampMixin, Base):
    __tablename__ = "item_types"
    __table_args__ = (UniqueConstraint("source", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(20))  # "jira" or "ado"
    name: Mapped[str] = mapped_column(String(100))  # exactly as the remote system calls it
    description: Mapped[str | None] = mapped_column(String(500))
    is_read_only: Mapped[bool] = mapped_column(Boolean, default=False)

    @property
    def source_label(self) -> str:
        return SOURCE_LABELS.get(self.source, self.source)

    def __repr__(self) -> str:
        return f"<ItemType {self.source}:{self.name} {'read-only' if self.is_read_only else 'editable'}>"
