"""Tests for FlowDraftBuilder."""

from uuid import uuid4

import pytest

from maestro_ai_agent.domain.enums import ActionType
from maestro_ai_agent.domain.flow import FlowStep
from maestro_ai_agent.domain.flow_draft import FlowDraftBuilder


def test_append_successful_and_serialize_roundtrip_keys() -> None:
    builder = FlowDraftBuilder(run_label="unit-test")
    intent_id = uuid4()
    step0 = FlowStep(
        sequence=0,
        action=ActionType.LAUNCH_APP,
        summary="Launch app",
        intent_id=intent_id,
        metadata={"scenario_step_index": "0"},
    )
    builder.append_successful(step0)
    payload = builder.to_serializable()
    assert payload["run_label"] == "unit-test"
    assert len(payload["steps"]) == 1
    assert payload["steps"][0]["action"] == ActionType.LAUNCH_APP.value
    assert payload["steps"][0]["intent_id"] == str(intent_id)
    assert "created_at" in payload and "updated_at" in payload


def test_append_requires_monotonic_sequence() -> None:
    builder = FlowDraftBuilder()
    builder.append_successful(
        FlowStep(sequence=0, action=ActionType.TAP, summary="Tap next", intent_id=None)
    )
    bad = FlowStep(sequence=2, action=ActionType.TAP, summary="Wrong sequence", intent_id=None)
    with pytest.raises(ValueError, match="sequence"):
        builder.append_successful(bad)


def test_append_planned_marks_lifecycle_metadata() -> None:
    builder = FlowDraftBuilder()
    step = FlowStep(
        sequence=0,
        action=ActionType.TAP,
        summary="[planned] tap ok",
        target_selector_hint="text:OK",
        intent_id=None,
        metadata={"scenario_step_index": "0"},
    )
    builder.append_planned(step)
    stored = builder.draft().steps[0]
    assert stored.metadata["lifecycle"] == "planned"
    assert stored.metadata["executed"] == "false"
    assert stored.metadata["validated"] == "false"


def test_append_executed_validated_metadata() -> None:
    builder = FlowDraftBuilder()
    step = FlowStep(
        sequence=0,
        action=ActionType.TAP,
        summary="tap",
        intent_id=None,
        metadata={"scenario_step_index": "0"},
    )
    builder.append_executed_validated(step)
    m = builder.draft().steps[0].metadata
    assert m["lifecycle"] == "executed_validated"
    assert m["validated"] == "true"
    assert m["validation_outcome"] == "validated"


def test_append_executed_validation_failed_metadata() -> None:
    builder = FlowDraftBuilder()
    step = FlowStep(sequence=0, action=ActionType.TAP, summary="tap", intent_id=None)
    builder.append_executed_validation_failed(step)
    m = builder.draft().steps[0].metadata
    assert m["lifecycle"] == "executed_validation_failed"
    assert m["validation_outcome"] == "validation_failed"


def test_append_executed_validation_inconclusive_metadata() -> None:
    builder = FlowDraftBuilder()
    step = FlowStep(sequence=0, action=ActionType.TAP, summary="tap", intent_id=None)
    builder.append_executed_validation_inconclusive(step)
    m = builder.draft().steps[0].metadata
    assert m["lifecycle"] == "executed_validation_inconclusive"
    assert m["validation_outcome"] == "validation_inconclusive"


def test_append_executed_validation_skipped_metadata() -> None:
    builder = FlowDraftBuilder()
    step = FlowStep(sequence=0, action=ActionType.TAP, summary="tap", intent_id=None)
    builder.append_executed_validation_skipped(step)
    m = builder.draft().steps[0].metadata
    assert m["lifecycle"] == "executed_validation_skipped"
    assert m["validation_outcome"] == "validation_skipped"


def test_append_executed_unvalidated_metadata() -> None:
    builder = FlowDraftBuilder()
    step = FlowStep(
        sequence=0,
        action=ActionType.INPUT_TEXT,
        summary="[executed] type text",
        target_selector_hint=None,
        input_value="x",
        intent_id=None,
        metadata={"scenario_step_index": "0"},
    )
    builder.append_executed_unvalidated(step)
    stored = builder.draft().steps[0]
    assert stored.metadata["lifecycle"] == "executed_unvalidated"
    assert stored.metadata["executed"] == "true"
    assert stored.metadata["validated"] == "false"
    assert stored.metadata["validation"] == "deferred"
