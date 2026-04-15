"""End-to-end normalization: classify → deterministic parse → confidence → optional AI."""

from __future__ import annotations

from pydantic import BaseModel, Field

from maestro_ai_agent.scenario.ai_fallback_parser import AIFallbackParser
from maestro_ai_agent.scenario.canonical_model import CanonicalScenario
from maestro_ai_agent.scenario.classifier import ScenarioInputProfile, classify_scenario_text
from maestro_ai_agent.scenario.confidence import ParseConfidence, evaluate_parse_confidence
from maestro_ai_agent.scenario.deterministic_parser import parse_scenario_text


class NormalizationResult(BaseModel):
    """Outcome of :func:`normalize_scenario_text`."""

    canonical: CanonicalScenario
    profile: ScenarioInputProfile
    confidence: ParseConfidence
    used_ai_fallback: bool = False
    warnings: list[str] = Field(default_factory=list)


def normalize_scenario_text(
    text: str,
    *,
    enable_ai_fallback: bool = False,
    ai_fallback: AIFallbackParser | None = None,
    confidence_threshold: float = 0.45,
) -> NormalizationResult:
    """
    Run the scenario-understanding pipeline (no runtime / orchestrator).

    1. Classify input structure + language hint.
    2. Deterministic parse to :class:`CanonicalScenario`.
    3. Evaluate parse confidence.
    4. Optionally call ``ai_fallback`` **only** to refine canonical steps when
       confidence is below ``confidence_threshold``.
    """
    profile = classify_scenario_text(text)
    canonical = parse_scenario_text(text, profile)
    confidence = evaluate_parse_confidence(canonical, profile)
    warnings = list(canonical.warnings)

    used_ai = False
    backend = ai_fallback if enable_ai_fallback else None

    if enable_ai_fallback and backend is not None and confidence.score < confidence_threshold:
        reason = "; ".join(confidence.reasons) if confidence.reasons else "low_score"
        try:
            improved = backend.normalize_to_canonical(
                text=text,
                profile=profile,
                draft=canonical,
                confidence_reason=reason,
            )
        except Exception as exc:
            warnings.append(f"AI fallback failed: {exc!s}")
            improved = None
        if improved is not None:
            canonical = improved
            confidence = evaluate_parse_confidence(canonical, profile)
            used_ai = True
            warnings.append("AI fallback adjusted canonical steps.")

    warnings.extend(profile.notes)
    return NormalizationResult(
        canonical=canonical,
        profile=profile,
        confidence=confidence,
        used_ai_fallback=used_ai,
        warnings=warnings,
    )
