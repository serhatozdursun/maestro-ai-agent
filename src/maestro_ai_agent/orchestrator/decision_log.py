"""Construct structured decision log rows from step outcomes."""

from __future__ import annotations

from maestro_ai_agent.domain.selectors.tap_resolution import TapResolutionSettings
from maestro_ai_agent.orchestrator.enums import (
    DecisionExecutionFootprint,
    PlanningRunMode,
    PostActionValidationOutcome,
    RunStepPhase,
)
from maestro_ai_agent.orchestrator.models import (
    RankedCandidateSummary,
    RunDecisionLogEntry,
    StepRunState,
)


def _top_k_candidates(
    step: StepRunState,
    *,
    limit: int = 5,
    tap_resolution: TapResolutionSettings | None = None,
) -> list[RankedCandidateSummary]:
    if step.ranking is None:
        return []
    lim = tap_resolution.max_target_suggestions if tap_resolution is not None else limit
    show_regions = True if tap_resolution is None else tap_resolution.show_target_regions
    out: list[RankedCandidateSummary] = []
    for entry in step.ranking.ordered[:lim]:
        out.append(
            RankedCandidateSummary(
                candidate_id=entry.candidate.candidate_id,
                selector_type=entry.candidate.selector_type,
                score=entry.score,
                expression=entry.candidate.expression,
                region_hint=entry.region_hint if show_regions else None,
                structural_kind=entry.structural_kind,
            ),
        )
    return out


def _footprint_for_step(step: StepRunState, *, planning_only: bool) -> DecisionExecutionFootprint:
    if planning_only:
        return DecisionExecutionFootprint.PLANNING_ONLY
    if step.phase is RunStepPhase.SKIPPED_NO_SELECTOR:
        return DecisionExecutionFootprint.PLANNING_ONLY
    if step.phase is RunStepPhase.UNSUPPORTED:
        return DecisionExecutionFootprint.EXECUTION_UNSUPPORTED
    if step.phase is RunStepPhase.MISSING_INPUT_VALUE:
        return DecisionExecutionFootprint.MISSING_INPUT_TEXT
    if step.phase is RunStepPhase.EXECUTION_FAILED:
        return DecisionExecutionFootprint.PROVIDER_INVOKED_FAILED
    if step.phase is RunStepPhase.VALIDATED:
        return DecisionExecutionFootprint.PROVIDER_SUCCESS_VALIDATION_PASSED
    if step.phase is RunStepPhase.VALIDATION_FAILED:
        return DecisionExecutionFootprint.PROVIDER_SUCCESS_VALIDATION_FAILED
    if step.phase is RunStepPhase.VALIDATION_INCONCLUSIVE:
        return DecisionExecutionFootprint.PROVIDER_SUCCESS_VALIDATION_INCONCLUSIVE
    if step.phase is RunStepPhase.VALIDATION_SKIPPED:
        return DecisionExecutionFootprint.PROVIDER_SUCCESS_VALIDATION_SKIPPED
    if step.phase is RunStepPhase.EXECUTED:
        return DecisionExecutionFootprint.EXECUTED
    if step.phase is RunStepPhase.VALIDATION_DEFERRED:
        return DecisionExecutionFootprint.PROVIDER_SUCCESS_VALIDATION_DEFERRED
    return DecisionExecutionFootprint.PLANNING_ONLY


def _provider_fields(step: StepRunState) -> tuple[str | None, bool | None, str | None]:
    ex = step.execution_outcome
    if ex is None or ex.action_result is None:
        return None, None, None
    r = ex.action_result
    return ex.provider_action, r.ok, r.message


def _validation_outcome_field(step: StepRunState) -> PostActionValidationOutcome | None:
    if step.post_action_validation is None:
        return None
    return step.post_action_validation.outcome


def build_decision_log_entry(
    step: StepRunState,
    *,
    planning_only: bool = True,
    planning_mode: PlanningRunMode = PlanningRunMode.PLANNING_ONLY,
    extra_limitations: list[str] | None = None,
    tap_resolution: TapResolutionSettings | None = None,
) -> RunDecisionLogEntry:
    """Map a terminal ``StepRunState`` into an audit log row."""
    chosen_id = step.planned_attempt.chosen_candidate_id if step.planned_attempt else None
    chosen_score = step.planned_attempt.score if step.planned_attempt else None
    explanation = step.planned_attempt.explanation_summary if step.planned_attempt else ""

    limitations = [
        *(extra_limitations or []),
    ]
    if planning_only:
        limitations.append(
            "Planning-only run: no Maestro tap/input/assert was executed; "
            "step outcome is not SUCCEEDED.",
        )
    elif planning_mode is PlanningRunMode.OBSERVE_PLAN_EXECUTE:
        limitations.append(
            "Observe-plan-execute: lightweight hierarchy validation is deterministic and "
            "may return inconclusive when evidence is weak.",
        )
        limitations.append(
            "Provider ``ActionResult.ok`` means the tool call completed, not that goals are met.",
        )
        if step.phase is RunStepPhase.VALIDATION_INCONCLUSIVE:
            limitations.append(
                "validation_inconclusive: no failing signal, "
                "but evidence was insufficient to pass.",
            )
        if step.phase is RunStepPhase.VALIDATION_SKIPPED:
            limitations.append(
                "validation_skipped: post-action hierarchy could not be checked safely.",
            )
    if step.phase == RunStepPhase.SKIPPED_NO_SELECTOR:
        limitations.append(
            "No viable primary selector; executor would need hints, exploration, or human input.",
        )

    footprint = _footprint_for_step(step, planning_only=planning_only)
    prov_action, prov_ok, prov_msg = _provider_fields(step)

    res_status = step.ranking.resolution_status if step.ranking else None
    amb_reason = step.ranking.ambiguity_reason if step.ranking else None

    return RunDecisionLogEntry(
        scenario_step_index=step.scenario_step_index,
        raw_step_text=step.raw_step_text,
        intent_goal_summary=step.intent.goal_summary,
        intent_primary_action=step.intent.primary_action,
        target_hints=step.target_hints,
        top_candidates=_top_k_candidates(step, tap_resolution=tap_resolution),
        selector_resolution_status=res_status,
        ambiguity_reason=amb_reason,
        chosen_candidate_id=chosen_id,
        chosen_score=chosen_score,
        explanation_summary=explanation,
        execution_footprint=footprint,
        step_phase=step.phase,
        step_validation_status=step.validation_status,
        provider_action=prov_action,
        provider_ok=prov_ok,
        provider_message=prov_msg,
        post_action_validation_outcome=_validation_outcome_field(step),
        warnings=list(step.warnings),
        limitations=limitations,
    )
