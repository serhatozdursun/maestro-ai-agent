"""Structured, auditable reasons for selector ranking outcomes."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class SelectorReasonCode(StrEnum):
    """Machine-readable reason codes (stable for logs and future LLM augmentation)."""

    UNIQUE_ID_MATCH = "unique_id_match"
    EXACT_VISIBLE_TEXT_MATCH = "exact_visible_text_match"
    KEYWORD_SEMANTIC_MATCH = "keyword_semantic_match"
    INPUT_LIKE_CONTROL = "input_like_control"
    INPUT_NEAR_EXPECTED_LABEL = "input_near_expected_label"
    AMBIGUITY_REDUCED_BY_PARENT = "ambiguity_reduced_by_parent_context"
    FALLBACK_CANDIDATE_ONLY = "fallback_candidate_only"
    POINT_LAST_RESORT = "point_last_resort"


class SelectorExplanation(BaseModel):
    """Human-readable summary plus structured reason codes."""

    codes: list[SelectorReasonCode] = Field(default_factory=list)
    summary: str = Field(
        min_length=1,
        description="Single-line explanation suitable for decision logs.",
    )
