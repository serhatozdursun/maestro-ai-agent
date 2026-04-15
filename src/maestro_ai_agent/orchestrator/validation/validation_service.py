"""Post-execution validation using a fresh hierarchy observation (conservative, deterministic)."""

from __future__ import annotations

from collections.abc import Callable

from maestro_ai_agent.domain.enums import ActionType, Platform
from maestro_ai_agent.orchestrator.action_attempt_planning import DIRECT_ASSERT_SURFACE_ID
from maestro_ai_agent.orchestrator.enums import (
    PostActionValidationOutcome,
    RunStepPhase,
    StepValidationStatus,
)
from maestro_ai_agent.orchestrator.models import (
    BeforeAfterObservationSummary,
    ObservationCycleResult,
    PostActionValidationRecord,
    StepRunState,
    ValidationEvidenceItem,
)
from maestro_ai_agent.orchestrator.observation_cycle import build_observation_cycle_result
from maestro_ai_agent.orchestrator.validation.heuristics import (
    PerGoalResult,
    aggregate_goal_verdicts,
    evaluate_ranked_assert_hierarchy,
    evaluate_validation_goal,
    evaluate_without_goals,
)
from maestro_ai_agent.orchestrator.validation.hierarchy_compare import hierarchy_fingerprint
from maestro_ai_agent.services.maestro.models import StructuredScreenObservation
from maestro_ai_agent.services.maestro.screen_service import MaestroScreenService


class PostExecutionValidationService:
    """
    Re-observes the screen after a successful provider action and applies deterministic checks.

    Does not treat ``ActionResult.ok`` as proof of UI success; conclusions come only from
    comparing before/after hierarchies against ``ValidationGoal`` signals when evidence is
    strong enough to avoid false confidence.
    """

    def __init__(self, screen_service: MaestroScreenService) -> None:
        self._screen = screen_service

    def validate_after_provider_success(
        self,
        step: StepRunState,
        *,
        app_id: str,
        platform: Platform,
        device_id: str | None,
        include_screenshot: bool,
    ) -> StepRunState:
        if step.phase is not RunStepPhase.EXECUTED:
            msg = "validate_after_provider_success requires RunStepPhase.EXECUTED."
            raise ValueError(msg)
        if step.observation is None:
            msg = "Pre-action observation is required for validation."
            raise ValueError(msg)
        ex = step.execution_outcome
        if ex is None or ex.action_result is None or not ex.action_result.ok:
            msg = "validate_after_provider_success requires successful provider outcome."
            raise ValueError(msg)

        observer: Callable[..., StructuredScreenObservation] = self._screen.observe_current_screen
        structured = observer(
            app_id=app_id,
            platform=platform,
            device_id=device_id,
            include_screenshot=include_screenshot,
        )
        post = build_observation_cycle_result(structured)
        before_h = step.observation.hierarchy
        after_h = post.hierarchy

        before_fp = hierarchy_fingerprint(before_h)
        after_fp = hierarchy_fingerprint(after_h)
        summary = BeforeAfterObservationSummary(
            before_node_count=before_fp[0],
            after_node_count=after_fp[0],
            before_parse_warnings=list(before_h.parse_warnings),
            after_parse_warnings=list(after_h.parse_warnings),
        )

        text_in = ex.text_input_used
        goals = step.intent.validation_goals

        if not after_h.nodes:
            record = PostActionValidationRecord(
                outcome=PostActionValidationOutcome.SKIPPED,
                before_after_summary=summary,
                evidence=[
                    ValidationEvidenceItem(
                        code="EMPTY_AFTER_HIERARCHY",
                        detail="Post-action hierarchy has no nodes; skipping strict validation.",
                        contributes="inconclusive",
                    ),
                ],
                notes=["validation_skipped: insufficient post-action hierarchy."],
            )
            return _apply_record(step, post, record)

        if step.intent.primary_action in (
            ActionType.ASSERT_VISIBLE,
            ActionType.ASSERT_NOT_VISIBLE,
        ) and step.planned_attempt is not None:
            pa = step.planned_attempt
            if pa.chosen_candidate_id != DIRECT_ASSERT_SURFACE_ID:
                v_ranked, lines_ranked = evaluate_ranked_assert_hierarchy(
                    after=after_h,
                    intent=step.intent,
                    expression=(pa.expression or "").strip(),
                    selector_type=pa.selector_type,
                )
                ev_ranked = [
                    ValidationEvidenceItem(
                        code="RANKED_ASSERT_HIERARCHY",
                        detail=line,
                        contributes=v_ranked.value,
                    )
                    for line in lines_ranked
                ]
                record = _record_from_aggregate(
                    v_ranked,
                    lines_ranked,
                    summary,
                    evidence=ev_ranked,
                )
                return _apply_record(step, post, record)

        if not goals:
            verdict, lines = evaluate_without_goals(
                before=before_h,
                after=after_h,
                intent=step.intent,
                text_input_used=text_in,
            )
            record = _record_from_aggregate(verdict, lines, summary)
            record = _with_input_validation_reporting(step, record)
            return _apply_record(step, post, record)

        blocker_episode = (
            step.blocker_episode
            if step.intent.primary_action is ActionType.DISMISS_BLOCKER
            else None
        )
        results: list[tuple[PerGoalResult, str]] = []
        for goal in goals:
            results.append(
                evaluate_validation_goal(
                    goal=goal,
                    before=before_h,
                    after=after_h,
                    intent_action=step.intent.primary_action,
                    text_input_used=text_in,
                    blocker_episode=blocker_episode,
                ),
            )
        verdict, lines = aggregate_goal_verdicts(results)
        evidence = [
            ValidationEvidenceItem(
                code="GOAL_SIGNAL",
                detail=line,
                contributes=r[0].value,
            )
            for r, line in zip(results, lines, strict=True)
        ]
        record = _record_from_aggregate(verdict, lines, summary, evidence=evidence)
        record = _with_input_validation_reporting(step, record)
        return _apply_record(step, post, record)


