"""Scenario run request defaults (CLI flags map to ``ScenarioRunRequest.tap_resolution``)."""

from maestro_ai_agent.domain.enums import Platform
from maestro_ai_agent.domain.scenario import ScenarioInput
from maestro_ai_agent.domain.selectors.tap_resolution import AmbiguityStrategy
from maestro_ai_agent.orchestrator.models import ScenarioRunRequest


def test_scenario_run_request_tap_resolution_defaults() -> None:
    req = ScenarioRunRequest(
        scenario_input=ScenarioInput(
            scenario_text="Tap 'OK'",
            app_id="com.example",
            platform=Platform.ANDROID,
        ),
        device_id="dev",
    )
    assert req.tap_resolution.ambiguity_strategy is AmbiguityStrategy.AUTO
    assert req.tap_resolution.max_target_suggestions == 8
    assert req.tap_resolution.show_target_regions is True
    assert req.tap_resolution.prefer_target_kind == "auto"
