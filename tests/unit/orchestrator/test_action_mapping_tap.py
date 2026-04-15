"""Unit tests for tap_on execution mapping (structured Maestro id/text)."""

from __future__ import annotations

from uuid import uuid4

from maestro_ai_agent.domain.enums import ActionType, SelectorType
from maestro_ai_agent.domain.intent import StepIntent
from maestro_ai_agent.orchestrator.execution.action_mapping import (
    ExecutionMappingDecision,
    SupportedProviderAction,
    map_planned_to_provider_action,
    parse_maestro_tap_arguments_from_planned,
)
from maestro_ai_agent.orchestrator.models import PlannedActionAttempt


def _planned(
    *,
    expression: str,
    selector_type: SelectorType,
) -> PlannedActionAttempt:
    return PlannedActionAttempt(
        intent_id=uuid4(),
        scenario_step_index=0,
        action=ActionType.TAP,
        chosen_candidate_id="c1",
        expression=expression,
        selector_type=selector_type,
        score=1.0,
        explanation_summary="fixture",
    )


def test_parse_id_prefixed_expression() -> None:
    tid, ttxt, err = parse_maestro_tap_arguments_from_planned(
        _planned(expression="id:bag", selector_type=SelectorType.ID),
    )
    assert err is None
    assert tid == "bag"
    assert ttxt is None


def test_parse_text_prefixed_expression() -> None:
    tid, ttxt, err = parse_maestro_tap_arguments_from_planned(
        _planned(expression="text:Cart", selector_type=SelectorType.TEXT),
    )
    assert err is None
    assert tid is None
    assert ttxt == "Cart"


def test_parse_point_is_unsupported() -> None:
    tid, ttxt, err = parse_maestro_tap_arguments_from_planned(
        _planned(expression="point:1,2", selector_type=SelectorType.POINT),
    )
    assert tid is None and ttxt is None
    assert err is not None
    assert "POINT" in err


def test_map_planned_id_candidate_to_tap_on() -> None:
    intent = StepIntent(
        intent_id=uuid4(),
        scenario_step_index=0,
        primary_action=ActionType.TAP,
        goal_summary="tap",
        raw_step_text="Tap 'Cart'",
        validation_goals=[],
    )
    planned = _planned(expression="id:bag", selector_type=SelectorType.ID)
    d = map_planned_to_provider_action(intent, planned, raw_step_text=intent.raw_step_text)
    assert isinstance(d, ExecutionMappingDecision)
    assert d.action is SupportedProviderAction.TAP_ON
    assert d.maestro_tap_id == "bag"
    assert d.maestro_tap_text is None
    assert d.selector == "id:bag"


def test_map_planned_text_candidate_to_tap_on() -> None:
    intent = StepIntent(
        intent_id=uuid4(),
        scenario_step_index=0,
        primary_action=ActionType.TAP,
        goal_summary="tap",
        raw_step_text="Tap 'Cart'",
        validation_goals=[],
    )
    planned = _planned(expression="text:Cart", selector_type=SelectorType.TEXT)
    d = map_planned_to_provider_action(intent, planned, raw_step_text=intent.raw_step_text)
    assert d.action is SupportedProviderAction.TAP_ON
    assert d.maestro_tap_id is None
    assert d.maestro_tap_text == "Cart"


def test_map_planned_point_to_none() -> None:
    intent = StepIntent(
        intent_id=uuid4(),
        scenario_step_index=0,
        primary_action=ActionType.TAP,
        goal_summary="tap",
        raw_step_text="Tap x",
        validation_goals=[],
    )
    planned = _planned(expression="point:1,2", selector_type=SelectorType.POINT)
    d = map_planned_to_provider_action(intent, planned, raw_step_text=intent.raw_step_text)
    assert d.action is SupportedProviderAction.NONE
    assert d.unsupported_reason is not None
