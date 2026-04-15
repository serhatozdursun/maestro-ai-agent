"""Input classifier (structure + language hint)."""

from maestro_ai_agent.scenario.classifier import (
    InputStructure,
    LanguageHint,
    classify_scenario_text,
)


def test_classifies_gherkin_with_scenario_line() -> None:
    text = """
Scenario: Cart
Given the user is logged in
When the user taps "Shop"
Then the user sees "Cart"
"""
    p = classify_scenario_text(text)
    assert p.structure is InputStructure.GHERKIN
    assert p.language_hint in (LanguageHint.ENGLISH, LanguageHint.MIXED_TR_EN)


def test_classifies_step_list_with_markers() -> None:
    text = """1. Tap "A"
2. Tap "B"
"""
    p = classify_scenario_text(text)
    assert p.structure is InputStructure.STEP_LIST


def test_classifies_turkish_shopping_lines_as_prose_or_list() -> None:
    text = """login ol
search'e git
shoe ara
"""
    p = classify_scenario_text(text)
    assert p.structure is InputStructure.PROSE
    assert p.language_hint in (LanguageHint.TURKISH, LanguageHint.MIXED_TR_EN)


def test_empty_text_unknown_language() -> None:
    p = classify_scenario_text("   \n  ")
    assert p.structure is InputStructure.PROSE
    assert p.language_hint is LanguageHint.UNKNOWN
