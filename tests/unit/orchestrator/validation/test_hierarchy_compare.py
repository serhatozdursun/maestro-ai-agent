"""Tests for hierarchy fingerprint helpers used in post-action validation."""

from __future__ import annotations

from maestro_ai_agent.domain.hierarchy import HierarchyNode, HierarchySnapshot
from maestro_ai_agent.orchestrator.validation.hierarchy_compare import (
    hierarchy_meaningfully_changed,
    input_literal_reflected_in_hierarchy,
    selected_state_changed,
)


def _h(*nodes: HierarchyNode) -> HierarchySnapshot:
    return HierarchySnapshot(nodes=list(nodes), raw_csv="fixture")


def test_selected_state_changed_false_when_no_selected_attr() -> None:
    n = HierarchyNode(node_index="1", depth=0, parent_index=None, text="A", class_name="tv")
    h = _h(n)
    assert selected_state_changed(h, h) is False


def test_input_literal_reflected_when_searchview_query_attribute_matches() -> None:
    snap = _h(
        HierarchyNode(
            node_index="1",
            depth=0,
            parent_index=None,
            text="",
            class_name="android.widget.SearchView",
            attributes={"query": "shoe"},
        ),
    )
    assert input_literal_reflected_in_hierarchy(snap, "shoe") is True


def test_input_literal_reflected_via_raw_csv_query_equals() -> None:
    snap = HierarchySnapshot(
        nodes=[],
        raw_csv='1,0,"query=shoe; class=android.widget.SearchView",\n',
    )
    assert input_literal_reflected_in_hierarchy(snap, "shoe") is True


def test_selected_state_changed_true_when_selected_flips() -> None:
    before = _h(
        HierarchyNode(
            node_index="1",
            depth=0,
            parent_index=None,
            text="Tab",
            class_name="tv",
            attributes={"selected": "false"},
        ),
    )
    after = _h(
        HierarchyNode(
            node_index="1",
            depth=0,
            parent_index=None,
            text="Tab",
            class_name="tv",
            attributes={"selected": "true"},
        ),
    )
    assert selected_state_changed(before, after) is True


def test_hierarchy_meaningfully_changed_ignores_status_bar_clock_tick() -> None:
    before = _h(
        HierarchyNode(node_index="1", depth=0, parent_index=None, text="13:24", class_name="tv"),
        HierarchyNode(node_index="2", depth=0, parent_index=None, text="Cart", class_name="tv"),
    )
    after = _h(
        HierarchyNode(node_index="1", depth=0, parent_index=None, text="13:25", class_name="tv"),
        HierarchyNode(node_index="2", depth=0, parent_index=None, text="Cart", class_name="tv"),
    )
    assert hierarchy_meaningfully_changed(before, after) is False
