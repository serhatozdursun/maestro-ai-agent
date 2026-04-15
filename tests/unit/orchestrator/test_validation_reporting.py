"""Decision log + run report fields for post-execution validation outcomes."""

from __future__ import annotations

from uuid import uuid4

from maestro_ai_agent.domain.enums import ActionType
from maestro_ai_agent.domain.intent import StepIntent
from maestro_ai_agent.orchestrator.decision_log import build_decision_log_entry
from maestro_ai_agent.orchestrator.enums import (
    DecisionExecutionFootprint,
    PlanningRunMode,
    PostActionValidationOutcome,
    RunStepPhase,
    StepValidationStatus,
)
from maestro_ai_agent.orchestrator.models import (
    BeforeAfterObservationSummary,
    PostActionValidationRecord,
    RunDecisionLogEntry,
    StepRunState,
)
from maestro_ai_agent.orchestrator.run_report import build_run_report


def _minimal_step(
    *,
    phase: RunStepPhase,
    validation_status: StepValidationStatus,
    post: PostActionValidationRecord | None,
) -> StepRunState:
    intent = StepIntent(
        intent_id=uuid4(),
        scenario_step_index=0,
        primary_action=ActionType.TAP,
        goal_summary="g",
        raw_step_text="Tap 'OK'",
        validation_goals=[],
    )
    return StepRunState(
        scenario_step_index=0,
        raw_step_text="Tap 'OK'",
        intent=intent,
        phase=phase,
        validation_status=validation_status,
        post_action_validation=post,
    )


def test_decision_log_includes_post_action_validation_outcome() -> None:
    summary = BeforeAfterObservationSummary(before_node_count=1, after_node_count=2)
    record = PostActionValidationRecord(
        outcome=PostActionValidationOutcome.VALIDATED,
        before_after_summary=summary,
        evidence=[],
        notes=[],
    )
    step = _minimal_step(
        phase=RunStepPhase.VALIDATED,
        validation_status=StepValidationStatus.PASSED,
        post=record,
    )
    entry = build_decision_log_entry(
        step,
        planning_only=False,
        planning_mode=PlanningRunMode.OBSERVE_PLAN_EXECUTE,
    )
    assert entry.post_action_validation_outcome is PostActionValidationOutcome.VALIDATED
    assert entry.execution_footprint is (
        DecisionExecutionFootprint.PROVIDER_SUCCESS_VALIDATION_PASSED
    )


def test_run_report_counts_validation_outcomes_from_footprints() -> None:
    summary = BeforeAfterObservationSummary(before_node_count=1, after_node_count=1)

    def row(phase: RunStepPhase, post: PostActionValidationRecord | None) -> RunDecisionLogEntry:
        vstat = (
            StepValidationStatus.PASSED
            if phase is RunStepPhase.VALIDATED
            else StepValidationStatus.FAILED
        )
        st = _minimal_step(phase=phase, validation_status=vstat, post=post)
        return build_decision_log_entry(
            st,
            planning_only=False,
            planning_mode=PlanningRunMode.OBSERVE_PLAN_EXECUTE,
        )

    log = [
        row(
            RunStepPhase.VALIDATED,
            PostActionValidationRecord(
                outcome=PostActionValidationOutcome.VALIDATED,
                before_after_summary=summary,
            ),
        ),
        row(
            RunStepPhase.VALIDATION_FAILED,
            PostActionValidationRecord(
                outcome=PostActionValidationOutcome.VALIDATION_FAILED,
                before_after_summary=summary,
            ),
        ),
    ]
    report = build_run_report(
        run_id=uuid4(),
        planning_mode=PlanningRunMode.OBSERVE_PLAN_EXECUTE,
        decision_log=log,
        stopped_after_first=False,
        max_steps_applied=False,
    )
    assert report.steps_validation_passed == 1
    assert report.steps_validation_failed == 1
    assert "validation_failed=1" in report.summary
