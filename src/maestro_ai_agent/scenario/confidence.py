"""Parse confidence from a canonical scenario (numeric + discrete band)."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from maestro_ai_agent.scenario.canonical_model import CanonicalScenario
from maestro_ai_agent.scenario.classifier import InputStructure, ScenarioInputProfile


class ConfidenceBand(StrEnum):
    """Discrete band derived from a numeric parse score."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ParseConfidence(BaseModel):
    """How much we trust the deterministic (or AI-augmented) normalization."""

    score: float = Field(ge=0.0, le=1.0, description="1.0 = all steps look well classified.")
    band: ConfidenceBand
    reasons: list[str] = Field(default_factory=list)


def _band_for_score(score: float) -> ConfidenceBand:
    if score >= 0.72:
        return ConfidenceBand.HIGH
    if score >= 0.45:
        return ConfidenceBand.MEDIUM
    return ConfidenceBand.LOW


def evaluate_parse_confidence(
    scenario: CanonicalScenario,
    profile: ScenarioInputProfile,
) -> ParseConfidence:
    """
    Heuristic confidence: penalize ``unknown`` actions and reward structured Gherkin.

    Extendable: plug in parse log signals, classifier margin, etc.
    """
    reasons: list[str] = []
    if not scenario.steps:
        return ParseConfidence(
            score=0.0,
            band=ConfidenceBand.LOW,
            reasons=["No steps produced."],
        )

    unknown = sum(1 for s in scenario.steps if s.action == "unknown")
    unknown_ratio = unknown / len(scenario.steps)
    base = 1.0 - (unknown_ratio * 0.85)
    if profile.structure == InputStructure.GHERKIN:
        base = min(1.0, base + 0.08)
        reasons.append("Gherkin structure bonus.")
    if unknown:
        reasons.append(f"{unknown} step(s) marked unknown.")

    score = max(0.0, min(1.0, base))
    return ParseConfidence(score=score, band=_band_for_score(score), reasons=reasons)
