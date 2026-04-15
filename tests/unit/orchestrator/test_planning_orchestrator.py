"""Planning-only orchestrator skeleton: observation, ranking, state, reports."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from maestro_ai_agent.domain.enums import ActionType, Platform
from maestro_ai_agent.domain.scenario import ParsedScenario, ScenarioInput, ScenarioStep
from maestro_ai_agent.domain.selectors.pipeline import plan_selector_ranking
from maestro_ai_agent.orchestrator.enums import (
    DecisionExecutionFootprint,
    PlanningRunMode,
    RunStepPhase,
)
from maestro_ai_agent.orchestrator.models import ScenarioRunRequest
from maestro_ai_agent.orchestrator.planning_service import ScenarioPlanningOrchestrator
from maestro_ai_agent.orchestrator.step_processing import run_observe_plan_cycle_for_intent
from maestro_ai_agent.services.maestro.models import ScreenshotArtifact
from maestro_ai_agent.services.maestro.screen_service import MaestroScreenService


def _csv_ok_button() -> str:
    return '1,0,"text=OK; class=android.widget.Button; bounds=[0,0][100,40]",\n'


class _StubScreenProvider:
    """Minimal provider: returns configurable hierarchy CSV per inspect call."""

    def __init__(self, *, csv: str, shot: ScreenshotArtifact | None = None) -> None:
        self._csv = csv
        self._shot = shot
        self.inspect_calls: list[str | None] = []

    def capabilities(self):
        raise NotImplementedError

    def list_devices(self):
        raise NotImplementedError

    def launch_app(
        self,
        *,
        app_id: str,
        device_id: str | None = None,
        permissions=None,
    ):
        raise NotImplementedError

    def stop_app(self, *, app_id: str, device_id: str | None = None):
        raise NotImplementedError

    def inspect_view_hierarchy(self, *, device_id: str | None = None) -> str:
        self.inspect_calls.append(device_id)
        return self._csv

    def take_screenshot(self, *, device_id: str | None = None) -> ScreenshotArtifact:
        assert self._shot is not None
        return self._shot

    def tap_on(
        self,
        *,
        tap_id: str | None = None,
        tap_text: str | None = None,
        device_id: str | None = None,
    ):
        raise NotImplementedError

    def input_text(self, *, text: str, device_id: str | None = None):
        raise NotImplementedError

    def run_flow(self, *, flow_yaml: str, device_id: str | None = None):
        raise NotImplementedError

    def check_flow_syntax(self, *, flow_yaml: str):
        raise NotImplementedError


def _scenario_input_two_steps() -> ScenarioInput:
    return ScenarioInput(
        scenario_text="Tap 'OK'\nAssert 'Done' visible",
        app_id="com.example.app",
        platform=Platform.ANDROID,
    )


def test_planning_only_orchestrator_end_to_end() -> None:
    provider = _StubScreenProvider(csv=_csv_ok_button())
    orch = ScenarioPlanningOrchestrator(MaestroScreenService(provider))
    result = orch.run_planning_only(
        ScenarioRunRequest(scenario_input=_scenario_input_two_steps()),
    )
    assert result.state.context.planning_mode is PlanningRunMode.PLANNING_ONLY
    assert len(result.state.step_states) == 2
    assert result.state.step_states[0].phase is RunStepPhase.PLANNED
    assert result.state.step_states[0].planned_attempt is not None
    assert result.state.step_states[0].planned_attempt.lifecycle == "planned"
    assert len(provider.inspect_calls) == 2
    assert len(result.state.flow_draft.steps) >= 1
    assert result.state.flow_draft.steps[0].metadata["lifecycle"] == "planned"
    assert result.report.steps_planned >= 1
    assert all(
        e.execution_footprint is DecisionExecutionFootprint.PLANNING_ONLY
        for e in result.report.decision_log
    )


def test_observation_service_invoked_with_device_id() -> None:
    provider = _StubScreenProvider(csv=_csv_ok_button())
    orch = ScenarioPlanningOrchestrator(MaestroScreenService(provider))
    orch.run_planning_only(
        ScenarioRunRequest(
            scenario_input=_scenario_input_two_steps(),
            device_id="device-42",
            max_steps=1,
        ),
    )
    assert provider.inspect_calls == ["device-42"]


def test_plan_selector_ranking_receives_observed_hierarchy() -> None:
    provider = _StubScreenProvider(csv=_csv_ok_button())
    orch = ScenarioPlanningOrchestrator(MaestroScreenService(provider))
    captured: list = []

    def _spy(hierarchy, intent, hints=None, **kwargs):
        captured.append(hierarchy)
        return plan_selector_ranking(hierarchy, intent, hints, **kwargs)

    with patch(
        "maestro_ai_agent.orchestrator.step_processing.plan_selector_ranking",
        side_effect=_spy,
    ):
        orch.run_planning_only(
            ScenarioRunRequest(
                scenario_input=ScenarioInput(
                    scenario_text="Tap 'OK'",
                    app_id="com.example.app",
                    platform=Platform.ANDROID,
                ),
            ),
        )
    assert len(captured) == 1
    assert len(captured[0].nodes) == 1
    assert captured[0].nodes[0].text == "OK"


def test_step_run_state_transitions_to_planned() -> None:
    provider = _StubScreenProvider(csv=_csv_ok_button())
    service = MaestroScreenService(provider)
    from maestro_ai_agent.domain.parse_scenario import parse_scenario_input
    from maestro_ai_agent.domain.planning import plan_intents

    parsed = parse_scenario_input(
        ScenarioInput(
            scenario_text="Tap 'OK'",
            app_id="com.example.app",
            platform=Platform.ANDROID,
        ),
    )
    intent = plan_intents(parsed)[0]
    step = run_observe_plan_cycle_for_intent(
        observer=service.observe_current_screen,
        app_id=parsed.input.app_id,
        platform=parsed.input.platform,
        device_id=None,
        include_screenshot=False,
        intent=intent,
    )
    assert step.phase is RunStepPhase.PLANNED
    assert step.observation is not None
    assert step.ranking is not None


def test_run_report_documents_non_execution() -> None:
    provider = _StubScreenProvider(csv=_csv_ok_button())
    orch = ScenarioPlanningOrchestrator(MaestroScreenService(provider))
    result = orch.run_planning_only(
        ScenarioRunRequest(scenario_input=_scenario_input_two_steps()),
    )
    joined = " ".join(result.report.limitations).lower()
    assert "not executed" in joined
    assert "yaml" in joined or "emitted" in joined
    assert "validation" in joined


def test_no_viable_selector_skips_flow_append() -> None:
    provider = _StubScreenProvider(csv="")
    orch = ScenarioPlanningOrchestrator(MaestroScreenService(provider))
    result = orch.run_planning_only(
        ScenarioRunRequest(
            scenario_input=ScenarioInput(
                scenario_text="Tap 'OK'",
                app_id="com.example.app",
                platform=Platform.ANDROID,
            ),
        ),
    )
    assert result.state.step_states[0].phase is RunStepPhase.SKIPPED_NO_SELECTOR
    assert result.state.step_states[0].planned_attempt is None
    assert len(result.state.flow_draft.steps) == 0
    assert result.report.steps_without_viable_selector == 1
    entry = result.report.decision_log[0]
    assert entry.chosen_candidate_id is None
    assert entry.step_phase is RunStepPhase.SKIPPED_NO_SELECTOR


def test_stop_after_first_planned_truncates() -> None:
    provider = _StubScreenProvider(csv=_csv_ok_button())
    orch = ScenarioPlanningOrchestrator(MaestroScreenService(provider))
    result = orch.run_planning_only(
        ScenarioRunRequest(
            scenario_input=_scenario_input_two_steps(),
            stop_after_first_planned=True,
        ),
    )
    assert len(result.state.step_states) == 1
    assert "stopped after the first planned" in " ".join(result.report.limitations).lower()


def test_parsed_scenario_request_path() -> None:
    inp = ScenarioInput(
        scenario_text="Tap 'OK'",
        app_id="com.example.app",
        platform=Platform.ANDROID,
    )
    parsed = ParsedScenario(
        input=inp,
        steps=[
            ScenarioStep(index=0, text="Tap 'OK'", source_line=1),
        ],
    )
    provider = _StubScreenProvider(csv=_csv_ok_button())
    orch = ScenarioPlanningOrchestrator(MaestroScreenService(provider))
    result = orch.run_planning_only(ScenarioRunRequest(parsed_scenario=parsed))
    assert len(result.state.step_states) == 1


def test_scenario_run_request_rejects_both_sources() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        ScenarioRunRequest(
            scenario_input=_scenario_input_two_steps(),
            parsed_scenario=ParsedScenario(input=_scenario_input_two_steps(), steps=[]),
        )


def _gherkin_cart_scenario_input() -> ScenarioInput:
    return ScenarioInput(
        scenario_text=(
            "Scenario: Add to cart\n"
            'When the user searches for "shoe"\n'
            'Then the user sees "Cart"\n'
        ),
        app_id="com.example.app",
        platform=Platform.ANDROID,
    )


def test_canonical_path_uses_normalizer_then_planner() -> None:
    """Opt-in flag: Gherkin-style text becomes semantic steps (tap + assert), not raw lines."""
    provider = _StubScreenProvider(csv=_csv_ok_button())
    orch = ScenarioPlanningOrchestrator(MaestroScreenService(provider))
    result = orch.run_planning_only(
        ScenarioRunRequest(
            scenario_input=_gherkin_cart_scenario_input(),
            use_canonical_scenario_normalization=True,
        ),
    )
    assert len(result.state.step_states) == 2
    assert result.state.step_states[0].intent.primary_action is ActionType.TAP
    assert result.state.step_states[1].intent.primary_action is ActionType.ASSERT_VISIBLE
    assert "shoe" in result.state.step_states[0].intent.raw_step_text


def test_legacy_path_default_for_gherkin_like_text() -> None:
    """Without the flag, line-based parse yields one intent per raw line (often UNKNOWN)."""
    provider = _StubScreenProvider(csv=_csv_ok_button())
    orch = ScenarioPlanningOrchestrator(MaestroScreenService(provider))
    result = orch.run_planning_only(
        ScenarioRunRequest(scenario_input=_gherkin_cart_scenario_input()),
    )
    assert len(result.state.step_states) == 3
    assert all(s.intent.primary_action is ActionType.UNKNOWN for s in result.state.step_states)


def test_explicit_false_matches_legacy_for_two_step_scenario() -> None:
    provider = _StubScreenProvider(csv=_csv_ok_button())
    orch = ScenarioPlanningOrchestrator(MaestroScreenService(provider))
    a = orch.run_planning_only(
        ScenarioRunRequest(scenario_input=_scenario_input_two_steps()),
    )
    b = orch.run_planning_only(
        ScenarioRunRequest(
            scenario_input=_scenario_input_two_steps(),
            use_canonical_scenario_normalization=False,
        ),
    )
    assert len(a.state.step_states) == len(b.state.step_states) == 2


def test_canonical_flag_with_parsed_scenario_rejected() -> None:
    inp = ScenarioInput(
        scenario_text="Tap 'OK'",
        app_id="com.example.app",
        platform=Platform.ANDROID,
    )
    parsed = ParsedScenario(
        input=inp,
        steps=[ScenarioStep(index=0, text="Tap 'OK'", source_line=1)],
    )
    with pytest.raises(ValueError, match="use_canonical_scenario_normalization requires"):
        ScenarioRunRequest(
            parsed_scenario=parsed,
            use_canonical_scenario_normalization=True,
        )
