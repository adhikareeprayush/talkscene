"""SQLAlchemy models (plan §9).

Imported for their side effect of registering on `Base.metadata`, which Alembic
autogenerate and `create_all` both rely on.
"""

from .base import Base
from .drill import Drill, DrillAttempt
from .report import Report
from .scenario import Scenario, ScenarioTag
from .session import PracticeSession, Turn
from .usage import TtsCache, UsageLedger
from .user import User, UserPref
from .vocab import SrsCard, VocabItem

__all__ = [
    "Base",
    "Drill",
    "DrillAttempt",
    "PracticeSession",
    "Report",
    "Scenario",
    "ScenarioTag",
    "SrsCard",
    "TtsCache",
    "Turn",
    "UsageLedger",
    "User",
    "UserPref",
    "VocabItem",
]
