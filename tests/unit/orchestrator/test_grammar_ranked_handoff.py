"""Ranked selector preferred over step text for scroll-until and assert grammar steps."""

from __future__ import annotations

from uuid import uuid4

from maestro_ai_agent.domain.confidence import ConfidenceScore
from maestro_ai_agent.domain.enums import ActionType, SelectorType
from maestro_ai_agent.domain.intent import StepIntent
from maestro_ai_agent.domain.selector import SelectorCandidate
from maestro_ai_agent.domain.selectors.explanation import SelectorExplanation
from maestro_ai_agent.domain.selectors.ranking_types import RankedSelectorCandidate, SelectorRankingResult
from maestro_ai_agent.orchestrator.action_attempt_planning import (
    DIRECT_ASSERT_SURFACE_ID,
    _try_grammar_synthetic_planned_attempt,
    plan_action_attempt_from_ranking,
)
from maestro_ai_agent.orchestrator.execution.action_mapping import (
    SupportedProviderAction,
    map_planned_to_provider_action,
    try_parse_inline_flow_marker,
)
from maestro_ai_agent.orchestrator.execution.inline_flow_yaml import (
    build_scroll_until_visible_flow_yaml,
    build_scroll_until_visible_ranked_flow_yaml,
)


def _intent(*, action: ActionType, text: str) -> StepIntent:
    return StepIntent(
        intent_id=uuid4(),
        scenario_step_index=0,
        primary_action=action,
        goal_summary="g",
        raw_step_text=text,
        validation_goals=[],
    )


def _ranking_id(expression: str) -> SelectorRankingResult:
    cand = SelectorCandidate(
        candidate_id="c-id",
        selector_type=SelectorType.ID,
        expression=expression,
        rationale="unit",
        rank=0,
        confidence=ConfidenceScore(value=0.9),
    )
    ranked = RankedSelectorCandidate(
        candidate=cand,
        score=10.0,
        evidence=[],
        explanation=SelectorExplanation(summary="ok", codes=[]),
    )
    return SelectorRankingResult(ordered=[ranked], primary=ranked)


def test_scroll_until_visible_prefers_ranked_id_yaml() -> None:
    intent = _intent(
        action=ActionType.SCROLL_UNTIL_VISIBLE,
        text="ScrollUntilVisible 'Promo'",
    )
    planned = plan_action_attempt_from_ranking(
        intent=intent,
        ranking=_ranking_id("id:carousel.root"),
        scenario_step_index=0,
        raw_step_text=intent.raw_step_text,
    )
    assert planned is not None
    assert planned.chosen_candidate_id == "c-id"
    marker = try_parse_inline_flow_marker(planned.expression)
    assert marker is not None
    tag, payload = marker
    assert tag == "scroll_until_ranked"
    assert "id" in payload
    assert "carousel.root" in payload
    dec = map_planned_to_provider_action(
        intent,
        planned,
        raw_step_text=intent.raw_step_text,
        app_id="com.example.app",
    )
    assert dec.action is SupportedProviderAction.RUN_FLOW
    assert dec.flow_yaml == build_scroll_until_visible_ranked_flow_yaml(
        app_id="com.example.app",
        selector_type=SelectorType.ID,
        expression="id:carousel.root",
    )


def test_scroll_until_visible_empty_ranking_uses_quoted_text_yaml() -> None:
    intent = _intent(
        action=ActionType.SCROLL_UNTIL_VISIBLE,
        text="ScrollUntilVisible 'Promo'",
    )
    planned = plan_action_attempt_from_ranking(
        intent=intent,
        ranking=SelectorRankingResult(ordered=[], primary=None),
        scenario_step_index=0,
        raw_step_text=intent.raw_step_text,
    )
    assert planned is not None
    marker = try_parse_inline_flow_marker(planned.expression)
    assert marker == ("scroll_until", "Promo")
    dec = map_planned_to_provider_action(
        intent,
        planned,
        raw_step_text=intent.raw_step_text,
        app_id="com.example.app",
    )
    assert dec.flow_yaml == build_scroll_until_visible_flow_yaml(
        app_id="com.example.app",
        element_text="Promo",
    )


def test_assert_visible_prefers_ranked_mapping() -> None:
    intent = _intent(action=ActionType.ASSERT_VISIBLE, text="AssertVisible 'Banner'")
    planned = plan_action_attempt_from_ranking(
        intent=intent,
        ranking=_ranking_id("id:home.banner"),
        scenario_step_index=0,
        raw_step_text=intent.raw_step_text,
    )
    assert planned is not None
    assert planned.chosen_candidate_id == "c-id"
    assert planned.expression == "id:home.banner"
    dec = map_planned_to_provider_action(
        intent,
        planned,
        raw_step_text=intent.raw_step_text,
        app_id="com.example.app",
    )
    assert dec.action is SupportedProviderAction.ASSERT_HIERARCHY
    assert dec.assert_ranked_expression == "id:home.banner"
    assert dec.assert_ranked_selector_type is SelectorType.ID
    assert dec.assert_surface_literal is None


def test_assert_visible_literal_only_uses_surface_id() -> None:
    intent = _intent(action=ActionType.ASSERT_VISIBLE, text="AssertVisible 'Banner'")
    grammar = _try_grammar_synthetic_planned_attempt(
        intent=intent,
        scenario_step_index=0,
        raw_step_text=intent.raw_step_text,
    )
    assert grammar is not None
    assert grammar.chosen_candidate_id == DIRECT_ASSERT_SURFACE_ID
    assert grammar.expression == "Banner"
