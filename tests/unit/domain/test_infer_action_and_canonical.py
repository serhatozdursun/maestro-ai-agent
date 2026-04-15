"""Action inference: command-leading heuristics + canonical_action authority."""

from maestro_ai_agent.domain.enums import ActionType, Platform
from maestro_ai_agent.domain.planning import (
    action_type_from_canonical_slug,
    plan_intents,
)
from maestro_ai_agent.domain.scenario import ParsedScenario, ScenarioInput, ScenarioStep
from maestro_ai_agent.scenario.planning_adapter import build_parsed_scenario_from_canonical
from maestro_ai_agent.scenario.scenario_normalizer import normalize_scenario_text


def _parsed_single(line: str, *, canonical_action: str | None = None) -> ParsedScenario:
    return ParsedScenario(
        input=ScenarioInput(scenario_text=line, app_id="com.example", platform=Platform.ANDROID),
        steps=[
            ScenarioStep(
                index=0,
                text=line,
                source_line=1,
                canonical_action=canonical_action,
            ),
        ],
    )


def test_infer_tap_shop() -> None:
    intents = plan_intents(_parsed_single("Tap 'Shop'"))
    assert intents[0].primary_action is ActionType.TAP


def test_infer_tap_shop_in_tab_bar_qualifier() -> None:
    intents = plan_intents(_parsed_single("Tap 'Shop' in the tab bar"))
    assert intents[0].primary_action is ActionType.TAP
    assert intents[0].target_container_hint == "tab_bar"


def test_infer_tap_shop_on_tab_bar_qualifier() -> None:
    intents = plan_intents(_parsed_single("Tap 'Shop' on the tab bar"))
    assert intents[0].primary_action is ActionType.TAP
    assert intents[0].target_container_hint == "tab_bar"


def test_infer_tap_swipe_to_like_not_swipe_action() -> None:
    intents = plan_intents(_parsed_single("Tap 'Swipe To Like'"))
    assert intents[0].primary_action is ActionType.TAP


def test_infer_tap_swipe_to_like_in_tab_bar() -> None:
    intents = plan_intents(_parsed_single("Tap 'Swipe To Like' in the tab bar"))
    assert intents[0].primary_action is ActionType.TAP
    assert intents[0].target_container_hint == "tab_bar"


def test_infer_swipe_left_command() -> None:
    intents = plan_intents(_parsed_single("Swipe left"))
    assert intents[0].primary_action is ActionType.SWIPE


def test_infer_scroll_down() -> None:
    intents = plan_intents(_parsed_single("Scroll Down"))
    assert intents[0].primary_action is ActionType.SCROLL


def test_canonical_path_swipe_label_stays_tap_with_qualifier() -> None:
    body = "Tap 'Swipe to like' in the tab bar"
    norm = normalize_scenario_text(body, enable_ai_fallback=False)
    parsed = build_parsed_scenario_from_canonical(
        norm.canonical,
        app_id="com.example",
        platform=Platform.ANDROID,
    )
    intents = plan_intents(parsed)
    assert intents[0].primary_action is ActionType.TAP
    assert intents[0].target_container_hint == "tab_bar"
    assert parsed.steps[0].canonical_action == "tap"


def test_canonical_action_overrides_misleading_text() -> None:
    """When canonical_action is set, planner must not contradict it via heuristics."""
    intents = plan_intents(
        _parsed_single("swipe up", canonical_action="tap"),
    )
    assert intents[0].primary_action is ActionType.TAP


def test_action_type_from_canonical_slug_unknown_falls_back() -> None:
    assert action_type_from_canonical_slug("when_action") is None
    assert action_type_from_canonical_slug(None) is None
