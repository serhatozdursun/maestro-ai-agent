"""Canonical scenario → domain ParsedScenario → plan_intents (no AI, no runtime)."""

from uuid import UUID

from maestro_ai_agent.domain.enums import ActionType, Platform
from maestro_ai_agent.domain.parse_scenario import parse_scenario_input
from maestro_ai_agent.domain.planning import plan_intents
from maestro_ai_agent.domain.scenario import ScenarioInput
from maestro_ai_agent.scenario.planning_adapter import build_parsed_scenario_from_canonical
from maestro_ai_agent.scenario.scenario_normalizer import normalize_scenario_text


def test_normalize_then_adapter_feeds_planner_with_tap_intents() -> None:
    text = "Tap 'OK'\nTap 'Cart'"
    norm = normalize_scenario_text(text, enable_ai_fallback=False)
    assert norm.used_ai_fallback is False

    parsed = build_parsed_scenario_from_canonical(
        norm.canonical,
        app_id="com.example",
        platform=Platform.ANDROID,
    )
    assert parsed.parser_name == "canonical_to_parsed_v1"
    intents = plan_intents(parsed)
    assert len(intents) == 2
    assert intents[0].scenario_step_index == 0
    assert intents[1].scenario_step_index == 1
    assert intents[0].primary_action is ActionType.TAP
    assert intents[1].primary_action is ActionType.TAP
    assert "OK" in intents[0].raw_step_text
    assert "Cart" in intents[1].raw_step_text


def test_step_order_matches_canonical_order() -> None:
    text = "1. Tap 'A'\n2. Tap 'B'\n3. Tap 'C'\n"
    norm = normalize_scenario_text(text, enable_ai_fallback=False)
    parsed = build_parsed_scenario_from_canonical(
        norm.canonical,
        app_id="com.example",
        platform=Platform.IOS,
    )
    intents = plan_intents(parsed)
    assert [i.raw_step_text for i in intents] == ["Tap 'A'", "Tap 'B'", "Tap 'C'"]


def test_legacy_parse_path_unchanged() -> None:
    """Direct ScenarioInput + parse_scenario_input + plan_intents still works."""
    inp = ScenarioInput(
        scenario_text="Tap 'X'",
        app_id="com.example",
        platform=Platform.ANDROID,
    )
    parsed = parse_scenario_input(inp)
    assert parsed.parser_name == "deterministic_line_v1"
    intents = plan_intents(parsed)
    assert len(intents) == 1
    assert intents[0].primary_action is ActionType.TAP


def test_planner_intent_ids_are_unique() -> None:
    norm = normalize_scenario_text("Tap '1'\nTap '2'", enable_ai_fallback=False)
    parsed = build_parsed_scenario_from_canonical(
        norm.canonical,
        app_id="com.example",
        platform=Platform.ANDROID,
    )
    intents = plan_intents(parsed)
    ids = {i.intent_id for i in intents}
    assert len(ids) == 2
    assert all(isinstance(i, UUID) for i in ids)
