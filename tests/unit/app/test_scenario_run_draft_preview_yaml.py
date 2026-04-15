"""Tests for scenario-run Maestro draft preview YAML (multi-step flow draft)."""

from __future__ import annotations

from maestro_ai_agent.app.maestro_draft_preview import build_blocking_popup_optional_tap_yaml_lines
from maestro_ai_agent.app.scenario_run import build_maestro_draft_preview_yaml
from maestro_ai_agent.domain.enums import ActionType, Platform
from maestro_ai_agent.domain.flow import FlowStep
from maestro_ai_agent.domain.flow_draft import FlowDraftBuilder
from maestro_ai_agent.domain.scenario import ScenarioInput
from maestro_ai_agent.orchestrator.enums import PlanningRunMode
from maestro_ai_agent.orchestrator.models import (
    PlanningOrchestrationResult,
    RunReport,
    ScenarioRunContext,
    ScenarioRunRequest,
    ScenarioRunState,
)


def test_build_maestro_draft_preview_yaml_prepends_single_optional_popup_tap() -> None:
    b = FlowDraftBuilder(run_label="t")
    b.append_executed_validated(
        FlowStep(
            sequence=0,
            action=ActionType.TAP,
            summary="tap ok",
            target_selector_hint="text:OK",
            metadata={},
        ),
    )
    req = ScenarioRunRequest(
        scenario_input=ScenarioInput(
            scenario_text="Tap 'OK'",
            app_id="com.example.app",
            platform=Platform.ANDROID,
        ),
        planning_mode=PlanningRunMode.OBSERVE_PLAN_EXECUTE,
    )
    state = ScenarioRunState(
        context=ScenarioRunContext(planning_mode=PlanningRunMode.OBSERVE_PLAN_EXECUTE),
        request=req,
        step_states=[],
        flow_draft=b.draft(),
    )
    report = RunReport(
        run_id=state.context.run_id,
        planning_mode=PlanningRunMode.OBSERVE_PLAN_EXECUTE,
        summary="fixture",
        decision_log=[],
    )
    bundle = PlanningOrchestrationResult(state=state, report=report)
    popup_lines = build_blocking_popup_optional_tap_yaml_lines(
        handled=True,
        tap_selector_basis="text",
        dismiss_tap_text="Continue",
        dismiss_tap_id=None,
    )
    yaml_text = build_maestro_draft_preview_yaml(
        app_id="com.example.app",
        result=bundle,
        popup_dismiss_yaml_lines=popup_lines,
    )
    sep = yaml_text.index("---")
    assert yaml_text.index("optional: true") > sep
    assert yaml_text.index("optional: true") < yaml_text.index("OK")


def test_build_maestro_draft_preview_includes_dismiss_blocker_optional_tap() -> None:
    b = FlowDraftBuilder(run_label="t")
    b.append_executed_validated(
        FlowStep(
            sequence=0,
            action=ActionType.DISMISS_BLOCKER,
            summary="dismiss",
            target_selector_hint="text:Allow",
            metadata={},
        ),
    )
    req = ScenarioRunRequest(
        scenario_input=ScenarioInput(
            scenario_text="Dismiss popup",
            app_id="com.example.app",
            platform=Platform.ANDROID,
        ),
        planning_mode=PlanningRunMode.OBSERVE_PLAN_EXECUTE,
    )
    state = ScenarioRunState(
        context=ScenarioRunContext(planning_mode=PlanningRunMode.OBSERVE_PLAN_EXECUTE),
        request=req,
        step_states=[],
        flow_draft=b.draft(),
    )
    report = RunReport(
        run_id=state.context.run_id,
        planning_mode=PlanningRunMode.OBSERVE_PLAN_EXECUTE,
        summary="fixture",
        decision_log=[],
    )
    bundle = PlanningOrchestrationResult(state=state, report=report)
    yaml_text = build_maestro_draft_preview_yaml(app_id="com.example.app", result=bundle)
    assert "Allow" in yaml_text
    assert "optional: true" in yaml_text
