"""Pydantic validation edge cases for core domain models."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from maestro_ai_agent.domain.confidence import ConfidenceScore
from maestro_ai_agent.domain.enums import ActionType, Platform, SelectorType, StepStatus
from maestro_ai_agent.domain.flow import FlowStep
from maestro_ai_agent.domain.observation import ExecutionAttempt, ScreenObservation
from maestro_ai_agent.domain.scenario import ScenarioInput
from maestro_ai_agent.domain.selector import SelectorCandidate


def test_confidence_score_bounds() -> None:
    with pytest.raises(ValidationError):
        ConfidenceScore(value=1.5)


def test_confidence_score_derives_level() -> None:
    score = ConfidenceScore(value=0.9)
    assert score.level is not None
    assert score.level.value == "high"


def test_scenario_input_rejects_blank_text() -> None:
    with pytest.raises(ValidationError):
        ScenarioInput(scenario_text="   ", app_id="x", platform=Platform.ANDROID)


def test_flow_step_requires_summary() -> None:
    with pytest.raises(ValidationError):
        FlowStep(sequence=0, action=ActionType.TAP, summary="")


def test_selector_candidate_requires_fields() -> None:
    with pytest.raises(ValidationError):
        SelectorCandidate(
            candidate_id="",
            selector_type=SelectorType.TEXT,
            expression=None,
            rationale="x",
            rank=0,
            confidence=ConfidenceScore(value=0.5),
        )


def test_execution_attempt_roundtrip() -> None:
    oid = uuid4()
    obs = ScreenObservation(
        observation_id=oid,
        recorded_at=datetime(2026, 1, 1, tzinfo=UTC),
        platform=Platform.ANDROID,
        hierarchy_summary="stub",
    )
    attempt = ExecutionAttempt(
        attempt_id=uuid4(),
        intent_id=uuid4(),
        scenario_step_index=0,
        action=ActionType.TAP,
        status=StepStatus.SUCCEEDED,
        screen_before=obs,
    )
    dumped = attempt.model_dump(mode="json")
    assert dumped["status"] == StepStatus.SUCCEEDED.value
    assert dumped["screen_before"]["observation_id"] == str(oid)
