"""Inline grammar ``run_flow`` mapping (bounded templates)."""

from __future__ import annotations

from uuid import uuid4

from maestro_ai_agent.domain.enums import ActionType, SelectorType
from maestro_ai_agent.domain.intent import StepIntent
from maestro_ai_agent.orchestrator.action_attempt_planning import (
    DIRECT_INLINE_FLOW_CANDIDATE_ID,
    _flow_expression,
)
from maestro_ai_agent.orchestrator.execution.action_mapping import (
    SupportedProviderAction,
    map_planned_to_provider_action,
)
from maestro_ai_agent.orchestrator.models import PlannedActionAttempt


def test_press_key_requires_app_id_for_run_flow() -> None:
    intent = StepIntent(
        intent_id=uuid4(),
        scenario_step_index=0,
        primary_action=ActionType.PRESS_KEY,
        goal_summary="press",
        raw_step_text="Press Enter",
        validation_goals=[],
    )
    planned = PlannedActionAttempt(
        intent_id=intent.intent_id,
        scenario_step_index=0,
        action=ActionType.PRESS_KEY,
        chosen_candidate_id=DIRECT_INLINE_FLOW_CANDIDATE_ID,
        expression=_flow_expression("press_key", "enter"),
        selector_type=SelectorType.TEXT,
        score=0.0,
        explanation_summary="x",
    )
    d0 = map_planned_to_provider_action(intent, planned, raw_step_text=intent.raw_step_text)
    assert d0.action is SupportedProviderAction.NONE
    d1 = map_planned_to_provider_action(
        intent,
        planned,
        raw_step_text=intent.raw_step_text,
        app_id="com.example.app",
    )
    assert d1.action is SupportedProviderAction.RUN_FLOW
    assert d1.flow_yaml is not None
    assert "pressKey" in d1.flow_yaml
    assert "com.example.app" in d1.flow_yaml


def test_dismiss_blocker_inline_marker_is_not_run_flow() -> None:
    """``DISMISS_BLOCKER`` is executed by the blocker engine, not static YAML."""
    intent = StepIntent(
        intent_id=uuid4(),
        scenario_step_index=0,
        primary_action=ActionType.DISMISS_BLOCKER,
        goal_summary="dismiss",
        raw_step_text="Dismiss popup",
        validation_goals=[],
    )
    planned = PlannedActionAttempt(
        intent_id=intent.intent_id,
        scenario_step_index=0,
        action=ActionType.DISMISS_BLOCKER,
        chosen_candidate_id=DIRECT_INLINE_FLOW_CANDIDATE_ID,
        expression=_flow_expression("dismiss_blocker", ""),
        selector_type=SelectorType.TEXT,
        score=0.0,
        explanation_summary="x",
    )
    d = map_planned_to_provider_action(
        intent,
        planned,
        raw_step_text=intent.raw_step_text,
        app_id="com.example.app",
    )
    assert d.action is SupportedProviderAction.NONE
    assert d.unsupported_reason is not None
    assert "blocker engine" in d.unsupported_reason.lower()
