"""Unit tests for ``PostExecutionValidationService`` (post-observe + deterministic goals)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from maestro_ai_agent.domain.enums import ActionType, Platform, SelectorType, ValidationSignalType
from maestro_ai_agent.domain.intent import StepIntent, ValidationGoal
from maestro_ai_agent.orchestrator.enums import (
    PostActionValidationOutcome,
    RunStepPhase,
    StepValidationStatus,
)
from maestro_ai_agent.orchestrator.models import (
    ObservationCycleResult,
    PlannedActionAttempt,
    ProviderExecutionOutcome,
    StepRunState,
)
from maestro_ai_agent.orchestrator.validation.validation_service import (
    PostExecutionValidationService,
)
from maestro_ai_agent.services.maestro.hierarchy_csv import parse_maestro_hierarchy_csv
from maestro_ai_agent.services.maestro.models import (
    ActionResult,
    ProviderCapabilities,
    ScreenshotArtifact,
)
from maestro_ai_agent.services.maestro.screen_service import MaestroScreenService


def _csv_ok() -> str:
    return '1,0,"text=OK; class=android.widget.Button; bounds=[0,0][100,40]",\n'


def _csv_next() -> str:
    return '1,0,"text=Next; class=android.widget.Button; bounds=[0,0][100,40]",\n'


class _PostValProvider:
    """Returns a fixed hierarchy on ``inspect_view_hierarchy`` (post-action frame)."""

    def __init__(self, post_csv: str) -> None:
        self._post_csv = post_csv

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities()

    def list_devices(self):
        raise NotImplementedError

    def launch_app(self, *, app_id: str, device_id: str | None = None, permissions=None):
        raise NotImplementedError

    def stop_app(self, *, app_id: str, device_id: str | None = None):
        raise NotImplementedError

    def inspect_view_hierarchy(self, *, device_id: str | None = None) -> str:
        return self._post_csv

    def take_screenshot(self, *, device_id: str | None = None) -> ScreenshotArtifact:
        return ScreenshotArtifact(byte_length=0)

    def tap_on(
        self,
        *,
        tap_id: str | None = None,
        tap_text: str | None = None,
        device_id: str | None = None,
    ) -> ActionResult:
        raise NotImplementedError

    def input_text(self, *, text: str, device_id: str | None = None) -> ActionResult:
        raise NotImplementedError

    def run_flow(self, *, flow_yaml: str, device_id: str | None = None) -> ActionResult:
        raise NotImplementedError

    def check_flow_syntax(self, *, flow_yaml: str):
        raise NotImplementedError


def _base_step(*, goals: list[ValidationGoal], before_csv: str) -> StepRunState:
    intent = StepIntent(
        intent_id=uuid4(),
        scenario_step_index=0,
        primary_action=ActionType.TAP,
        goal_summary="tap",
        raw_step_text="Tap 'OK'",
        validation_goals=goals,
    )
    obs = ObservationCycleResult(
        hierarchy=parse_maestro_hierarchy_csv(before_csv),
        parse_warnings=[],
        retrieved_at=datetime.now(UTC),
        app_id="com.example.app",
        platform=Platform.ANDROID,
    )
    planned = PlannedActionAttempt(
        intent_id=intent.intent_id,
        scenario_step_index=0,
        action=ActionType.TAP,
        chosen_candidate_id="c1",
        expression="text:OK",
        selector_type=SelectorType.TEXT,
        score=1.0,
        explanation_summary="x",
    )
    ex = ProviderExecutionOutcome(
        execution_attempted=True,
        provider_action="tap_on",
        selector_used="text:OK",
        action_result=ActionResult(ok=True, message=None),
        attempted_at=datetime.now(UTC),
    )
    return StepRunState(
        scenario_step_index=0,
        raw_step_text=intent.raw_step_text,
        intent=intent,
        phase=RunStepPhase.EXECUTED,
        observation=obs,
        planned_attempt=planned,
        execution_outcome=ex,
        validation_status=StepValidationStatus.DEFERRED,
    )


def test_validation_failed_when_text_visible_goal_contradicted() -> None:
    goals = [
        ValidationGoal(
            goal_id="g1",
            signal=ValidationSignalType.TEXT_VISIBLE,
            description="must see token",
            target_hint="__TOKEN_ABSENT__",
        ),
    ]
    step = _base_step(goals=goals, before_csv=_csv_ok())
    svc = PostExecutionValidationService(MaestroScreenService(_PostValProvider(_csv_next())))
    out = svc.validate_after_provider_success(
        step,
        app_id="com.example.app",
        platform=Platform.ANDROID,
        device_id=None,
        include_screenshot=False,
    )
    assert out.phase is RunStepPhase.VALIDATION_FAILED
    assert out.validation_status is StepValidationStatus.FAILED
    assert out.post_action_validation is not None
    assert out.post_action_validation.outcome is PostActionValidationOutcome.VALIDATION_FAILED


def test_validation_passes_when_expected_text_visible_after_tap() -> None:
    goals = [
        ValidationGoal(
            goal_id="g1",
            signal=ValidationSignalType.TEXT_VISIBLE,
            description="next screen",
            target_hint="Next",
        ),
    ]
    step = _base_step(goals=goals, before_csv=_csv_ok())
    svc = PostExecutionValidationService(MaestroScreenService(_PostValProvider(_csv_next())))
    out = svc.validate_after_provider_success(
        step,
        app_id="com.example.app",
        platform=Platform.ANDROID,
        device_id=None,
        include_screenshot=False,
    )
    assert out.phase is RunStepPhase.VALIDATED
    assert out.post_action_validation is not None
    assert out.post_action_validation.outcome is PostActionValidationOutcome.VALIDATED
