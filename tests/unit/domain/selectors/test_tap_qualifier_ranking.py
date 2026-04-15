"""Tap qualifier parsing, geometry hints, and ranking integration (deterministic)."""

from uuid import uuid4

from maestro_ai_agent.domain.enums import ActionType, SelectorType
from maestro_ai_agent.domain.hierarchy import HierarchyNode, HierarchySnapshot
from maestro_ai_agent.domain.intent import StepIntent
from maestro_ai_agent.domain.selectors.candidate_geometry import (
    NodeBounds,
    coarse_region_hint,
    hierarchy_screen_bbox,
    infer_node_structural_hints,
)
from maestro_ai_agent.domain.selectors.pipeline import plan_selector_ranking
from maestro_ai_agent.domain.selectors.tap_qualifier import (
    find_tap_qualifier_in_text,
    normalize_qualifier_phrase,
)
from maestro_ai_agent.domain.selectors.tap_resolution import (
    AmbiguityStrategy,
    TapResolutionSettings,
)
from maestro_ai_agent.domain.selectors.target_hints import TargetHints


def test_normalize_qualifier_synonyms() -> None:
    assert normalize_qualifier_phrase("the tab bar") == "tab_bar"
    assert normalize_qualifier_phrase("bottom navigation") == "tab_bar"
    assert normalize_qualifier_phrase("navigation bar") == "header"
    assert normalize_qualifier_phrase("the modal") == "modal"
    assert normalize_qualifier_phrase("search box") == "search_field"


def test_find_tap_qualifier_embedded_gherkin_style() -> None:
    tq = find_tap_qualifier_in_text("When the user taps 'Shop' on the tab bar")
    assert tq is not None
    assert tq.label == "Shop"
    assert tq.container_hint == "tab_bar"
    assert tq.preposition == "on"


def test_coarse_region_hint_grid() -> None:
    screen = NodeBounds(left=0.0, top=0.0, right=100.0, bottom=100.0)
    assert coarse_region_hint(10.0, 10.0, screen).startswith("top")
    assert "bottom" in coarse_region_hint(50.0, 95.0, screen)


def test_hierarchy_screen_bbox_unions_nodes() -> None:
    h = HierarchySnapshot(
        nodes=[
            HierarchyNode(
                node_index="a",
                depth=0,
                parent_index=None,
                bounds="[0,0][10,10]",
            ),
            HierarchyNode(
                node_index="b",
                depth=0,
                parent_index=None,
                bounds="[20,20][40,50]",
            ),
        ],
        raw_csv="fixture",
    )
    box = hierarchy_screen_bbox(h)
    assert box is not None
    assert box.left == 0.0 and box.right == 40.0


def _shop_duplicate_hierarchy() -> HierarchySnapshot:
    """Two visible ``Shop`` labels: bottom nav strip vs horizontal promo strip."""
    return HierarchySnapshot(
        nodes=[
            HierarchyNode(
                node_index="nav",
                depth=0,
                parent_index=None,
                class_name="com.google.android.material.bottomnavigation.BottomNavigationView",
                bounds="[0,1700][1080,1920]",
            ),
            HierarchyNode(
                node_index="tab_shop",
                depth=1,
                parent_index="nav",
                class_name="android.widget.TextView",
                visible_text="Shop",
                bounds="[400,1750][500,1880]",
            ),
            HierarchyNode(
                node_index="promo_row",
                depth=0,
                parent_index=None,
                class_name="android.widget.HorizontalScrollView",
                bounds="[0,80][1080,260]",
            ),
            HierarchyNode(
                node_index="banner_shop",
                depth=1,
                parent_index="promo_row",
                class_name="android.widget.TextView",
                visible_text="Shop",
                bounds="[40,120][200,200]",
            ),
        ],
        raw_csv="fixture-shop-dup",
    )


def test_plain_tap_shop_prefers_bottom_nav_over_banner_row() -> None:
    hierarchy = _shop_duplicate_hierarchy()
    intent = StepIntent(
        intent_id=uuid4(),
        scenario_step_index=0,
        primary_action=ActionType.TAP,
        goal_summary="Tap Shop",
        raw_step_text="Tap 'Shop'",
        validation_goals=[],
    )
    ranking = plan_selector_ranking(hierarchy, intent)
    assert ranking.primary is not None
    assert ranking.ordered[0].candidate.selector_type is SelectorType.TEXT
    assert ranking.ordered[0].candidate.expression is not None
    assert ranking.ordered[0].structural_kind == "tab_like"
    assert ranking.ordered[1].structural_kind == "banner_like"
    assert ranking.ordered[0].score > ranking.ordered[1].score


def test_tab_bar_qualifier_boosts_nav_shop() -> None:
    hierarchy = _shop_duplicate_hierarchy()
    intent = StepIntent(
        intent_id=uuid4(),
        scenario_step_index=0,
        primary_action=ActionType.TAP,
        goal_summary="Tap Shop tab",
        raw_step_text="Tap 'Shop' on the tab bar",
        validation_goals=[],
    )
    hints = TargetHints(desired_texts=["Shop"], container_hint="tab_bar")
    ranking = plan_selector_ranking(hierarchy, intent, hints=hints)
    top = ranking.ordered[0]
    assert top.structural_kind == "tab_like"
    assert top.score > ranking.ordered[1].score


def test_suggest_strategy_primary_iff_not_resolved() -> None:
    """Invariant: suggest/fail clear ``primary`` exactly for non-resolved tap rankings."""
    hierarchy = _shop_duplicate_hierarchy()
    intent = StepIntent(
        intent_id=uuid4(),
        scenario_step_index=0,
        primary_action=ActionType.TAP,
        goal_summary="Tap Shop",
        raw_step_text="Tap 'Shop'",
        validation_goals=[],
    )
    tr = TapResolutionSettings(ambiguity_strategy=AmbiguityStrategy.SUGGEST)
    ranking = plan_selector_ranking(hierarchy, intent, tap_resolution=tr)
    assert (ranking.primary is None) == (
        ranking.resolution_status in ("ambiguous_candidates", "not_found")
    )


def test_infer_node_structural_hints_banner_under_horizontal_scroll() -> None:
    h = _shop_duplicate_hierarchy()
    screen = hierarchy_screen_bbox(h)
    banner = next(n for n in h.nodes if n.node_index == "banner_shop")
    st = infer_node_structural_hints(banner, hierarchy=h, screen=screen)
    assert st.is_banner_like is True
