"""Planned intents and validation goals."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from maestro_ai_agent.domain.enums import ActionType, ValidationSignalType
from maestro_ai_agent.domain.selector import SelectorCandidate


class ValidationGoal(BaseModel):
    """Expected post-condition signal after an action (coarse, device-agnostic)."""

    goal_id: str = Field(min_length=1, description="Stable id within the intent (e.g. vg-1).")
    signal: ValidationSignalType
    description: str = Field(min_length=1, description="What should be observed after the action.")
    target_hint: str | None = Field(
        default=None,
        description="Optional substring, id fragment, or label to match in hierarchy or logs.",
    )


class StepIntent(BaseModel):
    """Planner output: one actionable intent with validation goals and empty selector slots."""

    intent_id: UUID
    scenario_step_index: int = Field(ge=0, description="Index into ParsedScenario.steps.")
    primary_action: ActionType
    goal_summary: str = Field(
        min_length=1,
        description="Short English summary of what the orchestrator should achieve next.",
    )
    raw_step_text: str = Field(description="Original scenario step text for audit trails.")
    target_container_hint: str | None = Field(
        default=None,
        description="Optional normalized UI region hint from tap qualifiers (e.g. ``tab_bar``).",
    )
    target_qualifier_phrase_raw: str | None = Field(
        default=None,
        description="Optional raw qualifier phrase after on/in/from (audit / planner echo).",
    )
    validation_goals: list[ValidationGoal] = Field(
        default_factory=list,
        description="Goals to check after the action; may be empty when action is UNKNOWN.",
    )
    selector_candidates: list[SelectorCandidate] = Field(
        default_factory=list,
        description=(
            "Ranked hypotheses; typically filled via ``plan_selector_ranking`` "
            "or ``apply_ranking_to_intent``."
        ),
    )
