from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..core.ids import report_id
from .base import Base, Json, TimestampMixin


class Report(Base, TimestampMixin):
    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=report_id)
    session_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("sessions.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    overall: Mapped[int] = mapped_column(Integer, nullable=False)
    estimated_cefr: Mapped[str] = mapped_column(String(8), nullable=False)
    json: Mapped[dict] = mapped_column(Json, nullable=False)
