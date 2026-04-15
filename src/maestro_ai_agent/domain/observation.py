"""Screen observations and execution attempts (pre- or post-action)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, Field

from maestro_ai_agent.domain.confidence import ConfidenceScore
from maestro_ai_agent.domain.enums import ActionType, Platform, StepStatus
from maestro_ai_agent.domain.selector import SelectorCandidate


class ScreenObservation(BaseModel):
    """Snapshot descriptor for a single point in time (no raw binary in domain)."""

    observation_id: UUID
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    platform: Platform
    hierarchy_summary: str | None = Field(
        default=None,
        description="Optional short summary or digest of hierarchy (full tree stays in services).",
    )
    screen_label: str | None = Field(
        default=None,
        description="Optional human label for the screen.",
    )


class ExecutionAttempt(BaseModel):
    """Single try of an intent against the device (status + selectors + observations)."""

    attempt_id: UUID
    intent_id: UUID
    scenario_step_index: int = Field(ge=0)
    action: ActionType
    status: StepStatus
    selector_candidates: list[SelectorCandidate] = Field(default_factory=list)
    committed_selector: SelectorCandidate | None = None
    screen_before: ScreenObservation | None = None
    screen_after: ScreenObservation | None = None
    error_message: str | None = None
    overall_confidence: ConfidenceScore | None = Field(
        default=None,
        description="Optional aggregate confidence for the attempt after ranking/execution.",
    )
