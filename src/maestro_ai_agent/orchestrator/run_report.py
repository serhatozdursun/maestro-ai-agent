"""Assemble human-oriented run reports from accumulated step outcomes."""

from __future__ import annotations

from uuid import UUID

from maestro_ai_agent.orchestrator.enums import (
    DecisionExecutionFootprint,
    PlanningRunMode,
    RunStepPhase,
)
from maestro_ai_agent.orchestrator.models import RunDecisionLogEntry, RunReport


def build_run_report(
    *,
    run_id: UUID,
    planning_mode: PlanningRunMode,
    decision_log: list[RunDecisionLogEntry],
    stopped_after_first: bool,
    max_steps_applied: bool,
) -> RunReport:
    """Summarize an orchestration pass (honest about planning vs provider execution)."""
    steps_observed = sum(1 for e in decision_log if e.step_phase != RunStepPhase.PENDING)
    steps_planned = sum(1 for e in decision_log if e.chosen_candidate_id is not None)
    skipped = sum(1 for e in decision_log if e.step_phase == RunStepPhase.SKIPPED_NO_SELECTOR)

    success_vd = sum(
        1
        for e in decision_log
        if e.execution_footprint is DecisionExecutionFootprint.PROVIDER_SUCCESS_VALIDATION_DEFERRED
    )
    prov_fail = sum(
        1
        for e in decision_log
        if e.execution_footprint is DecisionExecutionFootprint.PROVIDER_INVOKED_FAILED
    )
    unsup = sum(
        1
        for e in decision_log
        if e.execution_footprint is DecisionExecutionFootprint.EXECUTION_UNSUPPORTED
    )
    miss = sum(
        1
        for e in decision_log
        if e.execution_footprint is DecisionExecutionFootprint.MISSING_INPUT_TEXT
    )
    v_ok = sum(
        1
        for e in decision_log
        if e.execution_footprint is DecisionExecutionFootprint.PROVIDER_SUCCESS_VALIDATION_PASSED
    )
    v_fail = sum(
        1
        for e in decision_log
        if e.execution_footprint is DecisionExecutionFootprint.PROVIDER_SUCCESS_VALIDATION_FAILED
    )
    v_inc = sum(
        1
        for e in decision_log
        if e.execution_footprint
        is DecisionExecutionFootprint.PROVIDER_SUCCESS_VALIDATION_INCONCLUSIVE
    )
    v_skip = sum(
        1
        for e in decision_log
        if e.execution_footprint is DecisionExecutionFootprint.PROVIDER_SUCCESS_VALIDATION_SKIPPED
    )

    if planning_mode is PlanningRunMode.PLANNING_ONLY:
        limitations = [
            (
                "Maestro actions were not executed in this run; "
                "all attempts remain in the planned lifecycle."
            ),
            "No post-action validation was performed.",
            "No Maestro YAML was emitted.",
        ]
        if stopped_after_first:
            limitations.append(
                "Run stopped after the first planned step (stop_after_first_planned).",
            )
        if max_steps_applied:
            limitations.append(
                "A max_steps cap was applied; later scenario steps were not considered.",
            )

        if steps_planned:
            summary = (
                f"Planning-only pass: {steps_planned} step(s) received a planned primary "
                f"selector; {skipped} step(s) had no viable primary candidate."
            )
        else:
            summary = (
                "Planning-only pass: no steps received a planned primary selector "
                f"({skipped} skipped)."
            )
    else:
        limitations = [
            "Post-action validation uses hierarchy heuristics only (no screenshots/LLM).",
            "inconclusive means weak evidence, not silent success.",
            "No Maestro YAML was emitted.",
            "No retries and no full autonomous exploration loop.",
        ]
        if stopped_after_first:
            limitations.append(
                "Run stopped after the first step with a planned primary "
                "(stop_after_first_planned).",
            )
        if max_steps_applied:
            limitations.append(
                "A max_steps cap was applied; later scenario steps were not considered.",
            )

        summary = (
            f"Observe-plan-execute: validated={v_ok}, validation_failed={v_fail}, "
            f"inconclusive={v_inc}, validation_skipped={v_skip}; "
            f"provider_fail={prov_fail}; no_selector={skipped}; "
            f"unsupported={unsup}; missing_input={miss}."
        )

    return RunReport(
        run_id=run_id,
        planning_mode=planning_mode,
        summary=summary,
        limitations=limitations,
        decision_log=decision_log,
        total_intents=len(decision_log),
        steps_observed=steps_observed,
        steps_planned=steps_planned,
        steps_without_viable_selector=skipped,
        steps_provider_success_validation_deferred=success_vd,
        steps_provider_failed=prov_fail,
        steps_execution_unsupported=unsup,
        steps_missing_input_text=miss,
        steps_validation_passed=v_ok,
        steps_validation_failed=v_fail,
        steps_validation_inconclusive=v_inc,
        steps_validation_skipped=v_skip,
    )
