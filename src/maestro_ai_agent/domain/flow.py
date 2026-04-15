"""Committed successful flow steps (internal representation; not Maestro YAML)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, Field

from maestro_ai_agent.domain.enums import ActionType


class FlowStep(BaseModel):
    """
    One draft step (runtime-first).

    Successful runs set ``metadata`` keys such as ``lifecycle=validated`` (convention).
    Planning-only orchestration appends steps with ``lifecycle=planned``,
    ``executed=false``, ``validated=false`` until a real executor validates them.
    Conservative execution uses metadata such as ``executed_unvalidated`` (legacy),
    ``executed_validated``, ``executed_validation_failed``, ``executed_validation_inconclusive``,
    or ``executed_validation_skipped`` depending on the orchestrator validation outcome.
    """

    sequence: int = Field(ge=0, description="Monotonic order in the draft (0-based).")
    action: ActionType
    summary: str = Field(min_length=1, description="Human-readable description of the step.")
    target_selector_hint: str | None = Field(
        default=None,
        description="Resolved selector or target hint (Maestro syntax not required yet).",
    )
    input_value: str | None = Field(
        default=None,
        description="Text input when action is input_text.",
    )
    assertion_expectation: str | None = Field(
        default=None,
        description="Expected visible text or condition after asserts.",
    )
    intent_id: UUID | None = Field(default=None, description="Source StepIntent, if any.")
    metadata: dict[str, str] = Field(
        default_factory=dict,
        description="Small string metadata for tooling (e.g. scenario_step_index).",
    )


class FlowDraft(BaseModel):
    """Accumulated flow steps plus bookkeeping (serializable, no YAML emission)."""

    steps: list[FlowStep] = Field(default_factory=list)
    run_label: str | None = Field(default=None, description="Optional label for reports.")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
