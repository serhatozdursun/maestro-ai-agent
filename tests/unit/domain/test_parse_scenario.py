"""Tests for deterministic scenario parsing."""

from maestro_ai_agent.domain.enums import Platform
from maestro_ai_agent.domain.parse_scenario import parse_scenario_input
from maestro_ai_agent.domain.scenario import ScenarioInput


def test_parse_strips_bullets_and_trims() -> None:
    text = """
# setup ignored
- Launch the app
* Tap Sign in
1. Enter email "a@b.co"
"""
    inp = ScenarioInput(
        scenario_text=text,
        app_id="com.example.app",
        platform=Platform.ANDROID,
    )
    parsed = parse_scenario_input(inp)
    assert [s.text for s in parsed.steps] == [
        "Launch the app",
        "Tap Sign in",
        'Enter email "a@b.co"',
    ]
    assert parsed.steps[0].source_line == 3
    assert parsed.parser_name == "deterministic_line_v1"


def test_parse_empty_body_warns() -> None:
    inp = ScenarioInput(
        scenario_text="   \n# only comment\n",
        app_id="com.example.app",
        platform=Platform.IOS,
    )
    parsed = parse_scenario_input(inp)
    assert parsed.steps == []
    assert any("No non-empty steps" in w for w in parsed.warnings)
