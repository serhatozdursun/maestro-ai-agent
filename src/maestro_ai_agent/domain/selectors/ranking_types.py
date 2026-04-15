"""Results of deterministic selector ranking."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from maestro_ai_agent.domain.selector import SelectorCandidate
from maestro_ai_agent.domain.selectors.evidence import SelectorEvidence
from maestro_ai_agent.domain.selectors.explanation import SelectorExplanation

SelectorResolutionStatus = Literal["resolved", "ambiguous_candidates", "not_found"]


class RankedSelectorCandidate(BaseModel):
    """A selector candidate with deterministic score, evidence, and explanation."""

    candidate: SelectorCandidate
    score: float = Field(description="Higher is better (deterministic heuristic score).")
    evidence: list[SelectorEvidence] = Field(default_factory=list)
    explanation: SelectorExplanation
    region_hint: str | None = Field(
        default=None,
        description="Coarse on-screen region derived from parsed bounds when available.",
    )
    bounds: dict[str, float] | None = Field(
        default=None,
        description="Optional left/top/right/bottom from hierarchy bounds when parseable.",
    )
    structural_kind: str | None = Field(
        default=None,
        description="Deterministic structural label (e.g. tab_like, banner_like).",
    )
    preferred_for_qualifier: bool = Field(
        default=False,
        description="True when this candidate strongly matches an optional tap context hint.",
    )
    ranking_notes: list[str] = Field(
        default_factory=list,
        description="Extra deterministic notes (contextual hints, ambiguity drivers).",
    )


class SelectorFallbackGroup(BaseModel):
    """Optional grouping of alternates sharing a common fallback strategy."""

    label: str = Field(min_length=1)
    members: list[RankedSelectorCandidate] = Field(default_factory=list)


class SelectorRankingResult(BaseModel):
    """Ordered ranking output suitable for orchestrator consumption."""

    ordered: list[RankedSelectorCandidate] = Field(default_factory=list)
    primary: RankedSelectorCandidate | None = Field(
        default=None,
        description="Highest scoring candidate, if any.",
    )
    fallback_groups: list[SelectorFallbackGroup] = Field(
        default_factory=list,
        description="Optional grouped alternates (may be empty in early versions).",
    )
    resolution_status: SelectorResolutionStatus = Field(
        default="resolved",
        description="resolved | ambiguous_candidates | not_found (tap ambiguity policy aware).",
    )
    ambiguity_reason: str | None = Field(
        default=None,
        description="Why ranking is ambiguous or inconclusive (deterministic).",
    )
