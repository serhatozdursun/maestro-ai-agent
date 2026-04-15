"""Runtime-oriented models for orchestrated scenario runs (planning-first)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator

from maestro_ai_agent.domain.enums import ActionType, Platform, SelectorType
from maestro_ai_agent.domain.flow import FlowDraft
from maestro_ai_agent.domain.hierarchy import HierarchySnapshot
from maestro_ai_agent.domain.intent import StepIntent
from maestro_ai_agent.domain.scenario import ParsedScenario, ScenarioInput
from maestro_ai_agent.domain.selectors.ranking_types import SelectorRankingResult
from maestro_ai_agent.domain.selectors.tap_resolution import TapResolutionSettings
from maestro_ai_agent.domain.selectors.target_hints import TargetHints
from maestro_ai_agent.orchestrator.enums import (
    DecisionExecutionFootprint,
    PlanningRunMode,
    PostActionValidationOutcome,
    RunStepPhase,
    StepValidationStatus,
)
from maestro_ai_agent.services.maestro.models import ActionResult, ScreenshotArtifact


class ScenarioRunRequest(BaseModel):
    """Input for a single orchestrated run (planning-only by default)."""

    scenario_input: ScenarioInput | None = None
    parsed_scenario: ParsedScenario | None = None
    device_id: str | None = Field(
        default=None,
        description="Optional device identifier passed to the observation service.",
    )
    include_screenshot: bool = Field(
        default=False,
        description="Forwarded to the observation service when supported.",
    )
    enable_visual_advisory_fallback: bool = Field(
        default=False,
        description=(
            "When true and a :class:`VisualTargetSuggester` is configured on the orchestrator, "
            "re-rank once after a failed first pass if a screenshot exists (see docs)."
        ),
    )
    use_canonical_scenario_normalization: bool = Field(
        default=False,
        description=(
            "When true with ``scenario_input`` set, run ``normalize_scenario_text`` "
            "(deterministic only; no AI) and ``build_parsed_scenario_from_canonical`` before "
            "``plan_intents``. Default false keeps the legacy ``parse_scenario_input`` path."
        ),
    )
    run_label: str | None = Field(default=None, description="Label for FlowDraftBuilder.")
    planning_mode: PlanningRunMode = Field(
        default=PlanningRunMode.PLANNING_ONLY,
        description=(
            "``PLANNING_ONLY``: observe → rank → plan. "
            "``OBSERVE_PLAN_EXECUTE``: observe → rank → plan → ``tap_on``/``input_text`` "
            "when mapped, then a second hierarchy observation and deterministic validation."
        ),
    )
    stop_after_first_planned: bool = Field(
        default=False,
        description="If true, stop the loop after the first step that yields a planned attempt.",
    )
    max_steps: int | None = Field(
        default=None,
        ge=1,
        description="Optional cap on how many scenario steps to process.",
    )
    stop_on_first_hard_failure: bool = Field(
        default=False,
        description=(
            "When true, stop the intent loop after the first step in a hard-failure phase "
            "(execution failed, missing input, unsupported, or validation failed)."
        ),
    )
    tap_resolution: TapResolutionSettings = Field(
        default_factory=TapResolutionSettings,
        description="Tap ambiguity policy, suggestion limits, and structural preference overrides.",
    )

    @model_validator(mode="after")
    def _one_scenario_source(self) -> ScenarioRunRequest:
        has_input = self.scenario_input is not None
        has_parsed = self.parsed_scenario is not None
        if has_input == has_parsed:
            msg = "Provide exactly one of scenario_input or parsed_scenario."
            raise ValueError(msg)
        if self.use_canonical_scenario_normalization and not has_input:
            msg = "use_canonical_scenario_normalization requires scenario_input."
            raise ValueError(msg)
        return self


class ScenarioRunContext(BaseModel):
    """Immutable-ish metadata for a run."""

    run_id: UUID = Field(default_factory=uuid4)
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    device_id: str | None = None
    planning_mode: PlanningRunMode = PlanningRunMode.PLANNING_ONLY


class RankedCandidateSummary(BaseModel):
    """Compact view of a ranked selector for logs and reports."""

    candidate_id: str
    selector_type: SelectorType
    score: float
    expression: str | None = None
    region_hint: str | None = None
    structural_kind: str | None = None


class PlannedActionAttempt(BaseModel):
    """A single planned device action derived from selector ranking."""

    intent_id: UUID
    scenario_step_index: int
    action: ActionType
    chosen_candidate_id: str
    expression: str | None
    selector_type: SelectorType
    score: float
    rank_position: int = Field(default=0, description="0 = primary (best) candidate.")
    explanation_summary: str
    lifecycle: str = Field(
        default="planned",
        description="Selector-ranking artifact; execution status lives on ``StepRunState``.",
    )


class ProviderExecutionOutcome(BaseModel):
    """Record of a single provider invocation (or an explicit skip before invoke)."""

    execution_attempted: bool = Field(
        default=False,
        description="True once a tap/input_text call was dispatched to the provider.",
    )
    provider_action: str | None = Field(
        default=None,
        description="Logical provider method, e.g. tap_on or input_text.",
    )
    selector_used: str | None = None
    text_input_used: str | None = None
    action_result: ActionResult | None = None
    attempted_at: datetime | None = None
    unsupported_reason: str | None = Field(
        default=None,
        description="Populated when execution was skipped (unsupported or missing input).",
    )


class ObservationCycleResult(BaseModel):
    """Outcome of one observe step (hierarchy + warnings + optional screenshot)."""

    hierarchy: HierarchySnapshot
    parse_warnings: list[str] = Field(default_factory=list)
    retrieved_at: datetime
    app_id: str
    platform: Platform
    device_id: str | None = None
    screenshot: ScreenshotArtifact | None = Field(
        default=None,
        description="Present when ``include_screenshot`` was true and the provider returned data.",
    )


class BeforeAfterObservationSummary(BaseModel):
    """Compact before/after hierarchy stats for audit (not a full diff)."""

    before_node_count: int = 0
    after_node_count: int = 0
    before_parse_warnings: list[str] = Field(default_factory=list)
    after_parse_warnings: list[str] = Field(default_factory=list)


class ValidationEvidenceItem(BaseModel):
    """One line of deterministic validation reasoning."""

    code: str
    detail: str
    contributes: str | None = Field(
        default=None,
        description="Optional coarse verdict from this line (pass/fail/inconclusive).",
    )


class PostActionValidationRecord(BaseModel):
    """Outcome of post-execution hierarchy validation."""

    outcome: PostActionValidationOutcome
    before_after_summary: BeforeAfterObservationSummary
    evidence: list[ValidationEvidenceItem] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class StepRunState(BaseModel):
    """Mutable-ish per-step bookkeeping for the orchestrator loop."""

    scenario_step_index: int
    raw_step_text: str
    intent: StepIntent
    phase: RunStepPhase = RunStepPhase.PENDING
    observation: ObservationCycleResult | None = None
    ranking: SelectorRankingResult | None = None
    target_hints: TargetHints | None = None
    planned_attempt: PlannedActionAttempt | None = None
    validation_status: StepValidationStatus = StepValidationStatus.NOT_APPLICABLE
    execution_outcome: ProviderExecutionOutcome | None = None
    post_action_observation: ObservationCycleResult | None = None
    post_action_validation: PostActionValidationRecord | None = None
    warnings: list[str] = Field(default_factory=list)
    blocker_episode: dict[str, Any] | None = Field(
        default=None,
        description="Runtime blocker engine episode when ``DISMISS_BLOCKER`` ran.",
    )


class ScenarioRunState(BaseModel):
    """Aggregated runtime state after (or during) a run."""

    context: ScenarioRunContext
    request: ScenarioRunRequest
    step_states: list[StepRunState] = Field(default_factory=list)
    flow_draft: FlowDraft


class RunDecisionLogEntry(BaseModel):
    """One row in the human/QA-oriented decision log."""

    scenario_step_index: int
    raw_step_text: str
    intent_goal_summary: str | None
    intent_primary_action: ActionType
    target_hints: TargetHints | None = None
    top_candidates: list[RankedCandidateSummary] = Field(default_factory=list)
    selector_resolution_status: str | None = None
    ambiguity_reason: str | None = None
    chosen_candidate_id: str | None = None
    chosen_score: float | None = None
    explanation_summary: str = ""
    execution_footprint: DecisionExecutionFootprint = DecisionExecutionFootprint.PLANNING_ONLY
    step_phase: RunStepPhase = RunStepPhase.PENDING
    step_validation_status: StepValidationStatus = StepValidationStatus.NOT_APPLICABLE
    provider_action: str | None = None
    provider_ok: bool | None = None
    provider_message: str | None = None
    post_action_validation_outcome: PostActionValidationOutcome | None = None
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class RunReport(BaseModel):
    """High-level narrative for debugging and future QA review."""

    run_id: UUID
    planning_mode: PlanningRunMode
    summary: str
    limitations: list[str] = Field(default_factory=list)
    decision_log: list[RunDecisionLogEntry] = Field(default_factory=list)
    total_intents: int = 0
    steps_observed: int = 0
    steps_planned: int = 0
    steps_without_viable_selector: int = 0
    steps_provider_success_validation_deferred: int = 0
    steps_provider_failed: int = 0
    steps_execution_unsupported: int = 0
    steps_missing_input_text: int = 0
    steps_validation_passed: int = 0
    steps_validation_failed: int = 0
    steps_validation_inconclusive: int = 0
    steps_validation_skipped: int = 0


class PlanningOrchestrationResult(BaseModel):
    """Bundle returned by the planning orchestrator."""

    state: ScenarioRunState
    report: RunReport
