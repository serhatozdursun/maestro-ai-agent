"""ProviderStepExecutionService: text-first tap retries."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch
from uuid import uuid4

from maestro_ai_agent.domain.confidence import ConfidenceScore
from maestro_ai_agent.domain.enums import ActionType, Platform, SelectorType
from maestro_ai_agent.domain.intent import StepIntent
from maestro_ai_agent.domain.selector import SelectorCandidate
from maestro_ai_agent.domain.selectors.evidence import EvidenceKind, SelectorEvidence
from maestro_ai_agent.domain.selectors.explanation import SelectorExplanation, SelectorReasonCode
from maestro_ai_agent.domain.selectors.ranking_types import (
    RankedSelectorCandidate,
    SelectorRankingResult,
)
from maestro_ai_agent.domain.selectors.tap_resolution import TapResolutionSettings
from maestro_ai_agent.orchestrator.enums import PostActionValidationOutcome, RunStepPhase
from maestro_ai_agent.orchestrator.execution.execution_service import ProviderStepExecutionService
from maestro_ai_agent.orchestrator.models import (
    BeforeAfterObservationSummary,
    ObservationCycleResult,
    PlannedActionAttempt,
    PostActionValidationRecord,
    ProviderExecutionOutcome,
    StepRunState,
)
from maestro_ai_agent.orchestrator.planning_service import _build_post_execution_flow_step
from maestro_ai_agent.services.maestro.hierarchy_csv import parse_maestro_hierarchy_csv
from maestro_ai_agent.services.maestro.models import (
    ActionResult,
    ProviderCapabilities,
    ScreenshotArtifact,
)
from maestro_ai_agent.services.maestro.screen_service import MaestroScreenService


def _ranked(
    *,
    cid: str,
    expr: str,
    stype: SelectorType,
    score: float,
) -> RankedSelectorCandidate:
    return RankedSelectorCandidate(
        candidate=SelectorCandidate(
            candidate_id=cid,
            selector_type=stype,
            expression=expr,
            rationale="test",
            rank=0,
            confidence=ConfidenceScore(value=0.8),
        ),
        score=score,
        evidence=[SelectorEvidence(kind=EvidenceKind.VISIBLE_TEXT, weight=0.5, detail="d")],
        explanation=SelectorExplanation(
            codes=[SelectorReasonCode.FALLBACK_CANDIDATE_ONLY],
            summary="s",
        ),
    )


class _RetryTapProvider:
    """First tap (text) fails; second (id) succeeds."""

    def __init__(self) -> None:
        self.tap_calls: list[tuple[str | None, str | None]] = []
        self.run_flow_calls: list[str] = []

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities()

    def list_devices(self):
        raise NotImplementedError

    def launch_app(self, *, app_id: str, device_id: str | None = None, permissions=None):
        raise NotImplementedError

    def stop_app(self, *, app_id: str, device_id: str | None = None):
        raise NotImplementedError

    def inspect_view_hierarchy(self, *, device_id: str | None = None) -> str:
        if any(t == ("second", None) for t in self.tap_calls):
            return '2,0,"text=changed; class=android.view.View",\n'
        return '1,0,"text=x; class=android.view.View",\n'

    def take_screenshot(self, *, device_id: str | None = None) -> ScreenshotArtifact:
        return ScreenshotArtifact(byte_length=0)

    def tap_on(
        self,
        *,
        tap_id: str | None = None,
        tap_text: str | None = None,
        device_id: str | None = None,
    ) -> ActionResult:
        self.tap_calls.append((tap_id, tap_text))
        if tap_text == "X":
            return ActionResult(ok=False, message="not found")
        if tap_id == "second":
            return ActionResult(ok=True, message=None)
        return ActionResult(ok=False, message="unexpected")

    def run_flow(self, *, flow_yaml: str, device_id: str | None = None) -> ActionResult:
        self.run_flow_calls.append(flow_yaml)
        return ActionResult(ok=False, message="run_flow not used for id path in this stub")

    def input_text(self, *, text: str, device_id: str | None = None):
        raise NotImplementedError

    def check_flow_syntax(self, *, flow_yaml: str):
        raise NotImplementedError


def _planned_primary_id() -> PlannedActionAttempt:
    iid = uuid4()
    return PlannedActionAttempt(
        intent_id=iid,
        scenario_step_index=0,
        action=ActionType.TAP,
        chosen_candidate_id="i1",
        expression="id:second",
        selector_type=SelectorType.ID,
        score=0.99,
        rank_position=0,
        explanation_summary="primary id",
    )


def test_text_attempt_then_id_on_failure() -> None:
    intent = StepIntent(
        intent_id=_planned_primary_id().intent_id,
        scenario_step_index=0,
        primary_action=ActionType.TAP,
        goal_summary="tap",
        raw_step_text="Tap 'X'",
        validation_goals=[],
    )
    id_row = _ranked(cid="i1", expr="id:second", stype=SelectorType.ID, score=0.99)
    text_row = _ranked(cid="t1", expr="text:X", stype=SelectorType.TEXT, score=0.5)
    ranking = SelectorRankingResult(ordered=[id_row, text_row], primary=id_row)
    planned = _planned_primary_id()
    h = parse_maestro_hierarchy_csv(_RetryTapProvider().inspect_view_hierarchy())
    obs = ObservationCycleResult(
        hierarchy=h,
        parse_warnings=[],
        retrieved_at=datetime.now(UTC),
        app_id="c",
        platform=Platform.ANDROID,
    )
    step = StepRunState(
        scenario_step_index=0,
        raw_step_text=intent.raw_step_text,
        intent=intent,
        phase=RunStepPhase.PLANNED,
        observation=obs,
        ranking=ranking,
        planned_attempt=planned,
    )
    p = _RetryTapProvider()
    out = ProviderStepExecutionService(MaestroScreenService(p)).execute_top_planned_if_supported(
        step,
        device_id=None,
    )
    assert out.phase is RunStepPhase.EXECUTED
    assert p.tap_calls[0] == (None, "X")
    assert p.tap_calls[1] == ("second", None)
    assert len(p.run_flow_calls) == 1
    assert out.planned_attempt is not None
    assert out.planned_attempt.selector_type is SelectorType.ID
    assert out.execution_outcome is not None
    assert out.execution_outcome.selector_used == "id:second"


def test_planned_attempt_unchanged_after_text_first_success() -> None:
    """Planned YAML row stays stability-ranked (id-first); runtime tries text first.

    When the first text ``tap_on`` succeeds but the hierarchy is unchanged, ``run_flow`` is
    not used for the same selector; the next runtime candidate (id) wins once its tap changes
    the tree.
    """
    intent = StepIntent(
        intent_id=_planned_primary_id().intent_id,
        scenario_step_index=0,
        primary_action=ActionType.TAP,
        goal_summary="tap",
        raw_step_text="Tap 'X'",
        validation_goals=[],
    )
    id_row = _ranked(cid="i1", expr="id:bag", stype=SelectorType.ID, score=0.99)
    text_row = _ranked(cid="t1", expr="text:X", stype=SelectorType.TEXT, score=0.5)
    ranking = SelectorRankingResult(ordered=[id_row, text_row], primary=id_row)
    planned = _planned_primary_id()
    planned = planned.model_copy(
        update={
            "chosen_candidate_id": id_row.candidate.candidate_id,
            "expression": id_row.candidate.expression,
            "selector_type": id_row.candidate.selector_type,
        },
    )

    class _OkTextThenIdChangesHierarchy:
        def __init__(self) -> None:
            self.tap_calls: list[tuple[str | None, str | None]] = []
            self.run_flow_calls: list[str] = []

        def capabilities(self) -> ProviderCapabilities:
            return ProviderCapabilities()

        def list_devices(self):
            raise NotImplementedError

        def launch_app(self, *, app_id: str, device_id: str | None = None, permissions=None):
            raise NotImplementedError

        def stop_app(self, *, app_id: str, device_id: str | None = None):
            raise NotImplementedError

        def inspect_view_hierarchy(self, *, device_id: str | None = None) -> str:
            if len(self.tap_calls) >= 2:
                return '1,0,"text=after_id; class=android.view.View",\n'
            return '1,0,"text=x; class=android.view.View",\n'

        def take_screenshot(self, *, device_id: str | None = None) -> ScreenshotArtifact:
            return ScreenshotArtifact(byte_length=0)

        def tap_on(
            self,
            *,
            tap_id: str | None = None,
            tap_text: str | None = None,
            device_id: str | None = None,
        ) -> ActionResult:
            self.tap_calls.append((tap_id, tap_text))
            return ActionResult(ok=True, message=None)

        def input_text(self, *, text: str, device_id: str | None = None):
            raise NotImplementedError

        def run_flow(self, *, flow_yaml: str, device_id: str | None = None) -> ActionResult:
            self.run_flow_calls.append(flow_yaml)
            return ActionResult(ok=True, message=None)

        def check_flow_syntax(self, *, flow_yaml: str):
            raise NotImplementedError

    pr = _OkTextThenIdChangesHierarchy()
    h = parse_maestro_hierarchy_csv(pr.inspect_view_hierarchy())
    obs = ObservationCycleResult(
        hierarchy=h,
        parse_warnings=[],
        retrieved_at=datetime.now(UTC),
        app_id="c",
        platform=Platform.ANDROID,
    )
    step = StepRunState(
        scenario_step_index=0,
        raw_step_text=intent.raw_step_text,
        intent=intent,
        phase=RunStepPhase.PLANNED,
        observation=obs,
        ranking=ranking,
        planned_attempt=planned,
    )
    out = ProviderStepExecutionService(MaestroScreenService(pr)).execute_top_planned_if_supported(
        step,
        device_id=None,
    )
    assert out.planned_attempt.expression == "id:bag"
    assert out.execution_outcome is not None
    assert out.execution_outcome.selector_used == "id:bag"
    assert out.execution_outcome.provider_action == "tap_on"
    assert pr.tap_calls == [(None, "X"), ("bag", None)]
    assert pr.run_flow_calls == []


def test_post_execution_flow_step_uses_planned_expression_not_runtime_selector() -> None:
    """Draft flow hint follows stability-ranked ``planned_attempt``, not ``selector_used``."""
    iid = uuid4()
    planned = PlannedActionAttempt(
        intent_id=iid,
        scenario_step_index=0,
        action=ActionType.TAP,
        chosen_candidate_id="i1",
        expression="id:stable_row",
        selector_type=SelectorType.ID,
        score=0.99,
        rank_position=0,
        explanation_summary="primary",
    )
    intent = StepIntent(
        intent_id=iid,
        scenario_step_index=0,
        primary_action=ActionType.TAP,
        goal_summary="tap",
        raw_step_text="Tap",
        validation_goals=[],
    )
    ex = ProviderExecutionOutcome(
        provider_action="tap_on",
        selector_used="text:RuntimeOnly",
        text_input_used=None,
        action_result=ActionResult(ok=True, message=None),
        attempted_at=datetime.now(UTC),
        unsupported_reason=None,
        execution_attempted=True,
    )
    pav = PostActionValidationRecord(
        outcome=PostActionValidationOutcome.VALIDATED,
        before_after_summary=BeforeAfterObservationSummary(),
        evidence=[],
        notes=[],
    )
    step = StepRunState(
        scenario_step_index=0,
        raw_step_text="Tap",
        intent=intent,
        phase=RunStepPhase.VALIDATED,
        planned_attempt=planned,
        execution_outcome=ex,
        post_action_validation=pav,
    )
    flow = _build_post_execution_flow_step(step)
    assert flow is not None
    assert flow.target_selector_hint == "id:stable_row"


def test_runtime_tap_wrong_branch_runs_back_then_next_candidate() -> None:
    """When the next step is not plannable after a successful tap, run back and rotate."""
    iid0 = uuid4()
    iid1 = uuid4()
    intent0 = StepIntent(
        intent_id=iid0,
        scenario_step_index=0,
        primary_action=ActionType.TAP,
        goal_summary="tap",
        raw_step_text="Tap 'MisTap'",
        validation_goals=[],
    )
    next_intent = StepIntent(
        intent_id=iid1,
        scenario_step_index=1,
        primary_action=ActionType.TAP,
        goal_summary="tap",
        raw_step_text="Tap 'Checkout'",
        validation_goals=[],
    )
    r_mis = _ranked(cid="m1", expr="text:MisTap", stype=SelectorType.TEXT, score=0.95)
    r_good = _ranked(cid="g1", expr="text:GoodTap", stype=SelectorType.TEXT, score=0.5)
    ranking = SelectorRankingResult(ordered=[r_mis, r_good], primary=r_mis)
    planned = PlannedActionAttempt(
        intent_id=iid0,
        scenario_step_index=0,
        action=ActionType.TAP,
        chosen_candidate_id=r_mis.candidate.candidate_id,
        expression=r_mis.candidate.expression,
        selector_type=r_mis.candidate.selector_type,
        score=r_mis.score,
        rank_position=0,
        explanation_summary="mis",
    )

    home_csv = (
        '1,0,"text=MisTap; class=android.widget.Button; bounds=[0,0][10,10]",\n'
        '2,0,"text=GoodTap; class=android.widget.Button; bounds=[0,20][10,30]",\n'
    )
    wrong_csv = '1,0,"text=NoCheckoutHere; class=android.widget.TextView",\n'
    good_csv = '1,0,"text=Checkout; class=android.widget.Button; bounds=[0,0][20,10]",\n'

    class _BranchProv:
        def __init__(self) -> None:
            self.scene = "home"
            self.tap_calls: list[tuple[str | None, str | None]] = []
            self.run_flow_calls: list[str] = []

        def capabilities(self) -> ProviderCapabilities:
            return ProviderCapabilities()

        def list_devices(self):
            raise NotImplementedError

        def launch_app(self, *, app_id: str, device_id: str | None = None, permissions=None):
            raise NotImplementedError

        def stop_app(self, *, app_id: str, device_id: str | None = None):
            raise NotImplementedError

        def inspect_view_hierarchy(self, *, device_id: str | None = None) -> str:
            if self.scene == "home":
                return home_csv
            if self.scene == "wrong":
                return wrong_csv
            return good_csv

        def take_screenshot(self, *, device_id: str | None = None) -> ScreenshotArtifact:
            return ScreenshotArtifact(byte_length=0)

        def tap_on(
            self,
            *,
            tap_id: str | None = None,
            tap_text: str | None = None,
            device_id: str | None = None,
        ) -> ActionResult:
            self.tap_calls.append((tap_id, tap_text))
            if tap_text == "MisTap":
                self.scene = "wrong"
            elif tap_text == "GoodTap":
                self.scene = "good"
            return ActionResult(ok=True, message=None)

        def input_text(self, *, text: str, device_id: str | None = None):
            raise NotImplementedError

        def run_flow(self, *, flow_yaml: str, device_id: str | None = None) -> ActionResult:
            self.run_flow_calls.append(flow_yaml)
            if "back" in flow_yaml.lower():
                self.scene = "home"
            return ActionResult(ok=True, message=None)

        def check_flow_syntax(self, *, flow_yaml: str):
            raise NotImplementedError

    pr = _BranchProv()
    h = parse_maestro_hierarchy_csv(home_csv)
    obs = ObservationCycleResult(
        hierarchy=h,
        parse_warnings=[],
        retrieved_at=datetime.now(UTC),
        app_id="com.x",
        platform=Platform.ANDROID,
    )
    step = StepRunState(
        scenario_step_index=0,
        raw_step_text=intent0.raw_step_text,
        intent=intent0,
        phase=RunStepPhase.PLANNED,
        observation=obs,
        ranking=ranking,
        planned_attempt=planned,
    )
    probe_path = (
        "maestro_ai_agent.orchestrator.execution.execution_service."
        "next_intent_resolvable_for_branch_probe"
    )
    with patch(probe_path) as probe:
        probe.side_effect = [False, True]
        svc = ProviderStepExecutionService(MaestroScreenService(pr))
        out = svc.execute_top_planned_if_supported(
            step,
            device_id="d",
            next_intent=next_intent,
            tap_resolution=TapResolutionSettings(),
        )
    assert out.phase is RunStepPhase.EXECUTED
    assert pr.tap_calls[0] == (None, "MisTap")
    assert any("back" in y.lower() for y in pr.run_flow_calls)
    assert pr.tap_calls[-1] == (None, "GoodTap")
    assert out.execution_outcome is not None
    assert out.execution_outcome.selector_used == "text:GoodTap"
