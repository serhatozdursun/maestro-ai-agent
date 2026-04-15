"""Tests for selector generation, ranking, explanations, and ambiguity handling."""

from uuid import uuid4

from maestro_ai_agent.domain.enums import ActionType, SelectorType
from maestro_ai_agent.domain.hierarchy import HierarchyNode, HierarchySnapshot
from maestro_ai_agent.domain.intent import StepIntent
from maestro_ai_agent.domain.selectors.explanation import SelectorReasonCode
from maestro_ai_agent.domain.selectors.pipeline import (
    apply_ranking_to_intent,
    plan_selector_ranking,
)
from maestro_ai_agent.domain.selectors.target_hints import ControlKind, TargetHints


def make_intent(*, text: str, action: ActionType = ActionType.TAP) -> StepIntent:
    return StepIntent(
        intent_id=uuid4(),
        scenario_step_index=0,
        primary_action=action,
        goal_summary="fixture",
        raw_step_text=text,
        validation_goals=[],
    )


def test_unique_id_outranks_point_for_sign_in() -> None:
    hierarchy = HierarchySnapshot(
        nodes=[
            HierarchyNode(
                node_index="1",
                depth=0,
                parent_index=None,
                resource_id="com.shop:id/sign_in",
                class_name="android.widget.Button",
                text="Sign in",
                bounds="[0,0][200,80]",
            )
        ],
        raw_csv="fixture",
    )
    intent = make_intent(text='Tap "Sign in"')
    ranking = plan_selector_ranking(hierarchy, intent)
    assert ranking.primary is not None
    types_in_order = [entry.candidate.selector_type for entry in ranking.ordered]
    assert types_in_order[0] is SelectorType.ID
    assert SelectorType.POINT in types_in_order
    assert types_in_order.index(SelectorType.ID) < types_in_order.index(SelectorType.POINT)


def test_duplicate_visible_text_emits_relational_and_explanation() -> None:
    hierarchy = HierarchySnapshot(
        nodes=[
            HierarchyNode(
                node_index="10",
                depth=1,
                parent_index="1",
                resource_id="com.app:id/left_ok",
                class_name="android.widget.Button",
                text="OK",
                bounds="[0,0][10,10]",
            ),
            HierarchyNode(
                node_index="11",
                depth=1,
                parent_index="2",
                resource_id="com.app:id/right_ok",
                class_name="android.widget.Button",
                text="OK",
                bounds="[20,0][30,10]",
            ),
            HierarchyNode(
                node_index="1",
                depth=0,
                parent_index=None,
                resource_id="com.app:id/left_pane",
                class_name="android.widget.LinearLayout",
                text=None,
                bounds=None,
            ),
            HierarchyNode(
                node_index="2",
                depth=0,
                parent_index=None,
                resource_id="com.app:id/right_pane",
                class_name="android.widget.LinearLayout",
                text=None,
                bounds=None,
            ),
        ],
        raw_csv="fixture",
    )
    intent = make_intent(text="Tap OK")
    hints = TargetHints(
        desired_texts=["OK"],
        semantic_keywords=["ok"],
        preferred_control_kind=ControlKind.BUTTON,
    )
    ranking = plan_selector_ranking(hierarchy, intent, hints=hints)
    relational = [
        e for e in ranking.ordered if e.candidate.selector_type is SelectorType.RELATIONAL
    ]
    assert relational, "expected relational disambiguation for duplicate text"
    assert any(
        SelectorReasonCode.AMBIGUITY_REDUCED_BY_PARENT in entry.explanation.codes
        for entry in relational
    )


def test_point_candidate_is_last_resort_in_explanation() -> None:
    hierarchy = HierarchySnapshot(
        nodes=[
            HierarchyNode(
                node_index="1",
                depth=0,
                parent_index=None,
                resource_id="com.app:id/go",
                class_name="android.widget.Button",
                text="Go",
                bounds="[0,0][40,40]",
            )
        ],
        raw_csv="fixture",
    )
    intent = make_intent(text='Tap "Go"')
    ranking = plan_selector_ranking(hierarchy, intent)
    point_entry = next(
        e for e in ranking.ordered if e.candidate.selector_type is SelectorType.POINT
    )
    assert SelectorReasonCode.POINT_LAST_RESORT in point_entry.explanation.codes


def test_primary_explanation_contains_unique_text_or_id_signal() -> None:
    hierarchy = HierarchySnapshot(
        nodes=[
            HierarchyNode(
                node_index="5",
                depth=0,
                parent_index=None,
                resource_id="com.app:id/unique",
                class_name="android.widget.TextView",
                text="Welcome",
                bounds="[0,0][10,10]",
            )
        ],
        raw_csv="fixture",
    )
    intent = make_intent(text="Assert Welcome visible", action=ActionType.ASSERT_VISIBLE)
    hints = TargetHints(desired_texts=["Welcome"], preferred_control_kind=ControlKind.TEXTVIEW)
    ranking = plan_selector_ranking(hierarchy, intent, hints=hints)
    assert ranking.primary is not None
    codes = ranking.primary.explanation.codes
    assert (
        SelectorReasonCode.UNIQUE_ID_MATCH in codes
        or SelectorReasonCode.EXACT_VISIBLE_TEXT_MATCH in codes
    )


def test_apply_ranking_to_intent_attaches_ordered_candidates() -> None:
    hierarchy = HierarchySnapshot(
        nodes=[
            HierarchyNode(
                node_index="1",
                depth=0,
                parent_index=None,
                resource_id="com.app:id/x",
                class_name="android.widget.Button",
                text="Next",
                bounds="[0,0][5,5]",
            )
        ],
        raw_csv="fixture",
    )
    intent = make_intent(text='Tap "Next"')
    ranking = plan_selector_ranking(hierarchy, intent)
    updated = apply_ranking_to_intent(intent, ranking)
    assert len(updated.selector_candidates) == len(ranking.ordered)
    assert updated.selector_candidates[0].candidate_id == ranking.ordered[0].candidate.candidate_id
