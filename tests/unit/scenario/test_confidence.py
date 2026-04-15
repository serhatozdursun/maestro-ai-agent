"""Parse confidence scoring."""

from maestro_ai_agent.scenario.canonical_model import CanonicalScenario, CanonicalStep
from maestro_ai_agent.scenario.classifier import InputStructure, LanguageHint, ScenarioInputProfile
from maestro_ai_agent.scenario.confidence import ConfidenceBand, evaluate_parse_confidence


def test_high_confidence_when_no_unknown_steps() -> None:
    steps = [
        CanonicalStep(action="tap", target="OK", value=None, index=0, source_text=None),
    ]
    scenario = CanonicalScenario(steps=steps)
    profile = ScenarioInputProfile(
        structure=InputStructure.PROSE,
        language_hint=LanguageHint.ENGLISH,
    )
    c = evaluate_parse_confidence(scenario, profile)
    assert c.band is ConfidenceBand.HIGH
    assert c.score >= 0.72


def test_low_confidence_all_unknown() -> None:
    steps = [
        CanonicalStep(action="unknown", target="x", value=None, index=0, source_text=None),
        CanonicalStep(action="unknown", target="y", value=None, index=1, source_text=None),
    ]
    scenario = CanonicalScenario(steps=steps)
    profile = ScenarioInputProfile(
        structure=InputStructure.PROSE,
        language_hint=LanguageHint.ENGLISH,
    )
    c = evaluate_parse_confidence(scenario, profile)
    assert c.band is ConfidenceBand.LOW
    assert c.score < 0.45


def test_empty_steps_is_low() -> None:
    scenario = CanonicalScenario(steps=[])
    profile = ScenarioInputProfile(
        structure=InputStructure.GHERKIN,
        language_hint=LanguageHint.ENGLISH,
    )
    c = evaluate_parse_confidence(scenario, profile)
    assert c.score == 0.0
    assert c.band is ConfidenceBand.LOW
