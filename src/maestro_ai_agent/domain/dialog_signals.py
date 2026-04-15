"""Hierarchy predicates for known in-app UI patterns (domain-only, no IO)."""

from __future__ import annotations

from maestro_ai_agent.domain.hierarchy import (
    HierarchyNode,
    HierarchySnapshot,
    effective_visible_text,
)

# Visible labels (case-insensitive exact match on node text) allowed as dismiss taps
# for explicit runtime blocker patterns—not a global “tap anywhere” rule.
DISMISS_LABEL_ALLOWLIST_CI: frozenset[str] = frozenset(
    {
        "continue",
        "next",
        "skip",
        "allow",
        "not now",
        "maybe later",
    },
)


def _norm_text(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(value.lower().split())


def text_substring_present(hierarchy: HierarchySnapshot, needle: str) -> bool:
    """True if any visible text contains ``needle`` (case-insensitive)."""
    if not needle.strip():
        return False
    n = needle.lower().strip()
    parts: list[str] = []
    for node in hierarchy.nodes:
        t = _norm_text(effective_visible_text(node))
        if t:
            parts.append(t)
    hay = " ".join(sorted(parts))
    return n in hay


def has_exact_continue_label(hierarchy: HierarchySnapshot) -> bool:
    """True if some node shows a standalone ``Continue`` label (button)."""
    for node in hierarchy.nodes:
        label = (effective_visible_text(node) or "").strip().lower()
        if label == "continue":
            return True
    return False


def collect_allowlist_dismiss_nodes(hierarchy: HierarchySnapshot) -> list[HierarchyNode]:
    """
    Nodes whose visible label is an exact case-insensitive match to the dismiss allowlist.

    Sorted by ``node_index`` for deterministic iteration.
    """
    out: list[HierarchyNode] = []
    for node in hierarchy.nodes:
        label = (effective_visible_text(node) or "").strip().lower()
        if label in DISMISS_LABEL_ALLOWLIST_CI:
            out.append(node)
    out.sort(key=lambda n: n.node_index)
    return out


def developer_mode_continue_dialog_visible(hierarchy: HierarchySnapshot) -> bool:
    """
    True when developer-mode copy is visible **and** an allowlisted dismiss control exists.

    Used after taps to detect the same class of blocking sheet as preflight dismissal
    (Continue, Next, Skip, etc.—see ``DISMISS_LABEL_ALLOWLIST_CI``).
    """
    if not text_substring_present(hierarchy, "developer mode"):
        return False
    return bool(collect_allowlist_dismiss_nodes(hierarchy))
