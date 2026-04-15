"""Unit tests for deterministic post-action validation heuristics."""

from __future__ import annotations

from uuid import uuid4

from maestro_ai_agent.domain.enums import ActionType, ValidationSignalType
from maestro_ai_agent.domain.hierarchy import HierarchyNode, HierarchySnapshot
from maestro_ai_agent.domain.intent import StepIntent, ValidationGoal
from maestro_ai_agent.orchestrator.validation.heuristics import (
    PerGoalResult,
    aggregate_goal_verdicts,
    evaluate_validation_goal,
    evaluate_without_goals,
)


def _h(*nodes: HierarchyNode) -> HierarchySnapshot:
    return HierarchySnapshot(nodes=list(nodes), raw_csv="fixture")


def test_text_visible_passes_when_hint_present_after() -> None:
    before = _h(
        HierarchyNode(
            node_index="1",
            depth=0,
            parent_index=None,
            text="Old",
            class_name="android.widget.TextView",
        ),
    )
    after = _h(
        HierarchyNode(
            node_index="1",
            depth=0,
            parent_index=None,
            text="Welcome",
            class_name="android.widget.TextView",
        ),
    )
    goal = ValidationGoal(
        goal_id="g1",
        signal=ValidationSignalType.TEXT_VISIBLE,
        description="see welcome",
        target_hint="Welcome",
    )
    v, line = evaluate_validation_goal(
        goal=goal,
        before=before,
        after=after,
        intent_action=ActionType.TAP,
        text_input_used=None,
    )
    assert v is PerGoalResult.PASS
    assert "Welcome" in line


def test_text_visible_fails_when_hint_absent_with_nonempty_hierarchy() -> None:
    before = _h(
        HierarchyNode(node_index="1", depth=0, parent_index=None, text="A", class_name="tv"),
    )
    after = _h(
        HierarchyNode(node_index="1", depth=0, parent_index=None, text="B", class_name="tv"),
    )
    goal = ValidationGoal(
        goal_id="g1",
        signal=ValidationSignalType.TEXT_VISIBLE,
        description="see X",
        target_hint="MissingLabel",
    )
    v, line = evaluate_validation_goal(
        goal=goal,
        before=before,
        after=after,
        intent_action=ActionType.TAP,
        text_input_used=None,
    )
    assert v is PerGoalResult.FAIL
    assert "not found" in line.lower()


def test_hierarchy_changed_inconclusive_when_identical() -> None:
    n = HierarchyNode(node_index="1", depth=0, parent_index=None, text="X", class_name="tv")
    h = _h(n)
    goal = ValidationGoal(
        goal_id="g1",
        signal=ValidationSignalType.HIERARCHY_CHANGED,
        description="changed",
        target_hint=None,
    )
    v, line = evaluate_validation_goal(
        goal=goal,
        before=h,
        after=h,
        intent_action=ActionType.TAP,
        text_input_used=None,
    )
    assert v is PerGoalResult.INCONCLUSIVE
    assert "unchanged" in line.lower()


def test_tap_hierarchy_changed_inconclusive_when_target_hint_absent_before_after() -> None:
    before = _h(
        HierarchyNode(node_index="1", depth=0, parent_index=None, text="Cart", class_name="tv"),
    )
    after = _h(
        HierarchyNode(node_index="1", depth=0, parent_index=None, text="Back", class_name="tv"),
    )
    goal = ValidationGoal(
        goal_id="g1",
        signal=ValidationSignalType.HIERARCHY_CHANGED,
        description="tap changed",
        target_hint="Checkout",
    )
    v, line = evaluate_validation_goal(
        goal=goal,
        before=before,
        after=after,
        intent_action=ActionType.TAP,
        text_input_used=None,
    )
    assert v is PerGoalResult.INCONCLUSIVE
    assert "off-target tap" in line.lower()


def test_dismiss_blocker_no_pattern_passes_without_hierarchy_change() -> None:
    n = HierarchyNode(node_index="1", depth=0, parent_index=None, text="X", class_name="tv")
    h = _h(n)
    goal = ValidationGoal(
        goal_id="vg-dismiss-1",
        signal=ValidationSignalType.HIERARCHY_CHANGED,
        description="dismiss",
        target_hint=None,
    )
    v, line = evaluate_validation_goal(
        goal=goal,
        before=h,
        after=h,
        intent_action=ActionType.DISMISS_BLOCKER,
        text_input_used=None,
        blocker_episode={"code": "no_known_blocking_pattern"},
    )
    assert v is PerGoalResult.PASS
    assert "no registry pattern" in line


def test_aggregate_any_fail_wins() -> None:
    agg, lines = aggregate_goal_verdicts(
        [
            (PerGoalResult.PASS, "a"),
            (PerGoalResult.FAIL, "b"),
        ],
    )
    assert agg is PerGoalResult.FAIL
    assert "b" in lines


