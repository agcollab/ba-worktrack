"""Generated reports (weekly PDF + Excel), kept so they can be downloaded again later."""
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, ForeignKey, LargeBinary, String, func
from sqlalchemy.orm import Mapped, deferred, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.user import User


class GeneratedReport(Base):
    __tablename__ = "generated_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(30), default="weekly")
    title: Mapped[str] = mapped_column(String(200))
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"))
    # File bytes are stored in the database so backups include them. deferred() = only
    # loaded when a download asks for them, not when the list page shows the rows.
    pdf_data: Mapped[bytes | None] = deferred(mapped_column(LargeBinary))
    xlsx_data: Mapped[bytes | None] = deferred(mapped_column(LargeBinary))
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)

    created_by: Mapped["User | None"] = relationship()
