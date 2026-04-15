"""``DISMISS_BLOCKER`` scenario execution uses the runtime blocker engine."""

from __future__ import annotations

from uuid import uuid4

from maestro_ai_agent.domain.enums import ActionType, Platform, SelectorType, ValidationSignalType
from maestro_ai_agent.domain.intent import StepIntent, ValidationGoal
from maestro_ai_agent.orchestrator.action_attempt_planning import (
    DIRECT_INLINE_FLOW_CANDIDATE_ID,
    _flow_expression,
)
from maestro_ai_agent.orchestrator.enums import RunStepPhase
from maestro_ai_agent.orchestrator.execution.execution_service import ProviderStepExecutionService
from maestro_ai_agent.orchestrator.models import (
    ObservationCycleResult,
    PlannedActionAttempt,
    StepRunState,
)
from maestro_ai_agent.orchestrator.observation_cycle import build_observation_cycle_result
from maestro_ai_agent.services.maestro.models import (
    ActionResult,
    ProviderCapabilities,
    ScreenshotArtifact,
)
from maestro_ai_agent.services.maestro.screen_service import MaestroScreenService


def _csv_dev_mode_with_continue() -> str:
    return (
        '1,0,"text=Developer Mode; class=android.widget.TextView; bounds=[0,0][200,40]",\n'
        '2,0,"text=Continue; class=android.widget.Button; bounds=[110,50][210,80]",\n'
    )


def _csv_plain_home() -> str:
    return '1,0,"text=Home; class=android.widget.TextView; bounds=[0,0][100,40]",\n'


class _ClearsOnTap:
    def __init__(self, *, dialog: str, home: str) -> None:
        self._dialog = dialog
        self._home = home
        self._cleared = False

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities()

    def list_devices(self):
        raise NotImplementedError

    def launch_app(self, **kwargs):
        raise NotImplementedError

    def stop_app(self, **kwargs):
        raise NotImplementedError

    def inspect_view_hierarchy(self, *, device_id: str | None = None) -> str:
        return self._home if self._cleared else self._dialog

    def take_screenshot(self, *, device_id: str | None = None) -> ScreenshotArtifact:
        return ScreenshotArtifact(byte_length=0)

    def tap_on(
        self,
        *,
        tap_id: str | None = None,
        tap_text: str | None = None,
        device_id: str | None = None,
    ) -> ActionResult:
        self._cleared = True
        return ActionResult(ok=True, message=None)

    def run_flow(self, *, flow_yaml: str, device_id: str | None = None) -> ActionResult:
        return ActionResult(ok=False, message="unused")

    def input_text(self, **kwargs):
        raise NotImplementedError

    def check_flow_syntax(self, **kwargs):
        raise NotImplementedError


class _PlainHome:
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities()

    def list_devices(self):
        raise NotImplementedError

    def launch_app(self, **kwargs):
        raise NotImplementedError

    def stop_app(self, **kwargs):
        raise NotImplementedError

    def inspect_view_hierarchy(self, *, device_id: str | None = None) -> str:
        return _csv_plain_home()

    def take_screenshot(self, *, device_id: str | None = None) -> ScreenshotArtifact:
        return ScreenshotArtifact(byte_length=0)

    def tap_on(self, **kwargs) -> ActionResult:
        raise AssertionError("no blocker — must not tap")

    def run_flow(self, **kwargs) -> ActionResult:
        raise AssertionError("no blocker — must not run_flow")

    def input_text(self, **kwargs):
        raise NotImplementedError

    def check_flow_syntax(self, **kwargs):
        raise NotImplementedError


def _step_dismiss_blocker(
    *,
    obs: ObservationCycleResult,
    phase: RunStepPhase = RunStepPhase.PLANNED,
) -> StepRunState:
    iid = uuid4()
    intent = StepIntent(
        intent_id=iid,
        scenario_step_index=0,
        primary_action=ActionType.DISMISS_BLOCKER,
        goal_summary="Dismiss blocking UI",
        raw_step_text="Dismiss popup",
        validation_goals=[
            ValidationGoal(
                goal_id="vg-dismiss-1",
                signal=ValidationSignalType.HIERARCHY_CHANGED,
                description="Dismiss step post-check.",
                target_hint=None,
            ),
        ],
    )
    planned = PlannedActionAttempt(
        intent_id=iid,
        scenario_step_index=0,
        action=ActionType.DISMISS_BLOCKER,
        chosen_candidate_id=DIRECT_INLINE_FLOW_CANDIDATE_ID,
        expression=_flow_expression("dismiss_blocker", ""),
        selector_type=SelectorType.TEXT,
        score=0.0,
        explanation_summary="fixture",
    )
    return StepRunState(
        scenario_step_index=0,
        raw_step_text=intent.raw_step_text,
        intent=intent,
        phase=phase,
        observation=obs,
        planned_attempt=planned,
    )


def test_dismiss_blocker_execution_runs_engine_and_records_episode() -> None:
    p = _ClearsOnTap(dialog=_csv_dev_mode_with_continue(), home=_csv_plain_home())
    screen = MaestroScreenService(p)
    structured = screen.observe_current_screen(
        app_id="com.example",
        platform=Platform.ANDROID,
        device_id="d1",
        include_screenshot=False,
    )
    obs = build_observation_cycle_result(structured)
    step = _step_dismiss_blocker(obs=obs)
    svc = ProviderStepExecutionService(screen)
    out = svc.execute_top_planned_if_supported(step, device_id="d1")
    assert out.blocker_episode is not None
    assert out.blocker_episode["handled"] is True
    assert out.blocker_episode["verified_cleared"] is True
    assert out.blocker_episode["dismiss_text"] == "Continue"
    assert out.phase is RunStepPhase.EXECUTED


def test_dismiss_blocker_no_pattern_no_tap() -> None:
    p = _PlainHome()
    screen = MaestroScreenService(p)
    structured = screen.observe_current_screen(
        app_id="com.example",
        platform=Platform.ANDROID,
        device_id="d1",
        include_screenshot=False,
    )
    obs = build_observation_cycle_result(structured)
    step = _step_dismiss_blocker(obs=obs)
    svc = ProviderStepExecutionService(screen)
    out = svc.execute_top_planned_if_supported(step, device_id="d1")
    assert out.blocker_episode is not None
    assert out.blocker_episode["code"] == "no_known_blocking_pattern"
    assert out.phase is RunStepPhase.EXECUTED
