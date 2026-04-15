"""Selector hypotheses prior to Maestro execution."""

from __future__ import annotations

from pydantic import BaseModel, Field

from maestro_ai_agent.domain.confidence import ConfidenceScore
from maestro_ai_agent.domain.enums import SelectorType


class SelectorCandidate(BaseModel):
    """One ranked selector hypothesis (not yet executed on device)."""

    candidate_id: str = Field(min_length=1, description="Unique id within an intent.")
    selector_type: SelectorType
    expression: str | None = Field(
        default=None,
        description="Maestro-oriented selector string when known; None until hierarchy binds it.",
    )
    rationale: str = Field(min_length=1, description="Why this candidate was proposed.")
    rank: int = Field(ge=0, description="0 = strongest; larger numbers are weaker fallbacks.")
    confidence: ConfidenceScore
