"""Grammar SWIPE planning and execution mapping (reuses scroll swipe YAML for plain)."""

from __future__ import annotations

from uuid import uuid4

from maestro_ai_agent.domain.confidence import ConfidenceScore
from maestro_ai_agent.domain.enums import ActionType, SelectorType
from maestro_ai_agent.domain.intent import StepIntent
from maestro_ai_agent.domain.selector import SelectorCandidate
from maestro_ai_agent.domain.selectors.explanation import SelectorExplanation
from maestro_ai_agent.domain.selectors.ranking_types import RankedSelectorCandidate, SelectorRankingResult
from maestro_ai_agent.orchestrator.action_attempt_planning import (
    DIRECT_INLINE_FLOW_CANDIDATE_ID,
    plan_action_attempt_from_ranking,
)
from maestro_ai_agent.orchestrator.enums import RunStepPhase
from maestro_ai_agent.orchestrator.execution.action_mapping import (
    SupportedProviderAction,
    map_planned_to_provider_action,
    try_parse_inline_flow_marker,
)
from maestro_ai_agent.orchestrator.execution.execution_service import classify_skipped_step_for_execute_mode
from maestro_ai_agent.orchestrator.execution.inline_flow_yaml import (
    build_swipe_flow_yaml,
    build_swipe_from_ranked_candidate_flow_yaml,
    build_swipe_from_text_flow_yaml,
)
from maestro_ai_agent.orchestrator.models import StepRunState


def _empty_ranking() -> SelectorRankingResult:
    return SelectorRankingResult(ordered=[], primary=None, resolution_status="not_found")


def _intent(*, action: ActionType, text: str) -> StepIntent:
    return StepIntent(
        intent_id=uuid4(),
        scenario_step_index=0,
        primary_action=action,
        goal_summary="g",
        raw_step_text=text,
        validation_goals=[],
    )


def test_swipe_left_planned_inline_flow_same_tag_as_scroll() -> None:
    intent = _intent(action=ActionType.SWIPE, text="Swipe left")
    planned = plan_action_attempt_from_ranking(
        intent=intent,
        ranking=_empty_ranking(),
        scenario_step_index=0,
        raw_step_text=intent.raw_step_text,
    )
    assert planned is not None
    assert planned.action is ActionType.SWIPE
    assert planned.chosen_candidate_id == DIRECT_INLINE_FLOW_CANDIDATE_ID
    marker = try_parse_inline_flow_marker(planned.expression)
    assert marker == ("scroll", "left")


def test_swipe_right_planned_and_maps_to_run_flow() -> None:
    intent = _intent(action=ActionType.SWIPE, text="  Swipe RIGHT  ")
    planned = plan_action_attempt_from_ranking(
        intent=intent,
        ranking=_empty_ranking(),
        scenario_step_index=0,
        raw_step_text=intent.raw_step_text,
    )
    assert planned is not None
    dec = map_planned_to_provider_action(
        intent,
        planned,
        raw_step_text=intent.raw_step_text,
        app_id="com.example.app",
    )
    assert dec.action is SupportedProviderAction.RUN_FLOW
    assert dec.flow_yaml is not None
    assert dec.flow_yaml == build_swipe_flow_yaml(app_id="com.example.app", direction="right")


def test_scroll_left_unchanged_planning() -> None:
    intent = _intent(action=ActionType.SCROLL, text="Scroll left")
    planned = plan_action_attempt_from_ranking(
        intent=intent,
        ranking=_empty_ranking(),
        scenario_step_index=0,
        raw_step_text=intent.raw_step_text,
    )
    assert planned is not None
    assert planned.action is ActionType.SCROLL
    marker = try_parse_inline_flow_marker(planned.expression)
    assert marker == ("scroll", "left")
    dec = map_planned_to_provider_action(
        intent,
        planned,
        raw_step_text=intent.raw_step_text,
        app_id="com.example.app",
    )
    assert dec.flow_yaml == build_swipe_flow_yaml(app_id="com.example.app", direction="left")


def test_swipe_does_not_consume_ranked_primary() -> None:
    """Unparseable SWIPE must not fall through to a ranked tap primary (none ranked here)."""
    intent = _intent(action=ActionType.SWIPE, text="Swipe diagonally")
    ranking = SelectorRankingResult(ordered=[], primary=None)
    planned = plan_action_attempt_from_ranking(
        intent=intent,
        ranking=ranking,
        scenario_step_index=0,
        raw_step_text=intent.raw_step_text,
    )
    assert planned is None


def test_swipe_unparseable_skipped_then_classify_is_unsupported_with_swipe_reason() -> None:
    intent = _intent(action=ActionType.SWIPE, text="Swipe diagonally")
    step = StepRunState(
        scenario_step_index=0,
        raw_step_text=intent.raw_step_text,
        intent=intent,
        phase=RunStepPhase.SKIPPED_NO_SELECTOR,
    )
    out = classify_skipped_step_for_execute_mode(step)
    assert out.phase is RunStepPhase.UNSUPPORTED
    assert out.execution_outcome is not None
    r = (out.execution_outcome.unsupported_reason or "").lower()
    assert "swipe" in r
    assert "swipe left" in r or "plain" in r or "quoted" in r


