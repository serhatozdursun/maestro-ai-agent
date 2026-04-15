"""Tests for ``exploration_report.json`` machine-first artifact builder."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from maestro_ai_agent.app.exploration_report import (
    EXPLORATION_REPORT_FILENAME,
    build_exploration_report_payload,
    write_exploration_report,
)
from maestro_ai_agent.app.scenario_run import (
    MAESTRO_DRAFT_PREVIEW_FILENAME,
    _write_blocking_popup_failure_artifacts,
    _write_scenario_run_artifacts,
)
from maestro_ai_agent.domain.enums import ActionType, Platform, SelectorType
from maestro_ai_agent.domain.flow import FlowStep
from maestro_ai_agent.domain.flow_draft import FlowDraftBuilder
from maestro_ai_agent.domain.hierarchy import HierarchySnapshot
from maestro_ai_agent.domain.intent import StepIntent
from maestro_ai_agent.domain.scenario import ScenarioInput
from maestro_ai_agent.orchestrator.enums import PlanningRunMode, RunStepPhase, StepValidationStatus
from maestro_ai_agent.orchestrator.models import (
    ObservationCycleResult,
    PlannedActionAttempt,
    PlanningOrchestrationResult,
    RunDecisionLogEntry,
    RunReport,
    ScenarioRunContext,
    ScenarioRunRequest,
    ScenarioRunState,
    StepRunState,
)
from maestro_ai_agent.orchestrator.waiters.hierarchy_waiter import HierarchyStableWaitOutcome
from maestro_ai_agent.scenario.scenario_normalizer import normalize_scenario_text
from maestro_ai_agent.services.maestro.blocking_popup_dismissal import KnownBlockingPopupOutcome


def _minimal_scenario_run_result() -> PlanningOrchestrationResult:
    hs = HierarchySnapshot(raw_csv='1,0,"text=OK; class=android.widget.Button",\n', nodes=[])
    obs = ObservationCycleResult(
        hierarchy=hs,
        retrieved_at=datetime.now(UTC),
        app_id="com.example",
        platform=Platform.ANDROID,
    )
    intent = StepIntent(
        intent_id=uuid4(),
        scenario_step_index=0,
        primary_action=ActionType.TAP,
        goal_summary="Tap OK",
        raw_step_text="Tap 'OK'",
    )
    pa = PlannedActionAttempt(
        intent_id=intent.intent_id,
        scenario_step_index=0,
        action=ActionType.TAP,
        chosen_candidate_id="c1",
        expression="text:OK",
        selector_type=SelectorType.TEXT,
        score=1.0,
        explanation_summary="ranked",
    )
    st = StepRunState(
        scenario_step_index=0,
        raw_step_text="Tap 'OK'",
        intent=intent,
        phase=RunStepPhase.VALIDATED,
        observation=obs,
        planned_attempt=pa,
        validation_status=StepValidationStatus.PASSED,
    )
    req = ScenarioRunRequest(
        scenario_input=ScenarioInput(
            scenario_text="Tap 'OK'",
            app_id="com.example",
            platform=Platform.ANDROID,
        ),
        device_id="dev-1",
        planning_mode=PlanningRunMode.OBSERVE_PLAN_EXECUTE,
    )
    ctx = ScenarioRunContext(planning_mode=PlanningRunMode.OBSERVE_PLAN_EXECUTE, device_id="dev-1")
    b = FlowDraftBuilder(run_label="t")
    b.append_executed_validated(
        FlowStep(
            sequence=0,
            action=ActionType.TAP,
            summary="tap",
            target_selector_hint="text:OK",
            metadata={"scenario_step_index": "0"},
        ),
    )
    state = ScenarioRunState(
        context=ctx,
        request=req,
        step_states=[st],
        flow_draft=b.draft(),
    )
    report = RunReport(
        run_id=ctx.run_id,
        planning_mode=PlanningRunMode.OBSERVE_PLAN_EXECUTE,
        summary="done",
        decision_log=[
            RunDecisionLogEntry(
                scenario_step_index=0,
                raw_step_text="Tap 'OK'",
                intent_goal_summary="Tap OK",
                intent_primary_action=ActionType.TAP,
                chosen_candidate_id="c1",
            ),
        ],
    )
    return PlanningOrchestrationResult(state=state, report=report)


def test_write_exploration_report_creates_json_file(tmp_path: Path) -> None:
    path = write_exploration_report(tmp_path, {"schema_version": "1", "x": 1})
    assert path.name == EXPLORATION_REPORT_FILENAME
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == "1"


def test_build_includes_decision_log_and_flow_draft() -> None:
    result = _minimal_scenario_run_result()
    payload = build_exploration_report_payload(
        run_type="scenario_run",
        app_id="com.example",
        platform=Platform.ANDROID,
        device_id="dev-1",
        raw_step=None,
        raw_scenario="Tap 'OK'",
        canonical_scenario_used=True,
        result=result,
        orchestrator_ran=True,
        launch_info={"ok": True, "hierarchy_stable_wait": {"reason": "stable"}},
        popup_outcome=None,
        preflight_launch_attempted=True,
        preflight_launch_ok=True,
        preflight_launch_message=None,
        maestro_draft_preview_relative_path=MAESTRO_DRAFT_PREVIEW_FILENAME,
        maestro_draft_preview_written=True,
    )
    assert payload["schema_version"] == "1"
    assert payload["run_type"] == "scenario_run"
    assert len(payload["decision_log"]) == 1
    assert payload["decision_log"][0]["chosen_candidate_id"] == "c1"
    assert payload["flow_draft"] is not None
    assert len(payload["flow_draft"]["steps"]) == 1
    assert payload["flow_draft"]["steps"][0]["target_selector_hint"] == "text:OK"
    assert payload["steps"][0]["selector_resolution"]["chosen"]["expression"] == "text:OK"


def test_popup_outcome_in_preflight() -> None:
    popup = KnownBlockingPopupOutcome(
        handled=True,
        pattern_id="developer_mode_continue",
        reason="dismissed",
        should_abort_run=False,
        popup_tool_name="tap_on",
        popup_tool_args={"text": "Continue"},
        tap_selector_basis="text",
        dismiss_tap_text="Continue",
        dismiss_tap_id=None,
        detected=True,
        dismiss_action_resolved={"selector_basis": "text", "expression": "text:Continue"},
        execution_attempted=True,
        execution_ok=True,
        verified_cleared=True,
    )
    payload = build_exploration_report_payload(
        run_type="scenario_run",
        app_id="com.example",
        platform=Platform.ANDROID,
        device_id="d1",
        raw_step=None,
        raw_scenario=None,
        canonical_scenario_used=False,
        result=None,
        orchestrator_ran=False,
        launch_info=None,
        popup_outcome=popup,
        preflight_launch_attempted=True,
        preflight_launch_ok=True,
        preflight_launch_message=None,
        maestro_draft_preview_relative_path=MAESTRO_DRAFT_PREVIEW_FILENAME,
        maestro_draft_preview_written=False,
        run_id="rid-1",
    )
    po = payload["preflight"]["popup_outcome"]
    assert po is not None
    assert po["handled"] is True
    assert po["pattern_id"] == "developer_mode_continue"
    assert po["popup_tool_args"]["text"] == "Continue"
    assert po["blocker_episode"]["handled"] is True
    assert po["blocker_episode"]["dismiss_text"] == "Continue"


def test_maestro_draft_preview_paths() -> None:
    payload = build_exploration_report_payload(
        run_type="scenario_run",
        app_id="com.example",
        platform=Platform.IOS,
        device_id="udid",
        raw_step=None,
        raw_scenario="A\nB",
        canonical_scenario_used=True,
        result=_minimal_scenario_run_result(),
        orchestrator_ran=True,
        launch_info={"ok": True},
        popup_outcome=None,
        preflight_launch_attempted=True,
        preflight_launch_ok=True,
        preflight_launch_message=None,
        maestro_draft_preview_relative_path=MAESTRO_DRAFT_PREVIEW_FILENAME,
        maestro_draft_preview_written=True,
        canonical_scenario_path="canonical_scenario.json",
    )
    assert payload["input"]["canonical_scenario_path"] == "canonical_scenario.json"
    assert payload["maestro_draft_preview"]["yaml_path"] == MAESTRO_DRAFT_PREVIEW_FILENAME
    assert payload["maestro_draft_preview"]["written"] is True


def test_write_scenario_run_artifacts_writes_exploration_report(tmp_path: Path) -> None:
    result = _minimal_scenario_run_result()
    norm = normalize_scenario_text("Tap 'OK'", enable_ai_fallback=False)
    _write_scenario_run_artifacts(
        result,
        output_dir=tmp_path,
        app_id="com.example",
        launch_info={
            "ok": True,
            "message": None,
            "hierarchy_stable_wait": {"screen_stable": True, "reason": "ok"},
            "blocking_popup": {
                "handled": False,
                "pattern_id": None,
                "reason": "no_known_blocking_pattern",
            },
        },
        raw_scenario="Tap 'OK'",
        normalization=norm,
        popup_outcome=None,
    )
    er_path = tmp_path / EXPLORATION_REPORT_FILENAME
    assert er_path.is_file()
    data = json.loads(er_path.read_text(encoding="utf-8"))
    assert data["schema_version"] == "1"
    assert data["run_type"] == "scenario_run"
    assert data["preflight"]["popup_outcome"]["handled"] is False
    assert data["maestro_draft_preview"]["yaml_path"] == MAESTRO_DRAFT_PREVIEW_FILENAME
    assert "decision_log" in data
    assert "flow_draft" in data


def test_blocking_popup_failure_writes_exploration_report(tmp_path: Path) -> None:
    popup = KnownBlockingPopupOutcome(
        handled=False,
        pattern_id="developer_mode_continue",
        reason="tap_primary_flow_fallback_failed",
        should_abort_run=True,
        popup_tool_name="tap_on",
        popup_tool_args={"text": "Continue"},
        tap_selector_basis="text",
    )
    wait = HierarchyStableWaitOutcome(
        screen_stable=True,
        iterations_run=1,
        final_node_count=5,
        reason="stable",
    )
    _write_blocking_popup_failure_artifacts(
        output_dir=tmp_path,
        app_id="com.example",
        platform=Platform.ANDROID,
        device_id="d1",
        popup_outcome=popup,
        initial_delay_before_stability_s=0.5,
        wait_outcome=wait,
    )
    data = json.loads((tmp_path / EXPLORATION_REPORT_FILENAME).read_text(encoding="utf-8"))
    assert data["orchestrator_ran"] is False
    assert data["preflight"]["popup_outcome"]["should_abort_run"] is True
    assert data["preflight"]["hierarchy_stable_wait"]["reason"] == "stable"
    assert data["maestro_draft_preview"]["written"] is False
