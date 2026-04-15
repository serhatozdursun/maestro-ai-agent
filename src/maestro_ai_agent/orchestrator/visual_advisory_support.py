"""Build advisory requests and merge AI hints into :class:`TargetHints` (deterministic re-rank)."""

from __future__ import annotations

from maestro_ai_agent.domain.hierarchy import HierarchySnapshot
from maestro_ai_agent.domain.selectors.target_hints import TargetHints
from maestro_ai_agent.domain.visual_advisory import VisualAdvisoryRequest, VisualAdvisoryResponse
from maestro_ai_agent.orchestrator.models import ObservationCycleResult, StepRunState
from maestro_ai_agent.orchestrator.validation.hierarchy_compare import visible_text_tokens


def hierarchy_digest_for_visual_advisory(hierarchy: HierarchySnapshot) -> dict[str, object]:
    """Small, JSON-safe context for an advisory call (not a full hierarchy dump)."""
    texts = sorted(visible_text_tokens(hierarchy))
    return {
        "node_count": len(hierarchy.nodes),
        "visible_text_tokens_sample": texts[:24],
        "parse_warnings": list(hierarchy.parse_warnings)[:5],
    }


def build_visual_advisory_request(
    step: StepRunState,
    observation: ObservationCycleResult,
) -> VisualAdvisoryRequest:
    """Build request from step + observation (screenshot bytes when captured)."""
    shot = observation.screenshot
    return VisualAdvisoryRequest(
        scenario_step_text=step.raw_step_text,
        intent_goal_summary=step.intent.goal_summary,
        app_id=observation.app_id,
        platform=observation.platform,
        hierarchy_digest=hierarchy_digest_for_visual_advisory(observation.hierarchy),
        screenshot_mime_type=shot.mime_type if shot else "image/png",
        screenshot_byte_length=shot.byte_length if shot else 0,
        screenshot_sha256=shot.sha256 if shot else None,
        screenshot_bytes=shot.image_bytes if shot else None,
    )


def merge_visual_advisory_into_hints(
    hints: TargetHints,
    advisory: VisualAdvisoryResponse,
    *,
    min_confidence: float = 0.35,
) -> TargetHints:
    """Merge advisory labels into hints for a second deterministic ranking pass."""
    if advisory.confidence < min_confidence:
        return hints
    desired = list(hints.desired_texts)
    semantic = list(hints.semantic_keywords)
    existing_d = {d.lower() for d in desired}
    existing_s = {s.lower() for s in semantic}
    if advisory.likely_visible_text:
        t = advisory.likely_visible_text.strip()
        if t and t.lower() not in existing_d:
            desired.append(t)
            existing_d.add(t.lower())
    if advisory.likely_semantic_label:
        s = advisory.likely_semantic_label.strip()
        if s and s.lower() not in existing_s:
            semantic.append(s)
    return hints.model_copy(update={"desired_texts": desired, "semantic_keywords": semantic})