def _ranking_with_primary(
    *,
    selector_type: SelectorType,
    expression: str,
) -> SelectorRankingResult:
    cand = SelectorCandidate(
        candidate_id="c0",
        selector_type=selector_type,
        expression=expression,
        rationale="unit",
        rank=0,
        confidence=ConfidenceScore(value=0.9),
    )
    ranked = RankedSelectorCandidate(
        candidate=cand,
        score=10.0,
        evidence=[],
        explanation=SelectorExplanation(summary="primary for test", codes=[]),
    )
    return SelectorRankingResult(ordered=[ranked], primary=ranked)


def test_targeted_swipe_prefers_ranked_id_in_plan_and_yaml() -> None:
    intent = _intent(action=ActionType.SWIPE, text="Swipe left on 'App Stories'")
    ranking = _ranking_with_primary(
        selector_type=SelectorType.ID,
        expression="id:AppStoriesCarouselAccessibilityId",
    )
    planned = plan_action_attempt_from_ranking(
        intent=intent,
        ranking=ranking,
        scenario_step_index=0,
        raw_step_text=intent.raw_step_text,
    )
    assert planned is not None
    assert planned.chosen_candidate_id == "c0"
    assert planned.expression == (
        "__inline_flow__|swipe_on_ranked|left\x1fid\x1fid:AppStoriesCarouselAccessibilityId"
    )
    marker = try_parse_inline_flow_marker(planned.expression)
    assert marker is not None
    tag, _payload = marker
    assert tag == "swipe_on_ranked"
    dec = map_planned_to_provider_action(
        intent,
        planned,
        raw_step_text=intent.raw_step_text,
        app_id="com.example.app",
    )
    assert dec.flow_yaml == build_swipe_from_ranked_candidate_flow_yaml(
        app_id="com.example.app",
        direction="left",
        selector_type=SelectorType.ID,
        expression="id:AppStoriesCarouselAccessibilityId",
    )
    assert "id:" in (dec.flow_yaml or "")
    assert "AppStoriesCarouselAccessibilityId" in (dec.flow_yaml or "")


def test_targeted_swipe_prefers_ranked_text_in_yaml() -> None:
    intent = _intent(action=ActionType.SWIPE, text="Swipe right on 'Cart'")
    ranking = _ranking_with_primary(
        selector_type=SelectorType.TEXT,
        expression="text:Cart",
    )
    planned = plan_action_attempt_from_ranking(
        intent=intent,
        ranking=ranking,
        scenario_step_index=0,
        raw_step_text=intent.raw_step_text,
    )
    assert planned is not None
    dec = map_planned_to_provider_action(
        intent,
        planned,
        raw_step_text=intent.raw_step_text,
        app_id="com.example.app",
    )
    assert dec.flow_yaml == build_swipe_from_ranked_candidate_flow_yaml(
        app_id="com.example.app",
        direction="right",
        selector_type=SelectorType.TEXT,
        expression="text:Cart",
    )


def test_targeted_swipe_relational_primary_falls_back_to_step_text_yaml() -> None:
    intent = _intent(action=ActionType.SWIPE, text="Swipe left on 'Story card'")
    cand = SelectorCandidate(
        candidate_id="c-rel",
        selector_type=SelectorType.RELATIONAL,
        expression="childOf:id:parent",
        rationale="unit",
        rank=0,
        confidence=ConfidenceScore(value=0.5),
    )
    ranked = RankedSelectorCandidate(
        candidate=cand,
        score=3.0,
        evidence=[],
        explanation=SelectorExplanation(summary="relational", codes=[]),
    )
    ranking = SelectorRankingResult(ordered=[ranked], primary=ranked)
    planned = plan_action_attempt_from_ranking(
        intent=intent,
        ranking=ranking,
        scenario_step_index=0,
        raw_step_text=intent.raw_step_text,
    )
    assert planned is not None
    marker = try_parse_inline_flow_marker(planned.expression)
    assert marker is not None
    tag, _p = marker
    assert tag == "swipe_on_text"


def test_targeted_swipe_on_form_maps_to_swipe_from_text_yaml() -> None:
    intent = _intent(action=ActionType.SWIPE, text="Swipe left on 'Story card'")
    planned = plan_action_attempt_from_ranking(
        intent=intent,
        ranking=_empty_ranking(),
        scenario_step_index=0,
        raw_step_text=intent.raw_step_text,
    )
    assert planned is not None
    assert planned.action is ActionType.SWIPE
    marker = try_parse_inline_flow_marker(planned.expression)
    assert marker is not None
    tag, payload = marker
    assert tag == "swipe_on_text"
    assert "\x1f" in payload
    assert payload.startswith("left\x1f")
    assert "Story card" in payload
    dec = map_planned_to_provider_action(
        intent,
        planned,
        raw_step_text=intent.raw_step_text,
        app_id="com.example.app",
    )
    assert dec.action is SupportedProviderAction.RUN_FLOW
    assert dec.flow_yaml == build_swipe_from_text_flow_yaml(
        app_id="com.example.app",
        element_text="Story card",
        direction="left",
    )


def test_targeted_swipe_quoted_then_direction() -> None:
    intent = _intent(action=ActionType.SWIPE, text='Swipe "Story card" right')
    planned = plan_action_attempt_from_ranking(
        intent=intent,
        ranking=_empty_ranking(),
        scenario_step_index=0,
        raw_step_text=intent.raw_step_text,
    )
    assert planned is not None
    dec = map_planned_to_provider_action(
        intent,
        planned,
        raw_step_text=intent.raw_step_text,
        app_id="com.example.app",
    )
    assert dec.action is SupportedProviderAction.RUN_FLOW
    assert "Story card" in (dec.flow_yaml or "")
    assert "RIGHT" in (dec.flow_yaml or "")
