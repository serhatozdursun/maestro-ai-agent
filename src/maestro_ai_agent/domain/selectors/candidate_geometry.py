"""Deterministic geometry helpers for hierarchy nodes (coarse regions, no AI)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from maestro_ai_agent.domain.hierarchy import (
    HierarchyNode,
    HierarchySnapshot,
    effective_visible_text,
)

_BOUNDS_BRACKET = re.compile(
    r"\[\s*([0-9.+-]+)\s*,\s*([0-9.+-]+)\s*\]\s*\[\s*([0-9.+-]+)\s*,\s*([0-9.+-]+)\s*\]",
)


@dataclass(frozen=True)
class NodeBounds:
    left: float
    top: float
    right: float
    bottom: float

    @property
    def cx(self) -> float:
        return (self.left + self.right) / 2.0

    @property
    def cy(self) -> float:
        return (self.top + self.bottom) / 2.0


def parse_node_bounds(node: HierarchyNode) -> NodeBounds | None:
    """Parse Maestro-style ``bounds=[l,t][r,b]`` from ``bounds`` or attribute blob."""
    raw = (node.bounds or "").strip()
    if not raw:
        attrs = node.attributes or {}
        raw = (attrs.get("bounds") or "").strip()
    if not raw:
        return None
    m = _BOUNDS_BRACKET.search(raw)
    if not m:
        return None
    try:
        left = float(m.group(1))
        top = float(m.group(2))
        right = float(m.group(3))
        bottom = float(m.group(4))
    except ValueError:
        return None
    if right <= left or bottom <= top:
        return None
    return NodeBounds(left=left, top=top, right=right, bottom=bottom)


def hierarchy_screen_bbox(hierarchy: HierarchySnapshot) -> NodeBounds | None:
    """Union-ish screen box from all parseable node bounds (for normalizing centers)."""
    boxes = [b for n in hierarchy.nodes if (b := parse_node_bounds(n)) is not None]
    if not boxes:
        return None
    return NodeBounds(
        left=min(b.left for b in boxes),
        top=min(b.top for b in boxes),
        right=max(b.right for b in boxes),
        bottom=max(b.bottom for b in boxes),
    )


def coarse_region_hint(cx: float, cy: float, screen: NodeBounds) -> str:
    """
    Map a center into a 3x3 coarse grid relative to the parsed screen bbox.

    Falls back to vertical-only ``top`` / ``middle`` / ``bottom`` when width is tiny.
    """
    w = max(1.0, screen.right - screen.left)
    h = max(1.0, screen.bottom - screen.top)
    nx = (cx - screen.left) / w
    ny = (cy - screen.top) / h
    if w < 8.0:
        if ny < 0.33:
            return "top"
        if ny > 0.66:
            return "bottom"
        return "middle"
    col = "left" if nx < 0.33 else ("right" if nx > 0.66 else "center")
    row = "top" if ny < 0.33 else ("bottom" if ny > 0.66 else "middle")
    if row == "middle" and col == "center":
        return "middle-center"
    return f"{row}-{col}"


@dataclass(frozen=True)
class NodeStructuralHints:
    """Cheap hierarchy-only signals for contextual ranking."""

    is_tab_like: bool
    is_button_like: bool
    is_banner_like: bool
    is_header_like: bool
    is_modal_child: bool
    is_nav_container_child: bool
    is_list_row_like: bool
    region_hint: str | None


def infer_node_structural_hints(
    node: HierarchyNode,
    *,
    hierarchy: HierarchySnapshot,
    screen: NodeBounds | None,
) -> NodeStructuralHints:
    cls = (node.class_name or "").lower()
    text = effective_visible_text(node).lower()

    is_tab_like = any(
        x in cls
        for x in (
            "tablayout",
            "tabwidget",
            "bottomnavigationview",
            "uitabbar",
            "tabbar",
            "segmentedcontrol",
        )
    ) or ("tab" in cls and "textview" in cls)

    is_button_like = any(
        x in cls for x in ("button", "imagebutton", "uibutton", "materialbutton", "compoundbutton")
    )

    is_banner_like = any(
        x in cls for x in ("banner", "carousel", "viewpager", "horizontalscroll", "cardview")
    ) or ("promo" in text or "new in" in text or "hero" in cls)

    p0 = next((n for n in hierarchy.nodes if n.node_index == node.parent_index), None)
    if p0 is not None:
        pcls0 = (p0.class_name or "").lower()
        if any(
            x in pcls0
            for x in (
                "horizontalscrollview",
                "viewpager",
                "viewpager2",
                "carousel",
                "pager",
            )
        ):
            is_banner_like = True

    _headerish = (
        "toolbar",
        "actionbar",
        "appbarlayout",
        "navigationbar",
        "uinavigationbar",
    )
    is_header_like = any(x in cls for x in _headerish) or ("header" in cls)

    is_modal_child = False
    parent_idx = node.parent_index
    depth_guard = 0
    while parent_idx and depth_guard < 40:
        depth_guard += 1
        parent = next((n for n in hierarchy.nodes if n.node_index == parent_idx), None)
        if parent is None:
            break
        pcls = (parent.class_name or "").lower()
        if any(x in pcls for x in ("dialog", "alert", "popup", "modal", "sheet")):
            is_modal_child = True
            break
        parent_idx = parent.parent_index

    is_nav_container_child = False
    p2 = node.parent_index
    d2 = 0
    while p2 and d2 < 40:
        d2 += 1
        parent = next((n for n in hierarchy.nodes if n.node_index == p2), None)
        if parent is None:
            break
        pcls = (parent.class_name or "").lower()
        if any(
            x in pcls
            for x in (
                "bottomnavigationview",
                "tablayout",
                "tabwidget",
                "uitabbar",
                "navigationview",
            )
        ):
            is_nav_container_child = True
            break
        p2 = parent.parent_index

    is_list_row_like = False
    p3 = node.parent_index
    d3 = 0
    while p3 and d3 < 40:
        d3 += 1
        parent = next((n for n in hierarchy.nodes if n.node_index == p3), None)
        if parent is None:
            break
        pcls = (parent.class_name or "").lower()
        _list_parents = ("recyclerview", "listview", "lazyrow", "lazyvgrid", "tableview")
        if any(x in pcls for x in _list_parents):
            is_list_row_like = True
            break
        p3 = parent.parent_index

    region: str | None = None
    nb = parse_node_bounds(node)
    if nb is not None and screen is not None:
        region = coarse_region_hint(nb.cx, nb.cy, screen)
    elif nb is not None:
        region = "middle-center"

    return NodeStructuralHints(
        is_tab_like=is_tab_like,
        is_button_like=is_button_like,
        is_banner_like=is_banner_like,
        is_header_like=is_header_like,
        is_modal_child=is_modal_child,
        is_nav_container_child=is_nav_container_child,
        is_list_row_like=is_list_row_like,
        region_hint=region,
    )
