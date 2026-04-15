"""Orchestrator-specific lifecycle enums (distinct from domain StepStatus)."""

from __future__ import annotations

from enum import StrEnum


class RunStepPhase(StrEnum):
    """Where a scenario step is in the observe→plan→execute→validate lifecycle."""

    PENDING = "pending"
    OBSERVED = "observed"
    PLANNED = "planned"
    SKIPPED_NO_SELECTOR = "skipped_no_selector"
    EXECUTION_ATTEMPTED = "execution_attempted"
    EXECUTION_FAILED = "execution_failed"
    UNSUPPORTED = "unsupported"
    MISSING_INPUT_VALUE = "missing_input_value"
    VALIDATION_DEFERRED = "validation_deferred"
    EXECUTED = "executed"
    VALIDATED = "validated"
    VALIDATION_FAILED = "validation_failed"
    VALIDATION_INCONCLUSIVE = "validation_inconclusive"
    VALIDATION_SKIPPED = "validation_skipped"
    FAILED = "failed"


class StepValidationStatus(StrEnum):
    """Post-action validation lifecycle after a provider action (hierarchy heuristics)."""

    NOT_APPLICABLE = "not_applicable"
    DEFERRED = "deferred"
    PASSED = "passed"
    FAILED = "failed"
    INCONCLUSIVE = "inconclusive"
    SKIPPED = "skipped"


class PostActionValidationOutcome(StrEnum):
    """Deterministic post-execution validation result (separate from provider tool success)."""

    NOT_RUN = "not_run"
    SKIPPED = "validation_skipped"
    NOT_APPLICABLE = "validation_not_applicable"
    VALIDATED = "validated"
    VALIDATION_FAILED = "validation_failed"
    INCONCLUSIVE = "validation_inconclusive"


class PlanningRunMode(StrEnum):
    """How the orchestrator advances through steps."""

    PLANNING_ONLY = "planning_only"
    OBSERVE_PLAN_EXECUTE = "observe_plan_execute"


class DecisionExecutionFootprint(StrEnum):
    """Whether a decision row reflects real device execution or planning only."""

    DEVICE_PREFLIGHT_LAUNCH_SUCCEEDED = "device_preflight_launch_succeeded"
    PLANNING_ONLY = "planning_only"
    EXECUTION_UNSUPPORTED = "execution_unsupported"
    MISSING_INPUT_TEXT = "missing_input_text"
    PROVIDER_INVOKED_FAILED = "provider_invoked_failed"
    PROVIDER_SUCCESS_VALIDATION_DEFERRED = "provider_success_validation_deferred"
    PROVIDER_SUCCESS_VALIDATION_PASSED = "provider_success_validation_passed"
    PROVIDER_SUCCESS_VALIDATION_FAILED = "provider_success_validation_failed"
    PROVIDER_SUCCESS_VALIDATION_INCONCLUSIVE = "provider_success_validation_inconclusive"
    PROVIDER_SUCCESS_VALIDATION_SKIPPED = "provider_success_validation_skipped"
    EXECUTED = "executed"
