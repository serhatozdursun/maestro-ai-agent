"""Tests for lightweight deterministic planning."""

from maestro_ai_agent.domain.enums import ActionType, Platform, ValidationSignalType
from maestro_ai_agent.domain.parse_scenario import parse_scenario_input
from maestro_ai_agent.domain.planning import plan_intents, quoted_literal_from_step_text
from maestro_ai_agent.domain.scenario import ScenarioInput


def test_plan_classifies_launch_tap_input_assert() -> None:
    body = """Open the retail app.
Tap "Sign in".
Enter email "user@example.com" into the email field.
Assert that the text "Welcome" is visible.
"""
    parsed = parse_scenario_input(
        ScenarioInput(scenario_text=body, app_id="com.shop", platform=Platform.ANDROID)
    )
    intents = plan_intents(parsed)
    actions = [i.primary_action for i in intents]
    assert actions == [
        ActionType.LAUNCH_APP,
        ActionType.TAP,
        ActionType.INPUT_TEXT,
        ActionType.ASSERT_VISIBLE,
    ]
    assert intents[0].validation_goals[0].signal == ValidationSignalType.HIERARCHY_CHANGED
    assert intents[2].validation_goals[0].signal == ValidationSignalType.TEXT_CONTAINS
    assert intents[2].validation_goals[0].target_hint == "user@example.com"
    assert intents[3].validation_goals[0].target_hint == "Welcome"


def test_quoted_literal_from_step_text() -> None:
    assert quoted_literal_from_step_text("""Type 'hello'""") == "hello"
    assert quoted_literal_from_step_text("Type hello") is None


def test_open_sign_in_is_not_launch() -> None:
    """Heuristic: 'open' without ' app' substring should not be treated as launch."""
    parsed = parse_scenario_input(
        ScenarioInput(
            scenario_text='Open "Sign in"',
            app_id="com.example",
            platform=Platform.IOS,
        )
    )
    intents = plan_intents(parsed)
    assert intents[0].primary_action == ActionType.UNKNOWN
