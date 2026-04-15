"""Conservative observe→plan→execute (tap / input_text) with mocked provider."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from maestro_ai_agent.app.exploration_report import EXPLORATION_REPORT_FILENAME
from maestro_ai_agent.app.scenario_run import (
    MAESTRO_DRAFT_PREVIEW_FILENAME,
    _write_scenario_run_artifacts,
    build_maestro_draft_preview_yaml,
)
from maestro_ai_agent.domain.enums import ActionType, Platform, SelectorType
from maestro_ai_agent.domain.flow import FlowStep
from maestro_ai_agent.domain.flow_draft import FlowDraftBuilder
from maestro_ai_agent.domain.hierarchy import HierarchySnapshot
from maestro_ai_agent.domain.intent import StepIntent
from maestro_ai_agent.domain.scenario import ScenarioInput
from maestro_ai_agent.orchestrator.action_attempt_planning import DIRECT_INPUT_TEXT_CANDIDATE_ID
from maestro_ai_agent.orchestrator.enums import (
    DecisionExecutionFootprint,
    PlanningRunMode,
    PostActionValidationOutcome,
    RunStepPhase,
    StepValidationStatus,
)
from maestro_ai_agent.orchestrator.execution.execution_service import ProviderStepExecutionService
from maestro_ai_agent.orchestrator.models import (
    ObservationCycleResult,
    PlannedActionAttempt,
    PlanningOrchestrationResult,
    RunReport,
    ScenarioRunContext,
    ScenarioRunRequest,
    ScenarioRunState,
    StepRunState,
)
from maestro_ai_agent.orchestrator.planning_service import ScenarioPlanningOrchestrator
from maestro_ai_agent.scenario.scenario_normalizer import normalize_scenario_text
from maestro_ai_agent.services.maestro.models import (
    ActionResult,
    ProviderCapabilities,
    ScreenshotArtifact,
)
from maestro_ai_agent.services.maestro.screen_service import MaestroScreenService


def _csv_ok_button() -> str:
    return '1,0,"text=OK; class=android.widget.Button; bounds=[0,0][100,40]",\n'


def _csv_after_tap_changed() -> str:
    """Second hierarchy: different fingerprint so HIERARCHY_CHANGED goals can pass."""
    return (
        '1,0,"text=Next; class=android.widget.Button; bounds=[0,0][100,40]",\n'
        '2,0,"text=Done; class=android.widget.TextView; bounds=[0,50][100,80]",\n'
    )


def _csv_next_only() -> str:
    return '1,0,"text=Next; class=android.widget.Button; bounds=[0,0][100,40]",\n'


def _csv_done_only() -> str:
    return '1,0,"text=Done; class=android.widget.TextView; bounds=[0,80][100,120]",\n'


class _ExecStubProvider:
    def __init__(
        self,
        *,
        csv: str | list[str],
        tap_ok: bool = True,
        input_ok: bool = True,
        tap_message: str | None = None,
        input_message: str | None = None,
        run_flow_ok: bool = True,
        run_flow_message: str | None = None,
    ) -> None:
        self._csv_frames: list[str] = [csv] if isinstance(csv, str) else list(csv)
        self.empty_post_hierarchy: bool = False
        self.tap_ok = tap_ok
        self.input_ok = input_ok
        self.tap_message = tap_message
        self.input_message = input_message
        self.run_flow_ok = run_flow_ok
        self.run_flow_message = run_flow_message
        self.inspect_calls: list[str | None] = []
        self.tap_calls: list[tuple[str | None, str | None, str | None]] = []
        self.run_flow_calls: list[str] = []
        self.input_calls: list[tuple[str, str | None]] = []

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities()

    def list_devices(self):
        raise NotImplementedError

    def launch_app(self, *, app_id: str, device_id: str | None = None, permissions=None):
        raise NotImplementedError

    def stop_app(self, *, app_id: str, device_id: str | None = None):
        raise NotImplementedError

    def inspect_view_hierarchy(self, *, device_id: str | None = None) -> str:
        self.inspect_calls.append(device_id)
        if self.empty_post_hierarchy and self.tap_calls:
            return ""
        if len(self._csv_frames) >= 2 and (self.tap_calls or self.run_flow_calls):
            return self._csv_frames[1]
        return self._csv_frames[0]

    def take_screenshot(self, *, device_id: str | None = None) -> ScreenshotArtifact:
        return ScreenshotArtifact(byte_length=0)

    def tap_on(
        self,
        *,
        tap_id: str | None = None,
        tap_text: str | None = None,
        device_id: str | None = None,
    ) -> ActionResult:
        self.tap_calls.append((tap_id, tap_text, device_id))
        return ActionResult(ok=self.tap_ok, message=self.tap_message)

    def run_flow(self, *, flow_yaml: str, device_id: str | None = None) -> ActionResult:
        self.run_flow_calls.append(flow_yaml)
        return ActionResult(ok=self.run_flow_ok, message=self.run_flow_message)

    def input_text(self, *, text: str, device_id: str | None = None) -> ActionResult:
        self.input_calls.append((text, device_id))
        return ActionResult(ok=self.input_ok, message=self.input_message)

    def check_flow_syntax(self, *, flow_yaml: str):
        raise NotImplementedError


class _MultiFrameTapProvider(_ExecStubProvider):
    """Hierarchy frame index follows completed tap count (supports two validated taps)."""

    def inspect_view_hierarchy(self, *, device_id: str | None = None) -> str:
        self.inspect_calls.append(device_id)
        if self.empty_post_hierarchy and self.tap_calls:
            return ""
        n = len(self.tap_calls)
        idx = min(n, len(self._csv_frames) - 1)
        return self._csv_frames[idx]


def _csv_edit_field_plain() -> str:
    return '1,0,"class=android.widget.EditText; bounds=[0,0][200,40]",\n'


def _csv_edit_field_with_hello() -> str:
    return '1,0,"text=hello; class=android.widget.EditText; bounds=[0,0][200,40]",\n'


def _csv_input_sibling_hello_row_edit_plain() -> str:
    """Sibling label contains ``hello`` so INPUT ranking can anchor the EditText."""
    return (
        '10,0,"text=hello row; class=android.widget.TextView; bounds=[0,0][120,24]",\n'
        '11,0,"class=android.widget.EditText; resource-id=com.ex:id et; bounds=[0,24][200,64]",\n'
    )


def _csv_input_sibling_hello_row_edit_typed() -> str:
    return (
        '10,0,"text=hello row; class=android.widget.TextView; bounds=[0,0][120,24]",\n'
        '11,0,"text=hello; class=android.widget.EditText; resource-id=com.ex:id et; '
        'bounds=[0,24][200,64]",\n'
    )


def _csv_input_sibling_shoe_shelf_edit_plain() -> str:
    return (
        '10,0,"text=shoe shelf; class=android.widget.TextView; bounds=[0,0][120,24]",\n'
        '11,0,"class=android.widget.EditText; resource-id=com.ex:id et; bounds=[0,24][200,64]",\n'
    )


def _csv_no_hello_landmark() -> str:
    return '1,0,"text=Search; class=android.widget.TextView; bounds=[0,0][100,20]",\n'


def _csv_edittext_shoe_typed() -> str:
    return '1,0,"text=shoe; class=android.widget.EditText; bounds=[0,0][200,40]",\n'


class _InputDirectReflectStub(_ExecStubProvider):
    """After ``input_text``, hierarchy shows the typed literal (no ``run_flow`` needed)."""

    def inspect_view_hierarchy(self, *, device_id: str | None = None) -> str:
        self.inspect_calls.append(device_id)
        if len(self._csv_frames) >= 2 and self.input_calls:
            return self._csv_frames[1]
        return self._csv_frames[0]


class _InputPrimaryThenFlowStub(_ExecStubProvider):
    """First post-input snapshot omits literal; after ``run_flow`` snapshot includes it."""

    def inspect_view_hierarchy(self, *, device_id: str | None = None) -> str:
        self.inspect_calls.append(device_id)
        if len(self._csv_frames) >= 2 and self.run_flow_calls:
            return self._csv_frames[1]
        if len(self._csv_frames) >= 2 and self.input_calls:
            return self._csv_frames[0]
        return self._csv_frames[0]


class _InputNeverReflectStub(_ExecStubProvider):
    """Provider reports success but hierarchy never contains the typed literal."""

    def inspect_view_hierarchy(self, *, device_id: str | None = None) -> str:
        self.inspect_calls.append(device_id)
        return self._csv_frames[0]


def _execute_request(text: str) -> ScenarioRunRequest:
    return ScenarioRunRequest(
        scenario_input=ScenarioInput(
            scenario_text=text,
            app_id="com.example.app",
            platform=Platform.ANDROID,
        ),
        planning_mode=PlanningRunMode.OBSERVE_PLAN_EXECUTE,
    )


def test_successful_tap_execution_mocked_provider() -> None:
    p = _ExecStubProvider(csv=[_csv_ok_button(), _csv_after_tap_changed()])
    orch = ScenarioPlanningOrchestrator(MaestroScreenService(p))
    result = orch.run_observe_plan_execute(_execute_request("Tap 'OK'"))
    step = result.state.step_states[0]
    assert step.phase is RunStepPhase.VALIDATED
    assert step.validation_status is StepValidationStatus.PASSED
    assert step.post_action_validation is not None
    assert step.execution_outcome is not None
    assert step.execution_outcome.provider_action == "tap_on"
    assert step.execution_outcome.action_result is not None
    assert step.execution_outcome.action_result.ok is True
    assert len(p.tap_calls) == 1
    assert p.tap_calls[0] == (None, "OK", None)
    assert p.run_flow_calls == []
    assert len(result.state.flow_draft.steps) == 1
    meta = result.state.flow_draft.steps[0].metadata
    assert meta["lifecycle"] == "executed_validated"
    assert meta["executed"] == "true"
    assert meta["validated"] == "true"
    assert meta["validation_outcome"] == "validated"
    entry = result.report.decision_log[0]
    assert entry.execution_footprint is (
        DecisionExecutionFootprint.PROVIDER_SUCCESS_VALIDATION_PASSED
    )
    assert entry.provider_ok is True
    assert entry.post_action_validation_outcome is PostActionValidationOutcome.VALIDATED


def test_successful_input_text_execution_mocked_provider() -> None:
    """Direct execution service: ranking may not emit INPUT primaries; PLANNED path is enough."""
    p = _InputDirectReflectStub(csv=[_csv_ok_button(), _csv_edit_field_with_hello()])
    svc = MaestroScreenService(p)
    intent = StepIntent(
        intent_id=uuid4(),
        scenario_step_index=0,
        primary_action=ActionType.INPUT_TEXT,
        goal_summary="input",
        raw_step_text="Type 'hello' in the field",
        validation_goals=[],
    )
    planned = PlannedActionAttempt(
        intent_id=intent.intent_id,
        scenario_step_index=0,
        action=ActionType.INPUT_TEXT,
        chosen_candidate_id="c1",
        expression="id:ignored_for_input_mapping",
        selector_type=SelectorType.ID,
        score=1.0,
        explanation_summary="fixture",
    )
    obs = ObservationCycleResult(
        hierarchy=HierarchySnapshot(nodes=[], raw_csv=""),
        parse_warnings=[],
        retrieved_at=datetime.now(UTC),
        app_id="com.example.app",
        platform=Platform.ANDROID,
    )
    step = StepRunState(
        scenario_step_index=0,
        raw_step_text=intent.raw_step_text,
        intent=intent,
        phase=RunStepPhase.PLANNED,
        observation=obs,
        planned_attempt=planned,
    )
    out = ProviderStepExecutionService(svc).execute_top_planned_if_supported(step, device_id=None)
    assert out.phase is RunStepPhase.EXECUTED
    assert p.input_calls == [("hello", None)]
    assert p.run_flow_calls == []
    assert out.execution_outcome is not None
    assert out.execution_outcome.text_input_used == "hello"
    assert out.execution_outcome.provider_action == "input_text"


def test_unsupported_step_no_provider_invocation() -> None:
    csv = '1,0,"text=Done; class=android.widget.TextView; bounds=[0,0][10,10]",\n'
    p = _ExecStubProvider(csv=csv)
    orch = ScenarioPlanningOrchestrator(MaestroScreenService(p))
    result = orch.run_observe_plan_execute(
        _execute_request("Describe an obscure widget interaction with no verb"),
    )
    step = result.state.step_states[0]
    assert step.phase is RunStepPhase.UNSUPPORTED
    assert len(p.tap_calls) == 0
    assert len(p.input_calls) == 0
    assert result.state.flow_draft.steps == []
    entry = result.report.decision_log[0]
    assert entry.execution_footprint is DecisionExecutionFootprint.EXECUTION_UNSUPPORTED


def test_missing_input_value_no_invented_text() -> None:
    csv = '1,0,"class=android.widget.EditText; bounds=[0,0][200,40]",\n'
    p = _ExecStubProvider(csv=csv)
    orch = ScenarioPlanningOrchestrator(MaestroScreenService(p))
    result = orch.run_observe_plan_execute(
        _execute_request("Type hello without quotes"),
    )
    step = result.state.step_states[0]
    assert step.phase is RunStepPhase.MISSING_INPUT_VALUE
    assert len(p.input_calls) == 0
    entry = result.report.decision_log[0]
    assert entry.execution_footprint is DecisionExecutionFootprint.MISSING_INPUT_TEXT


def test_provider_reported_failure_sets_execution_failed() -> None:
    p = _ExecStubProvider(
        csv=_csv_ok_button(),
        tap_ok=False,
        tap_message="element not found",
        run_flow_ok=False,
        run_flow_message="run_flow failed",
    )
    orch = ScenarioPlanningOrchestrator(MaestroScreenService(p))
    result = orch.run_observe_plan_execute(_execute_request("Tap 'OK'"))
    step = result.state.step_states[0]
    assert step.phase is RunStepPhase.EXECUTION_FAILED
    assert step.execution_outcome is not None
    assert step.execution_outcome.action_result is not None
    assert step.execution_outcome.action_result.ok is False
    assert len(result.state.flow_draft.steps) == 0
    assert len(p.run_flow_calls) == 1
    assert "appId:" in p.run_flow_calls[0]
    entry = result.report.decision_log[0]
    assert entry.execution_footprint is DecisionExecutionFootprint.PROVIDER_INVOKED_FAILED
    assert entry.provider_ok is False


def test_state_transitions_planned_to_validated_when_hierarchy_changes() -> None:
    p = _ExecStubProvider(csv=[_csv_ok_button(), _csv_after_tap_changed()])
    orch = ScenarioPlanningOrchestrator(MaestroScreenService(p))
    result = orch.run_observe_plan_execute(_execute_request("Tap 'OK'"))
    assert result.state.step_states[0].phase is RunStepPhase.VALIDATED


def test_tap_when_hierarchy_unchanged_skips_run_flow_then_may_fail_on_next_candidate() -> None:
    """No UI change after ok ``tap_on`` does not escalate the same selector via ``run_flow``.

    The runner then tries the next ranked candidate; this stub rejects ``point:`` taps, so
    the step ends in execution failure rather than validation.
    """
    c = _csv_ok_button()
    p = _ExecStubProvider(csv=[c, c])
    orch = ScenarioPlanningOrchestrator(MaestroScreenService(p))
    result = orch.run_observe_plan_execute(_execute_request("Tap 'OK'"))
    step = result.state.step_states[0]
    assert step.phase is RunStepPhase.EXECUTION_FAILED
    assert len(p.run_flow_calls) == 0


def test_validation_skipped_when_post_action_hierarchy_empty() -> None:
    p = _ExecStubProvider(csv=_csv_ok_button())
    p.empty_post_hierarchy = True
    orch = ScenarioPlanningOrchestrator(MaestroScreenService(p))
    result = orch.run_observe_plan_execute(_execute_request("Tap 'OK'"))
    step = result.state.step_states[0]
    assert step.phase is RunStepPhase.VALIDATION_SKIPPED
    assert step.post_action_validation is not None
    assert step.post_action_validation.outcome.value == "validation_skipped"
    meta = result.state.flow_draft.steps[0].metadata
    assert meta["validation_outcome"] == "validation_skipped"
    skipped = PostActionValidationOutcome.SKIPPED
    assert result.report.decision_log[0].post_action_validation_outcome is skipped
    assert result.report.steps_validation_skipped == 1


def test_decision_log_after_execute_mode() -> None:
    p = _ExecStubProvider(csv=[_csv_ok_button(), _csv_after_tap_changed()])
    orch = ScenarioPlanningOrchestrator(MaestroScreenService(p))
    result = orch.run_observe_plan_execute(_execute_request("Tap 'OK'"))
    lim = " ".join(result.report.decision_log[0].limitations).lower()
    assert "validation" in lim
    assert result.report.steps_validation_passed == 1


def test_run_observe_plan_execute_rejects_wrong_request_mode() -> None:
    p = _ExecStubProvider(csv=_csv_ok_button())
    orch = ScenarioPlanningOrchestrator(MaestroScreenService(p))
    bad = ScenarioRunRequest(
        scenario_input=ScenarioInput(
            scenario_text="Tap 'OK'",
            app_id="com.example.app",
            platform=Platform.ANDROID,
        ),
        planning_mode=PlanningRunMode.PLANNING_ONLY,
    )
    with pytest.raises(ValueError, match="observe_plan_execute"):
        orch.run_observe_plan_execute(bad)


def test_run_planning_only_rejects_execute_mode_request() -> None:
    p = _ExecStubProvider(csv=_csv_ok_button())
    orch = ScenarioPlanningOrchestrator(MaestroScreenService(p))
    bad = ScenarioRunRequest(
        scenario_input=ScenarioInput(
            scenario_text="Tap 'OK'",
            app_id="com.example.app",
            platform=Platform.ANDROID,
        ),
        planning_mode=PlanningRunMode.OBSERVE_PLAN_EXECUTE,
    )
    with pytest.raises(ValueError, match="planning_only"):
        orch.run_planning_only(bad)


def test_two_step_execute_validates_in_scenario_order() -> None:
    frames = (_csv_ok_button(), _csv_next_only(), _csv_done_only())
    p = _MultiFrameTapProvider(csv=list(frames))
    orch = ScenarioPlanningOrchestrator(MaestroScreenService(p))
    result = orch.run_observe_plan_execute(_execute_request("Tap 'OK'\nTap 'Next'"))
    assert len(result.state.step_states) == 2
    assert [s.scenario_step_index for s in result.state.step_states] == [0, 1]
    assert [s.raw_step_text for s in result.state.step_states] == ["Tap 'OK'", "Tap 'Next'"]
    assert all(s.phase is RunStepPhase.VALIDATED for s in result.state.step_states)
    assert p.tap_calls == [(None, "OK", None), (None, "Next", None)]


def test_stop_on_first_hard_failure_skips_remaining_intents() -> None:
    p = _ExecStubProvider(csv=_csv_ok_button(), tap_ok=False, run_flow_ok=False)
    orch = ScenarioPlanningOrchestrator(MaestroScreenService(p))
    req = _execute_request("Tap 'OK'\nTap 'Next'").model_copy(
        update={"stop_on_first_hard_failure": True},
    )
    result = orch.run_observe_plan_execute(req)
    assert len(result.state.step_states) == 1
    assert result.state.step_states[0].phase is RunStepPhase.EXECUTION_FAILED


def test_without_stop_on_hard_failure_still_processes_next_intent() -> None:
    p = _ExecStubProvider(csv=_csv_ok_button(), tap_ok=False, run_flow_ok=False)
    orch = ScenarioPlanningOrchestrator(MaestroScreenService(p))
    req = _execute_request("Tap 'OK'\nTap 'Next'")
    assert req.stop_on_first_hard_failure is False
    result = orch.run_observe_plan_execute(req)
    assert len(result.state.step_states) == 2
    assert result.state.step_states[0].phase is RunStepPhase.EXECUTION_FAILED


def test_scenario_run_artifacts_exploration_report_and_yaml(tmp_path: Path) -> None:
    frames = (_csv_ok_button(), _csv_next_only(), _csv_done_only())
    p = _MultiFrameTapProvider(csv=list(frames))
    orch = ScenarioPlanningOrchestrator(MaestroScreenService(p))
    raw = "Tap 'OK'\nTap 'Next'"
    result = orch.run_observe_plan_execute(_execute_request(raw))
    norm = normalize_scenario_text(raw, enable_ai_fallback=False)
    _write_scenario_run_artifacts(
        result,
        output_dir=tmp_path,
        app_id="com.example.app",
        launch_info={"ok": True},
        raw_scenario=raw,
        normalization=norm,
    )
    er = json.loads((tmp_path / EXPLORATION_REPORT_FILENAME).read_text(encoding="utf-8"))
    assert er["run_type"] == "scenario_run"
    assert len(er["steps"]) == 2
    assert [row["scenario_step_index"] for row in er["steps"]] == [0, 1]
    assert er["steps"][0]["raw_step_text"] == "Tap 'OK'"
    assert len(er["flow_draft"]["steps"]) == 2
    yaml_text = (tmp_path / MAESTRO_DRAFT_PREVIEW_FILENAME).read_text(encoding="utf-8")
    assert "appId: com.example.app" in yaml_text
    assert yaml_text.index("OK") < yaml_text.index("Next")
    built = build_maestro_draft_preview_yaml(app_id="com.example.app", result=result)
    assert built == yaml_text
    assert (tmp_path / "canonical_scenario.json").exists()


def test_input_enter_shoe_without_ranked_field_still_planned_direct_input_not_skipped() -> None:
    """No EditText in hierarchy → no selector primary; INPUT_TEXT still plans and executes."""
    p = _InputDirectReflectStub(csv=[_csv_no_hello_landmark(), _csv_edittext_shoe_typed()])
    orch = ScenarioPlanningOrchestrator(MaestroScreenService(p))
    result = orch.run_observe_plan_execute(_execute_request("Enter 'shoe'"))
    step = result.state.step_states[0]
    assert step.phase is RunStepPhase.VALIDATED
    assert step.planned_attempt is not None
    assert step.planned_attempt.chosen_candidate_id == DIRECT_INPUT_TEXT_CANDIDATE_ID
    assert step.phase is not RunStepPhase.SKIPPED_NO_SELECTOR
    assert p.input_calls == [("shoe", None)]
    assert p.run_flow_calls == []
    assert any("no ranked selector" in w.lower() for w in step.warnings)


def test_input_e2e_validated_when_literal_visible_after_direct_input() -> None:
    p = _InputDirectReflectStub(
        csv=[_csv_input_sibling_hello_row_edit_plain(), _csv_input_sibling_hello_row_edit_typed()],
    )
    orch = ScenarioPlanningOrchestrator(MaestroScreenService(p))
    result = orch.run_observe_plan_execute(_execute_request("Type 'hello' in the hello row"))
    step = result.state.step_states[0]
    assert step.phase is RunStepPhase.VALIDATED
    assert p.input_calls == [("hello", None)]
    assert p.run_flow_calls == []
    assert step.post_action_validation is not None
    assert any(e.code == "INPUT_VALIDATION_POLICY" for e in step.post_action_validation.evidence)


def test_input_e2e_validated_after_run_flow_fallback() -> None:
    p = _InputPrimaryThenFlowStub(
        csv=[_csv_input_sibling_hello_row_edit_plain(), _csv_input_sibling_hello_row_edit_typed()],
    )
    orch = ScenarioPlanningOrchestrator(MaestroScreenService(p))
    result = orch.run_observe_plan_execute(_execute_request("Type 'hello' in the hello row"))
    step = result.state.step_states[0]
    assert step.phase is RunStepPhase.VALIDATED
    assert p.input_calls == [("hello", None)]
    assert len(p.run_flow_calls) == 1
    assert "inputText" in p.run_flow_calls[0]
    assert "hello" in p.run_flow_calls[0]
    assert step.execution_outcome is not None
    assert step.execution_outcome.provider_action == "run_flow"


def test_input_e2e_inconclusive_when_provider_ok_but_no_reflection() -> None:
    p = _InputNeverReflectStub(csv=_csv_input_sibling_shoe_shelf_edit_plain())
    orch = ScenarioPlanningOrchestrator(MaestroScreenService(p))
    result = orch.run_observe_plan_execute(_execute_request("Type 'shoe' in the shoe shelf"))
    step = result.state.step_states[0]
    assert step.phase is RunStepPhase.VALIDATION_INCONCLUSIVE
    assert p.input_calls == [("shoe", None)]
    assert len(p.run_flow_calls) == 1
    assert step.post_action_validation is not None
    assert step.post_action_validation.outcome is PostActionValidationOutcome.INCONCLUSIVE
    assert any(e.code == "INPUT_VALIDATION_POLICY" for e in step.post_action_validation.evidence)


def test_build_maestro_draft_preview_yaml_emits_input_text_when_value_empty_string() -> None:
    """input_value may be ''; draft preview YAML should still emit inputText (quoted)."""
    b = FlowDraftBuilder(run_label="t")
    b.append_executed_validated(
        FlowStep(
            sequence=0,
            action=ActionType.INPUT_TEXT,
            summary="in",
            target_selector_hint="id:search",
            input_value="",
            metadata={},
        ),
    )
    req = ScenarioRunRequest(
        scenario_input=ScenarioInput(
            scenario_text="x",
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
    assert '- inputText: ""' in yaml_text
