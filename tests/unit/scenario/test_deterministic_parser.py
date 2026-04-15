"""Deterministic canonical parsing."""

from maestro_ai_agent.scenario.classifier import (
    InputStructure,
    LanguageHint,
    ScenarioInputProfile,
    classify_scenario_text,
)
from maestro_ai_agent.scenario.deterministic_parser import parse_scenario_text


def test_turkish_shopping_example() -> None:
    text = """login ol
search'e git
shoe ara
ilk ürünü aç
cart'a ekle
"""
    c = parse_scenario_text(text)
    assert [s.action for s in c.steps] == [
        "login",
        "navigate",
        "search",
        "open_first_product",
        "add_to_cart",
    ]
    assert c.steps[1].target == "search"
    assert c.steps[2].target == "shoe"


def test_gherkin_add_shoe_scenario() -> None:
    text = """
Scenario: Add a Shoe to the Shopping Cart
Given the user is logged in
When the user searches for "shoe"
Then the user adds the product to the cart
"""
    profile = classify_scenario_text(text)
    assert profile.structure is InputStructure.GHERKIN
    c = parse_scenario_text(text, profile)
    assert c.title == "Add a Shoe to the Shopping Cart"
    assert [s.action for s in c.steps] == ["login", "search", "add_to_cart"]
    assert c.steps[1].target == "shoe"
    assert c.steps[2].target == "cart"


def test_english_numbered_step_list() -> None:
    text = """1. Tap "Sign in"
2. Input email
3. Tap "Continue"
"""
    c = parse_scenario_text(text)
    assert len(c.steps) == 3
    assert c.steps[0].action == "tap"
    assert c.steps[0].target == "Sign in"
    assert c.steps[1].action == "input"
    assert c.steps[2].action == "tap"


def test_assert_line() -> None:
    c = parse_scenario_text('Verify "Checkout" is visible')
    assert c.steps[0].action == "assert"
    assert c.steps[0].target == "Checkout"


def test_unknown_preserved() -> None:
    c = parse_scenario_text("do something utterly nonstandard xyz")
    assert c.steps[0].action == "unknown"
    assert c.steps[0].target is not None


def test_tap_with_contextual_qualifier_parses_container_hint() -> None:
    c = parse_scenario_text("Tap 'Shop' on the tab bar")
    assert len(c.steps) == 1
    assert c.steps[0].action == "tap"
    assert c.steps[0].target == "Shop"
    assert c.steps[0].target_container_hint == "tab_bar"
    assert c.steps[0].target_qualifier_phrase_raw == "the tab bar"
    assert c.steps[0].tap_qualifier_preposition == "on"


def test_tap_plain_without_qualifier_unchanged() -> None:
    c = parse_scenario_text("Tap 'Shop'")
    assert c.steps[0].action == "tap"
    assert c.steps[0].target == "Shop"
    assert c.steps[0].target_container_hint is None


def test_parse_respects_explicit_gherkin_profile_for_mixed_header() -> None:
    """If caller forces GHERKIN, parser uses Gherkin path even on odd headers."""
    text = 'When the user searches for "x"\nThen the user sees "y"\n'
    prof = ScenarioInputProfile(
        structure=InputStructure.GHERKIN,
        language_hint=LanguageHint.ENGLISH,
    )
    c = parse_scenario_text(text, prof)
    assert c.steps[0].action == "search"
    assert c.steps[1].action == "assert"
