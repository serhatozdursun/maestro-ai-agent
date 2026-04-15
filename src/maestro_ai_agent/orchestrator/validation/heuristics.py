"""
Deterministic post-action validation heuristics.

Conservative by design: weak or ambiguous evidence yields inconclusive, not pass.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from maestro_ai_agent.domain.enums import ActionType, SelectorType, ValidationSignalType
from maestro_ai_agent.domain.hierarchy import HierarchySnapshot
from maestro_ai_agent.domain.intent import StepIntent, ValidationGoal
from maestro_ai_agent.orchestrator.validation.hierarchy_compare import (
    hierarchy_meaningfully_changed,
    input_literal_reflected_in_hierarchy,
    ranked_selector_matches_hierarchy,
    selected_state_changed,
    text_substring_present,
)


class PerGoalResult(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    INCONCLUSIVE = "inconclusive"


def evaluate_validation_goal(
    *,
    goal: ValidationGoal,
    before: HierarchySnapshot,
    after: HierarchySnapshot,
    intent_action: ActionType,
    text_input_used: str | None,
    blocker_episode: dict[str, Any] | None = None,
) -> tuple[PerGoalResult, str]:
    """Return (verdict, one-line evidence) for a single goal."""
    hint = (goal.target_hint or "").strip()
    signal = goal.signal

    if signal is ValidationSignalType.CUSTOM:
        return (
            PerGoalResult.INCONCLUSIVE,
            f"{goal.goal_id}: CUSTOM signal not auto-validated.",
        )

    if signal is ValidationSignalType.HIERARCHY_CHANGED:
        if intent_action is ActionType.DISMISS_BLOCKER and blocker_episode:
            code = str(blocker_episode.get("code") or "")
            if code == "no_known_blocking_pattern":
                return (
                    PerGoalResult.PASS,
                    f"{goal.goal_id}: dismiss_blocker — no registry pattern; "
                    "unchanged hierarchy ok.",
                )
            if blocker_episode.get("verified_cleared") is True:
                return (
                    PerGoalResult.PASS,
                    f"{goal.goal_id}: dismiss_blocker — engine verified pattern clearance.",
                )
            if code == "developer_mode_seen_but_allowlist_dismiss_not_found":
                msg = (
                    f"{goal.goal_id}: dismiss_blocker — developer-mode signal "
                    "without safe dismiss; no tap attempted."
                )
                return (PerGoalResult.PASS, msg)
        if hierarchy_meaningfully_changed(before, after):
            if intent_action is ActionType.TAP and hint:
                before_has_hint = text_substring_present(before, hint)
                after_has_hint = text_substring_present(after, hint)
                if not before_has_hint and not after_has_hint:
                    return (
                        PerGoalResult.INCONCLUSIVE,
                        f"{goal.goal_id}: hierarchy changed, but tap hint {hint!r} was absent "
                        "in both before/after hierarchies; possible off-target tap.",
                    )
            return (
                PerGoalResult.PASS,
                f"{goal.goal_id}: hierarchy fingerprint changed after action.",
            )
        return (
            PerGoalResult.INCONCLUSIVE,
            f"{goal.goal_id}: hierarchy fingerprint unchanged; cannot confirm UI update.",
        )

    if signal in (ValidationSignalType.TEXT_VISIBLE, ValidationSignalType.ELEMENT_VISIBLE):
        if not hint:
            return (
                PerGoalResult.INCONCLUSIVE,
                f"{goal.goal_id}: {signal.value} without target_hint.",
            )
        if text_substring_present(after, hint):
            return (
                PerGoalResult.PASS,
                f"{goal.goal_id}: expected text/hint {hint!r} visible after action.",
            )
        if after.parse_warnings or not after.nodes:
            return (
                PerGoalResult.INCONCLUSIVE,
                f"{goal.goal_id}: hint {hint!r} not found; hierarchy weak or empty.",
            )
        return (
            PerGoalResult.FAIL,
            f"{goal.goal_id}: expected visible hint {hint!r} not found after action.",
        )

    if signal is ValidationSignalType.TEXT_CONTAINS:
        if not hint:
            return (
                PerGoalResult.INCONCLUSIVE,
                f"{goal.goal_id}: TEXT_CONTAINS without target_hint.",
            )
        if intent_action is ActionType.INPUT_TEXT:
            lit_ok = input_literal_reflected_in_hierarchy(after, hint)
            typed_ok = bool(text_input_used) and input_literal_reflected_in_hierarchy(
                after,
                text_input_used,
            )
            if lit_ok:
                return (
                    PerGoalResult.PASS,
                    f"{goal.goal_id}: INPUT_TEXT — {hint!r} reflected on input control or raw CSV.",
                )
            if typed_ok and text_input_used:
                return (
                    PerGoalResult.PASS,
                    f"{goal.goal_id}: INPUT_TEXT — entered text {text_input_used!r} reflected on "
                    "input control or raw CSV.",
                )
            if after.parse_warnings or not after.nodes:
                return (
                    PerGoalResult.INCONCLUSIVE,
                    f"{goal.goal_id}: INPUT_TEXT — weak or empty hierarchy; "
                    "cannot assess reflection.",
                )
            return (
                PerGoalResult.INCONCLUSIVE,
                f"{goal.goal_id}: INPUT_TEXT — literal not on input-like nodes or raw CSV; "
                "inconclusive (not validated).",
            )
        if text_substring_present(after, hint):
            return (
                PerGoalResult.PASS,
                f"{goal.goal_id}: hierarchy contains {hint!r} after action.",
            )
        if after.parse_warnings or not after.nodes:
            return (
                PerGoalResult.INCONCLUSIVE,
                f"{goal.goal_id}: text {hint!r} not found; hierarchy weak or empty.",
            )
        return (
            PerGoalResult.FAIL,
            f"{goal.goal_id}: expected text {hint!r} not reflected in hierarchy.",
        )

    if signal is ValidationSignalType.ELEMENT_ABSENT:
        if not hint:
            return (
                PerGoalResult.INCONCLUSIVE,
                f"{goal.goal_id}: ELEMENT_ABSENT without target_hint.",
            )
        if text_substring_present(after, hint):
            return (
                PerGoalResult.FAIL,
                f"{goal.goal_id}: element/text {hint!r} still present after action.",
            )
        return (
            PerGoalResult.PASS,
            f"{goal.goal_id}: hint {hint!r} not visible after action.",
        )

    return (
        PerGoalResult.INCONCLUSIVE,
        f"{goal.goal_id}: signal {signal.value} not handled by heuristics.",
    )


def aggregate_goal_verdicts(
    results: list[tuple[PerGoalResult, str]],
) -> tuple[PerGoalResult, list[str]]:
    """Any fail → fail; else any inconclusive → inconclusive; else pass."""
    lines = [r[1] for r in results]
    verdicts = [r[0] for r in results]
    if PerGoalResult.FAIL in verdicts:
        return PerGoalResult.FAIL, lines
    if PerGoalResult.INCONCLUSIVE in verdicts:
        return PerGoalResult.INCONCLUSIVE, lines
    if not verdicts:
        return PerGoalResult.INCONCLUSIVE, lines
    return PerGoalResult.PASS, lines


def evaluate_without_goals(
    *,
    before: HierarchySnapshot,
    after: HierarchySnapshot,
    intent: StepIntent,
    text_input_used: str | None,
) -> tuple[PerGoalResult, list[str]]:
    """Fallback when ``validation_goals`` is empty (conservative)."""
    if intent.primary_action is ActionType.INPUT_TEXT and text_input_used:
        if input_literal_reflected_in_hierarchy(after, text_input_used):
            return (
                PerGoalResult.PASS,
                [
                    "No explicit goals; entered text reflected on input-like control or raw CSV.",
                ],
            )
        if not after.nodes or after.parse_warnings:
            return (
                PerGoalResult.INCONCLUSIVE,
                [
                    "No explicit goals; cannot confirm input reflection (weak or empty hierarchy).",
                ],
            )
        return (
            PerGoalResult.INCONCLUSIVE,
            [
                "No explicit goals; entered text not found in visible or raw post-hierarchy; "
                "input_validation: inconclusive (not validated).",
            ],
        )

    if intent.primary_action is ActionType.TAP:
        if text_substring_present(before, "developer mode") and not text_substring_present(
            after,
            "developer mode",
        ):
            return (
                PerGoalResult.PASS,
                [
                    "No explicit goals; Developer Mode blocking UI no longer visible after tap.",
                ],
            )
        if selected_state_changed(before, after):
            return (
                PerGoalResult.PASS,
                ["No explicit goals; selected= state changed on at least one node after tap."],
            )
        if hierarchy_meaningfully_changed(before, after):
            return (
                PerGoalResult.PASS,
                ["No explicit goals; hierarchy changed after tap (weak positive signal)."],
            )
        return (
            PerGoalResult.INCONCLUSIVE,
            ["No explicit goals; hierarchy unchanged after tap."],
        )

    return (
        PerGoalResult.INCONCLUSIVE,
        ["No validation goals and no safe default heuristic for this action."],
    )


def evaluate_ranked_assert_hierarchy(
    *,
    after: HierarchySnapshot,
    intent: StepIntent,
    expression: str,
    selector_type: SelectorType,
) -> tuple[PerGoalResult, list[str]]:
    """
    Post-action check for assert steps planned from a ranked id/text selector (not quoted
    literal surface id).
    """
    expr = (expression or "").strip()
    if not expr:
        return (
            PerGoalResult.INCONCLUSIVE,
            ["Ranked assert: empty selector expression; inconclusive."],
        )

    visible = ranked_selector_matches_hierarchy(
        after,
        selector_type=selector_type,
        expression=expr,
    )

    if intent.primary_action is ActionType.ASSERT_VISIBLE:
        if visible:
            return (
                PerGoalResult.PASS,
                [f"Ranked assert: selector {expr!r} ({selector_type.value}) visible in hierarchy."],
            )
        if not after.nodes or after.parse_warnings:
            return (
                PerGoalResult.INCONCLUSIVE,
                [
                    f"Ranked assert: selector {expr!r} not found; weak or ambiguous hierarchy.",
                ],
            )
        return (
            PerGoalResult.FAIL,
            [f"Ranked assert: expected selector {expr!r} not found in post-action hierarchy."],
        )

    if intent.primary_action is ActionType.ASSERT_NOT_VISIBLE:
        if visible:
            return (
                PerGoalResult.FAIL,
                [f"Ranked assert-not: selector {expr!r} still present in hierarchy."],
            )
        if not after.nodes or after.parse_warnings:
            return (
                PerGoalResult.INCONCLUSIVE,
                [
                    "Ranked assert-not: weak or ambiguous hierarchy; cannot confirm absence.",
                ],
            )
        return (
            PerGoalResult.PASS,
            [f"Ranked assert-not: selector {expr!r} not found in post-action hierarchy."],
        )

    return (
        PerGoalResult.INCONCLUSIVE,
        ["Ranked assert: unexpected intent action for ranked assert validation."],
    )
