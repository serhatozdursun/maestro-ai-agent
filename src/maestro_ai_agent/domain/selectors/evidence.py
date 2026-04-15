"""Evidence signals supporting selector proposals."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class EvidenceKind(StrEnum):
    """Categories of deterministic evidence attached to a selector proposal."""

    RESOURCE_ID = "resource_id"
    VISIBLE_TEXT = "visible_text"
    CLASS_HINT = "class_hint"
    SEMANTIC_KEYWORD = "semantic_keyword"
    PARENT_CONTEXT = "parent_context"
    PROXIMITY_LABEL = "proximity_label"
    VALIDATION_GOAL_HINT = "validation_goal_hint"
    POINT_GEOMETRY = "point_geometry"


class SelectorEvidence(BaseModel):
    """One weighted piece of evidence backing a selector choice."""

    kind: EvidenceKind
    weight: float = Field(
        ge=0.0,
        le=1.0,
        description="Relative strength of this signal for ranking.",
    )
    detail: str = Field(
        min_length=1,
        description="Human-readable explanation tied to the hierarchy.",
    )
