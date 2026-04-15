"""Visual advisory hint merge and request shaping (no network)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from maestro_ai_agent.domain.enums import ActionType, Platform
from maestro_ai_agent.domain.hierarchy import HierarchySnapshot
from maestro_ai_agent.domain.intent import StepIntent
from maestro_ai_agent.domain.selectors.intent_match import infer_target_hints
from maestro_ai_agent.domain.selectors.target_hints import TargetHints
from maestro_ai_agent.domain.visual_advisory import VisualAdvisoryResponse
from maestro_ai_agent.orchestrator.models import ObservationCycleResult, StepRunState
from maestro_ai_agent.orchestrator.visual_advisory_support import (
    build_visual_advisory_request,
    hierarchy_digest_for_visual_advisory,
    merge_visual_advisory_into_hints,
)
from maestro_ai_agent.services.maestro.models import ScreenshotArtifact


def test_merge_appends_text_when_confident() -> None:
    base = infer_target_hints(
        StepIntent(
            intent_id=uuid4(),
            scenario_step_index=0,
            primary_action=ActionType.TAP,
            goal_summary="tap",
            raw_step_text="Tap 'X'",
            validation_goals=[],
        ),
    )
    adv = VisualAdvisoryResponse(
        likely_visible_text="Cart",
        confidence=0.9,
    )
    merged = merge_visual_advisory_into_hints(base, adv)
    assert "Cart" in merged.desired_texts


def test_merge_respects_low_confidence() -> None:
    base = TargetHints(desired_texts=["A"])
    adv = VisualAdvisoryResponse(likely_visible_text="B", confidence=0.1)
    merged = merge_visual_advisory_into_hints(base, adv)
    assert merged.desired_texts == ["A"]


def test_hierarchy_digest_is_bounded() -> None:
    h = HierarchySnapshot(nodes=[], raw_csv="")
    d = hierarchy_digest_for_visual_advisory(h)
    assert "node_count" in d
    assert "visible_text_tokens_sample" in d


def test_build_request_includes_step_and_screenshot_meta() -> None:
    intent = StepIntent(
        intent_id=uuid4(),
        scenario_step_index=0,
        primary_action=ActionType.TAP,
        goal_summary="tap cart",
        raw_step_text="Tap 'Cart'",
        validation_goals=[],
    )
    step = StepRunState(scenario_step_index=0, raw_step_text=intent.raw_step_text, intent=intent)
    obs = ObservationCycleResult(
        hierarchy=HierarchySnapshot(nodes=[], raw_csv=""),
        parse_warnings=[],
        retrieved_at=datetime.now(UTC),
        app_id="com.example",
        platform=Platform.IOS,
        screenshot=ScreenshotArtifact(
            byte_length=3,
            image_bytes=b"\x01\x02\x03",
            sha256="abc",
        ),
    )
    req = build_visual_advisory_request(step, obs)
    assert req.app_id == "com.example"
    assert req.screenshot_byte_length == 3
    assert req.screenshot_bytes == b"\x01\x02\x03"
