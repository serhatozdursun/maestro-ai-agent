"""Scenario understanding: classify input, parse deterministically, optional AI normalize."""

from maestro_ai_agent.scenario.ai_fallback_parser import AIFallbackParser, NullAIFallbackParser
from maestro_ai_agent.scenario.canonical_model import CanonicalScenario, CanonicalStep
from maestro_ai_agent.scenario.classifier import (
    InputStructure,
    LanguageHint,
    ScenarioInputProfile,
    classify_scenario_text,
)
from maestro_ai_agent.scenario.confidence import ParseConfidence, evaluate_parse_confidence
from maestro_ai_agent.scenario.deterministic_parser import parse_scenario_text
from maestro_ai_agent.scenario.planning_adapter import (
    build_parsed_scenario_from_canonical,
    canonical_step_to_planner_line,
)
from maestro_ai_agent.scenario.scenario_normalizer import (
    NormalizationResult,
    normalize_scenario_text,
)

__all__ = [
    "AIFallbackParser",
    "CanonicalScenario",
    "CanonicalStep",
    "InputStructure",
    "LanguageHint",
    "NormalizationResult",
    "NullAIFallbackParser",
    "ParseConfidence",
    "ScenarioInputProfile",
    "build_parsed_scenario_from_canonical",
    "canonical_step_to_planner_line",
    "classify_scenario_text",
    "evaluate_parse_confidence",
    "normalize_scenario_text",
    "parse_scenario_text",
]