def test_tap_without_goals_passes_when_selected_changes() -> None:
    before = _h(
        HierarchyNode(
            node_index="1",
            depth=0,
            parent_index=None,
            text="Tab",
            class_name="android.widget.TextView",
            attributes={"selected": "false"},
        ),
    )
    after = _h(
        HierarchyNode(
            node_index="1",
            depth=0,
            parent_index=None,
            text="Tab",
            class_name="android.widget.TextView",
            attributes={"selected": "true"},
        ),
    )
    intent = StepIntent(
        intent_id=uuid4(),
        scenario_step_index=0,
        primary_action=ActionType.TAP,
        goal_summary="x",
        raw_step_text="Tap tab",
        validation_goals=[],
    )
    v, lines = evaluate_without_goals(
        before=before,
        after=after,
        intent=intent,
        text_input_used=None,
    )
    assert v is PerGoalResult.PASS
    assert any("selected" in line.lower() for line in lines)


def test_text_contains_input_inconclusive_without_reflection() -> None:
    before = _h(
        HierarchyNode(node_index="1", depth=0, parent_index=None, text="x", class_name="tv"),
    )
    after = _h(
        HierarchyNode(node_index="1", depth=0, parent_index=None, text="y", class_name="tv"),
    )
    goal = ValidationGoal(
        goal_id="g1",
        signal=ValidationSignalType.TEXT_CONTAINS,
        description="typed",
        target_hint="hello",
    )
    v, line = evaluate_validation_goal(
        goal=goal,
        before=before,
        after=after,
        intent_action=ActionType.INPUT_TEXT,
        text_input_used="hello",
    )
    assert v is PerGoalResult.INCONCLUSIVE
    assert "INPUT_TEXT" in line


def test_text_contains_non_input_fails_when_hint_absent() -> None:
    before = _h(
        HierarchyNode(node_index="1", depth=0, parent_index=None, text="a", class_name="tv"),
    )
    after = _h(
        HierarchyNode(node_index="1", depth=0, parent_index=None, text="b", class_name="tv"),
    )
    goal = ValidationGoal(
        goal_id="g1",
        signal=ValidationSignalType.TEXT_CONTAINS,
        description="contains",
        target_hint="missing",
    )
    v, line = evaluate_validation_goal(
        goal=goal,
        before=before,
        after=after,
        intent_action=ActionType.TAP,
        text_input_used=None,
    )
    assert v is PerGoalResult.FAIL
    assert "not reflected" in line.lower()


def test_text_contains_input_passes_via_raw_csv_when_visible_empty() -> None:
    after = HierarchySnapshot(
        nodes=[],
        raw_csv='1,0,"value=hello; class=android.widget.EditText",\n',
    )
    goal = ValidationGoal(
        goal_id="g1",
        signal=ValidationSignalType.TEXT_CONTAINS,
        description="typed",
        target_hint="hello",
    )
    v, line = evaluate_validation_goal(
        goal=goal,
        before=_h(),
        after=after,
        intent_action=ActionType.INPUT_TEXT,
        text_input_used="hello",
    )
    assert v is PerGoalResult.PASS
    assert "raw" in line.lower()


def test_input_without_goals_inconclusive_when_literal_only_on_plain_textview() -> None:
    """Visible substring alone is not evidence; input-like control or input-ish CSV required."""
    after = _h(
        HierarchyNode(
            node_index="1",
            depth=0,
            parent_index=None,
            text="shoe",
            class_name="android.widget.TextView",
        ),
    )
    intent = StepIntent(
        intent_id=uuid4(),
        scenario_step_index=0,
        primary_action=ActionType.INPUT_TEXT,
        goal_summary="x",
        raw_step_text="Enter 'shoe'",
        validation_goals=[],
    )
    v, lines = evaluate_without_goals(
        before=_h(),
        after=after,
        intent=intent,
        text_input_used="shoe",
    )
    assert v is PerGoalResult.INCONCLUSIVE
    assert any("not validated" in line.lower() or "inconclusive" in line.lower() for line in lines)


def test_input_without_goals_passes_when_text_visible() -> None:
    after = _h(
        HierarchyNode(
            node_index="1",
            depth=0,
            parent_index=None,
            text="hello world",
            class_name="android.widget.EditText",
        ),
    )
    intent = StepIntent(
        intent_id=uuid4(),
        scenario_step_index=0,
        primary_action=ActionType.INPUT_TEXT,
        goal_summary="x",
        raw_step_text="Type 'hello'",
        validation_goals=[],
    )
    v, lines = evaluate_without_goals(
        before=_h(),
        after=after,
        intent=intent,
        text_input_used="hello",
    )
    assert v is PerGoalResult.PASS
    assert lines
