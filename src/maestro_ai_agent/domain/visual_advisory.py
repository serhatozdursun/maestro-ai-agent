"""Models for optional screenshot-backed visual advisory (AI-ready, no LLM coupling)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from maestro_ai_agent.domain.enums import Platform


class BoundingBoxHint(BaseModel):
    """Optional normalized screen region (0..1) from an external vision model."""

    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)
    width: float = Field(ge=0.0, le=1.0)
    height: float = Field(ge=0.0, le=1.0)


class VisualAdvisoryRequest(BaseModel):
    """
    Payload for :class:`VisualTargetSuggester` (screenshot + light context).

    ``screenshot_bytes`` may be omitted in tests; production callers should attach bytes
    when available (can be large—avoid logging full dumps).
    """

    scenario_step_text: str
    intent_goal_summary: str
    app_id: str
    platform: Platform
    hierarchy_digest: dict[str, object] = Field(
        default_factory=dict,
        description="Small JSON-safe summary (node counts, text tokens)—not full CSV.",
    )
    screenshot_mime_type: str = "image/png"
    screenshot_byte_length: int = 0
    screenshot_sha256: str | None = None
    screenshot_bytes: bytes | None = Field(default=None, repr=False)


class VisualAdvisoryResponse(BaseModel):
    """Structured guess from a vision/LLM backend; fed into deterministic ranking as hints only."""

    likely_visible_text: str | None = None
    likely_semantic_label: str | None = None
    likely_region: BoundingBoxHint | None = None
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    rationale: str | None = Field(default=None, description="Short model explanation for audit.")
