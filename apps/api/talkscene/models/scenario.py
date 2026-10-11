from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, Json, TimestampMixin


class Scenario(Base, TimestampMixin):
    """A scenario pack row.

    `yaml` holds the whole validated document so the conversation engine reads
    one object and the catalog can be re-seeded from `packages/scenarios`
    without a migration.  The scalar columns exist only to make filtering cheap.
    """

    __tablename__ = "scenarios"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    language: Mapped[str] = mapped_column(String(8), index=True, nullable=False)
    level: Mapped[str] = mapped_column(String(4), index=True, nullable=False)
    category: Mapped[str] = mapped_column(String(24), index=True, nullable=False)
    title_en: Mapped[str] = mapped_column(String(120), nullable=False)
    summary: Mapped[str] = mapped_column(String(400), nullable=False)
    yaml: Mapped[dict] = mapped_column(Json, nullable=False)
    is_published: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    author_id: Mapped[str | None] = mapped_column(String(40), ForeignKey("users.id"))

    tags: Mapped[list[ScenarioTag]] = relationship(
        back_populates="scenario", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (Index("ix_scenarios_lang_level", "language", "level"),)


class ScenarioTag(Base):
    __tablename__ = "scenario_tags"

    scenario_id: Mapped[str] = mapped_column(
        String(80), ForeignKey("scenarios.id", ondelete="CASCADE"), primary_key=True
    )
    tag: Mapped[str] = mapped_column(String(40), primary_key=True)

    scenario: Mapped[Scenario] = relationship(back_populates="tags")
