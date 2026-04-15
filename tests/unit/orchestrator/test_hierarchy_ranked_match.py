"""Hierarchy helpers for ranked id/text matching (assert validation)."""

from __future__ import annotations

from maestro_ai_agent.domain.enums import SelectorType
from maestro_ai_agent.domain.hierarchy import HierarchyNode, HierarchySnapshot
from maestro_ai_agent.orchestrator.validation.hierarchy_compare import (
    ranked_selector_matches_hierarchy,
    resource_id_visible_in_hierarchy,
)


def test_resource_id_visible_matches_node_and_csv() -> None:
    snap = HierarchySnapshot(
        nodes=[
            HierarchyNode(
                node_index="0",
                depth=0,
                resource_id="com.app:id/banner_row",
            ),
        ],
        raw_csv="com.app:id/banner_row,",
    )
    assert resource_id_visible_in_hierarchy(snap, "banner_row")
    assert ranked_selector_matches_hierarchy(
        snap,
        selector_type=SelectorType.ID,
        expression="id:com.app:id/banner_row",
    )


def test_ranked_text_matches_visible_text() -> None:
    snap = HierarchySnapshot(
        nodes=[
            HierarchyNode(
                node_index="0",
                depth=0,
                visible_text="Hello World",
            ),
        ],
    )
    assert ranked_selector_matches_hierarchy(
        snap,
        selector_type=SelectorType.TEXT,
        expression="text:World",
    )
