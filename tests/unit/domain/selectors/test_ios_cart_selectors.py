"""Selector generation for iOS-style hierarchy (accessibilityText + 5-column CSV)."""

from uuid import uuid4

from maestro_ai_agent.domain.enums import ActionType, SelectorType
from maestro_ai_agent.domain.intent import StepIntent
from maestro_ai_agent.domain.selectors.generator import generate_proposals
from maestro_ai_agent.services.maestro.hierarchy_csv import parse_maestro_hierarchy_csv

# Snippet from real device hierarchy CSV (tab bar: Home / Cart / …).
_KG_TAB_SNIPPET = """element_num,depth,bounds,attributes,parent_num
40,11,"[25,795][99,849]","accessibilityText=Home; enabled=true; selected=true",39
41,12,"[48,801][76,829]","resource-id=home; enabled=true",40
42,11,"[89,795][163,849]","accessibilityText=Cart; enabled=true",39
43,12,"[112,801][140,829]","resource-id=bag; enabled=true",42
"""


def _tap_intent(step: str) -> StepIntent:
    return StepIntent(
        intent_id=uuid4(),
        scenario_step_index=0,
        primary_action=ActionType.TAP,
        goal_summary="tap cart tab",
        raw_step_text=step,
        validation_goals=[],
    )


def test_cart_visible_text_and_text_and_id_proposals() -> None:
    hierarchy = parse_maestro_hierarchy_csv(_KG_TAB_SNIPPET)
    intent = _tap_intent("Tap 'Cart'")
    proposals = generate_proposals(hierarchy, intent)

    text_exprs = [p.expression for p in proposals if p.selector_type is SelectorType.TEXT]
    id_exprs = [p.expression for p in proposals if p.selector_type is SelectorType.ID]

    assert any("Cart" in ex for ex in text_exprs), text_exprs
    assert "id:bag" in id_exprs, id_exprs

    cart_node = next(n for n in hierarchy.nodes if n.node_index == "42")
    assert cart_node.visible_text == "Cart"


def test_tap_cart_does_not_yield_empty_proposals() -> None:
    hierarchy = parse_maestro_hierarchy_csv(_KG_TAB_SNIPPET)
    intent = _tap_intent("Tap Cart")
    proposals = generate_proposals(hierarchy, intent)
    assert proposals, "expected at least one selector candidate for Cart tab row"