def _with_input_validation_reporting(
    step: StepRunState,
    record: PostActionValidationRecord,
) -> PostActionValidationRecord:
    """Prepend explicit policy + notes for INPUT_TEXT post-action validation."""
    if step.intent.primary_action is not ActionType.INPUT_TEXT:
        return record
    policy = ValidationEvidenceItem(
        code="INPUT_VALIDATION_POLICY",
        detail=(
            "INPUT_TEXT validation is strict: pass only when the literal appears on an "
            "input-like hierarchy node (including value/query/hint attributes), or on a raw "
            "CSV line that also hints an input control (EditText, value=, query=, SearchView, "
            "etc.); otherwise inconclusive. Maestro tool success does not imply the value "
            "landed in the field."
        ),
        contributes=None,
    )
    extra_notes = [
        "input_validation: reflection checked (input-like nodes + input-ish CSV lines).",
        *record.notes,
    ]
    return record.model_copy(
        update={
            "evidence": [policy, *record.evidence],
            "notes": extra_notes,
        },
    )


def _record_from_aggregate(
    verdict: PerGoalResult,
    lines: list[str],
    summary: BeforeAfterObservationSummary,
    *,
    evidence: list[ValidationEvidenceItem] | None = None,
) -> PostActionValidationRecord:
    ev = evidence or [
        ValidationEvidenceItem(
            code="AGGREGATE",
            detail=line,
            contributes=verdict.value,
        )
        for line in lines
    ]
    if verdict is PerGoalResult.FAIL:
        return PostActionValidationRecord(
            outcome=PostActionValidationOutcome.VALIDATION_FAILED,
            before_after_summary=summary,
            evidence=ev,
            notes=lines,
        )
    if verdict is PerGoalResult.INCONCLUSIVE:
        return PostActionValidationRecord(
            outcome=PostActionValidationOutcome.INCONCLUSIVE,
            before_after_summary=summary,
            evidence=ev,
            notes=lines,
        )
    return PostActionValidationRecord(
        outcome=PostActionValidationOutcome.VALIDATED,
        before_after_summary=summary,
        evidence=ev,
        notes=lines,
    )


def _apply_record(
    step: StepRunState,
    post_observation: ObservationCycleResult,
    record: PostActionValidationRecord,
) -> StepRunState:
    if record.outcome is PostActionValidationOutcome.VALIDATED:
        phase = RunStepPhase.VALIDATED
        vstatus = StepValidationStatus.PASSED
    elif record.outcome is PostActionValidationOutcome.VALIDATION_FAILED:
        phase = RunStepPhase.VALIDATION_FAILED
        vstatus = StepValidationStatus.FAILED
    elif record.outcome is PostActionValidationOutcome.INCONCLUSIVE:
        phase = RunStepPhase.VALIDATION_INCONCLUSIVE
        vstatus = StepValidationStatus.INCONCLUSIVE
    elif record.outcome is PostActionValidationOutcome.SKIPPED:
        phase = RunStepPhase.VALIDATION_SKIPPED
        vstatus = StepValidationStatus.SKIPPED
    else:
        phase = RunStepPhase.VALIDATION_INCONCLUSIVE
        vstatus = StepValidationStatus.INCONCLUSIVE

    extra = [*(step.warnings or [])]
    extra.extend(record.notes)
    extra.append(
        f"Post-action validation outcome: {record.outcome.value} "
        f"(nodes before/after: {record.before_after_summary.before_node_count}/"
        f"{record.before_after_summary.after_node_count}).",
    )
    return step.model_copy(
        update={
            "phase": phase,
            "validation_status": vstatus,
            "post_action_observation": post_observation,
            "post_action_validation": record,
            "warnings": extra,
        },
    )
