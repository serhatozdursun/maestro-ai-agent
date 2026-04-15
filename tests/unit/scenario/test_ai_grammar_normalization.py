"""AI grammar lines → canonical actions and planner convergence."""

from __future__ import annotations

from maestro_ai_agent.domain.enums import ActionType, Platform
from maestro_ai_agent.domain.planning import plan_intents
from maestro_ai_agent.scenario.planning_adapter import build_parsed_scenario_from_canonical
from maestro_ai_agent.scenario.scenario_normalizer import normalize_scenario_text


def _intents_from_body(body: str):
    norm = normalize_scenario_text(body.strip(), enable_ai_fallback=False)
    parsed = build_parsed_scenario_from_canonical(
        norm.canonical,
        app_id="com.example",
        platform=Platform.ANDROID,
    )
    return plan_intents(parsed), norm


def test_press_enter_parsing() -> None:
    intents, norm = _intents_from_body("Enter 'shoe'\nPress Enter\n")
    assert norm.canonical.steps[1].action == "press_key"
    assert norm.canonical.steps[1].value == "enter"
    assert intents[1].primary_action is ActionType.PRESS_KEY


def test_assert_not_visible_canonical() -> None:
    _, norm = _intents_from_body('Assert not visible "Loading"\n')
    assert norm.canonical.steps[0].action == "assert_not_visible"
    assert norm.canonical.steps[0].target == "Loading"


def test_scroll_until_visible_canonical() -> None:
    _, norm = _intents_from_body("Scroll until visible 'Checkout'\n")
    assert norm.canonical.steps[0].action == "scroll_until_visible"
    assert norm.canonical.steps[0].target == "Checkout"


def test_launch_app_slug() -> None:
    _, norm = _intents_from_body("LaunchApp\n")
    assert norm.canonical.steps[0].action == "launch_app"
