"""Optional visual advisory re-rank (hierarchy-first, second pass only)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from maestro_ai_agent.domain.enums import ActionType, Platform
from maestro_ai_agent.domain.intent import StepIntent
from maestro_ai_agent.domain.visual_advisory import VisualAdvisoryRequest, VisualAdvisoryResponse
from maestro_ai_agent.orchestrator.enums import RunStepPhase
from maestro_ai_agent.orchestrator.models import ObservationCycleResult, StepRunState
from maestro_ai_agent.orchestrator.step_processing import rank_and_plan_for_step
from maestro_ai_agent.services.maestro.hierarchy_csv import parse_maestro_hierarchy_csv
from maestro_ai_agent.services.maestro.models import ScreenshotArtifact


class _StubSuggester:
    def suggest(self, request: VisualAdvisoryRequest) -> VisualAdvisoryResponse | None:
        return VisualAdvisoryResponse(likely_visible_text="OK", confidence=0.95)


def test_visual_fallback_second_pass_plans_when_hints_augmented() -> None:
    csv = '1,0,"text=OK; class=android.widget.Button; bounds=[0,0][100,40]",\n'
    hierarchy = parse_maestro_hierarchy_csv(csv)
    intent = StepIntent(
        intent_id=uuid4(),
        scenario_step_index=0,
        primary_action=ActionType.TAP,
        goal_summary="tap",
        raw_step_text="Tap 'ZZZ'",
        validation_goals=[],
    )
    obs = ObservationCycleResult(
        hierarchy=hierarchy,
        parse_warnings=[],
        retrieved_at=datetime.now(UTC),
        app_id="com.example",
        platform=Platform.ANDROID,
        screenshot=ScreenshotArtifact(byte_length=1, image_bytes=b"\xff"),
    )
    step = StepRunState(
        scenario_step_index=0,
        raw_step_text=intent.raw_step_text,
        intent=intent,
        phase=RunStepPhase.OBSERVED,
        observation=obs,
    )
    out = rank_and_plan_for_step(
        step,
        enable_visual_advisory_fallback=True,
        visual_target_suggester=_StubSuggester(),
    )
    assert out.phase is RunStepPhase.PLANNED
    assert out.planned_attempt is not None
    assert "OK" in (out.planned_attempt.expression or "")
    assert any("Visual advisory fallback re-ranked" in w for w in out.warnings)
