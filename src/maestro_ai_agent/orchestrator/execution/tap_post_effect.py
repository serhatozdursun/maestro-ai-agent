"""Deterministic classification of tap outcomes for candidate rotation (no AI)."""

from __future__ import annotations

from enum import StrEnum

from maestro_ai_agent.domain.dialog_signals import developer_mode_continue_dialog_visible
from maestro_ai_agent.domain.hierarchy import HierarchySnapshot
from maestro_ai_agent.domain.intent import StepIntent
from maestro_ai_agent.domain.selectors.pipeline import plan_selector_ranking
from maestro_ai_agent.domain.selectors.tap_resolution import TapResolutionSettings
from maestro_ai_agent.orchestrator.action_attempt_planning import plan_action_attempt_from_ranking
from maestro_ai_agent.orchestrator.validation.hierarchy_compare import (
    hierarchy_meaningfully_changed,
)
from maestro_ai_agent.services.maestro.models import ActionResult


class PostTapUiOutcome(StrEnum):
    """Coarse UI effect after a direct ``tap_on`` (before any ``run_flow`` escalation)."""

    NO_EFFECT = "no_effect"
    """Provider reported success but hierarchy fingerprint is unchanged (and no known blocker)."""
    STATE_CHANGED = "state_changed"
    """Hierarchy fingerprint changed vs pre-tap snapshot."""
    TAP_PROVIDER_FAILED = "tap_provider_failed"
    """``tap_on`` returned ``ok=False``."""
    BLOCKER_DIALOG_VISIBLE = "blocker_dialog_visible"
    """Known blocking / dev-mode style dialog still visible on post-tap hierarchy."""


def classify_post_direct_tap(
    *,
    hierarchy_before: HierarchySnapshot,
    hierarchy_after: HierarchySnapshot,
    tap_result: ActionResult,
) -> PostTapUiOutcome:
    """Classify UI state after ``tap_on`` only (deterministic hierarchy evidence)."""
    if not tap_result.ok:
        return PostTapUiOutcome.TAP_PROVIDER_FAILED
    if developer_mode_continue_dialog_visible(hierarchy_after):
        return PostTapUiOutcome.BLOCKER_DIALOG_VISIBLE
    if hierarchy_meaningfully_changed(hierarchy_before, hierarchy_after):
        return PostTapUiOutcome.STATE_CHANGED
    return PostTapUiOutcome.NO_EFFECT


def next_intent_plannable(
    *,
    hierarchy_after: HierarchySnapshot,
    next_intent: StepIntent,
    tap_resolution: TapResolutionSettings | None,
) -> bool:
    """
    True when the next scenario step would yield a planned provider attempt (same as observe→plan).

    Used to detect likely wrong-branch taps: hierarchy moved but the next line cannot be planned.
    """
    tr = tap_resolution or TapResolutionSettings()
    ranking = plan_selector_ranking(
        hierarchy_after,
        next_intent,
        tap_resolution=tr,
    )
    planned = plan_action_attempt_from_ranking(
        intent=next_intent,
        ranking=ranking,
        scenario_step_index=next_intent.scenario_step_index,
        raw_step_text=next_intent.raw_step_text,
    )
    return planned is not None


def next_intent_resolvable_for_branch_probe(
    *,
    hierarchy_after: HierarchySnapshot,
    next_intent: StepIntent | None,
    tap_resolution: TapResolutionSettings | None,
) -> bool:
    """If there is no next intent, treat as resolvable (no wrong-branch probe)."""
    if next_intent is None:
        return True
    return next_intent_plannable(
        hierarchy_after=hierarchy_after,
        next_intent=next_intent,
        tap_resolution=tap_resolution,
    )
