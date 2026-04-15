"""Tests for deterministic target hint inference."""

from uuid import uuid4

from maestro_ai_agent.domain.enums import ActionType, ValidationSignalType
from maestro_ai_agent.domain.intent import StepIntent, ValidationGoal
from maestro_ai_agent.domain.selectors.intent_match import infer_target_hints
from maestro_ai_agent.domain.selectors.target_hints import ControlKind


def test_infer_hints_extracts_quotes_and_sign_in_semantics() -> None:
    intent = StepIntent(
        intent_id=uuid4(),
        scenario_step_index=0,
        primary_action=ActionType.TAP,
        goal_summary="tap sign in",
        raw_step_text='Tap "Sign in" to continue.',
        validation_goals=[],
    )
    hints = infer_target_hints(intent)
    assert "Sign in" in hints.desired_texts
    assert any("sign in" in kw for kw in hints.semantic_keywords)
    assert hints.preferred_control_kind is ControlKind.BUTTON


def test_tap_without_quotes_adds_tail_as_desired_hint() -> None:
    intent = StepIntent(
        intent_id=uuid4(),
        scenario_step_index=0,
        primary_action=ActionType.TAP,
        goal_summary="tap uk",
        raw_step_text="Tap UK",
        validation_goals=[],
    )
    hints = infer_target_hints(intent)
    assert "UK" in hints.desired_texts


def test_tap_qualifier_surfaces_in_target_hints() -> None:
    intent = StepIntent(
        intent_id=uuid4(),
        scenario_step_index=0,
        primary_action=ActionType.TAP,
        goal_summary="tap shop tab",
        raw_step_text="Tap 'Shop' in the bottom navigation",
        validation_goals=[],
    )
    hints = infer_target_hints(intent)
    assert hints.container_hint == "tab_bar"
    assert hints.qualifier_phrase_raw == "the bottom navigation"


def test_input_text_prefers_edittext_control_kind() -> None:
    intent = StepIntent(
        intent_id=uuid4(),
        scenario_step_index=1,
        primary_action=ActionType.INPUT_TEXT,
        goal_summary="enter email",
        raw_step_text='Enter "user@example.com" into the email field.',
        validation_goals=[
            ValidationGoal(
                goal_id="vg1",
                signal=ValidationSignalType.TEXT_CONTAINS,
                description="email accepted",
                target_hint="user@example.com",
            )
        ],
    )
    hints = infer_target_hints(intent)
    assert "user@example.com" in hints.desired_texts
    assert hints.preferred_control_kind is ControlKind.EDITTEXT
