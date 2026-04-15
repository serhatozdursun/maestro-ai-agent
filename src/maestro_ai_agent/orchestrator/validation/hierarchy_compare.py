"""Deterministic hierarchy fingerprints for before/after comparison (no transport)."""

from __future__ import annotations

from maestro_ai_agent.domain.enums import SelectorType
from maestro_ai_agent.domain.hierarchy import HierarchySnapshot, effective_visible_text

HierarchyFingerprint = tuple[int, frozenset[tuple[str | None, str]]]


def _norm_text(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(value.lower().split())


def _is_volatile_ui_text(text: str) -> bool:
    """
    Ignore high-churn status-bar style tokens in before/after fingerprints.

    These values often change without any user action (clock minute tick, network/battery
    labels) and can create false "changed" signals for tap validation.
    """
    if not text:
        return False
    if len(text) == 5 and text[2] == ":" and text[:2].isdigit() and text[3:].isdigit():
        return True
    if "%" in text and "battery" in text:
        return True
    if "wi-fi bars" in text or "no signal" in text or "not charging" in text:
        return True
    return False


def visible_text_tokens(hierarchy: HierarchySnapshot) -> frozenset[str]:
    """Non-empty normalized visible text values from hierarchy nodes."""
    out: set[str] = set()
    for node in hierarchy.nodes:
        t = _norm_text(effective_visible_text(node))
        if t:
            out.add(t)
    return frozenset(out)


def hierarchy_fingerprint(hierarchy: HierarchySnapshot) -> HierarchyFingerprint:
    """
    Cheap structural fingerprint: node count + multiset of (resource_id, text).

    Intended only for conservative same-screen vs changed-screen checks.
    """
    pairs: set[tuple[str | None, str]] = set()
    for node in hierarchy.nodes:
        txt = _norm_text(effective_visible_text(node))
        if _is_volatile_ui_text(txt):
            continue
        pairs.add((node.resource_id, txt))
    return (len(hierarchy.nodes), frozenset(pairs))


def combined_visible_text(hierarchy: HierarchySnapshot) -> str:
    """Single lowercase string of visible texts for substring checks (conservative)."""
    return " ".join(sorted(visible_text_tokens(hierarchy)))


def text_substring_present(hierarchy: HierarchySnapshot, needle: str) -> bool:
    """True if any node's visible text contains ``needle`` (case-insensitive)."""
    if not needle.strip():
        return False
    n = needle.lower().strip()
    hay = combined_visible_text(hierarchy)
    return n in hay


def resource_id_visible_in_hierarchy(hierarchy: HierarchySnapshot, resource_id: str) -> bool:
    """
    True when ``resource_id`` appears on a node ``resource_id`` field or in raw hierarchy CSV.

    Accepts a bare id token (no ``id:`` prefix). Matching is case-insensitive and substring
    based on ``raw_csv`` so partially qualified ids from ranking still match device rows.
    """
    rid = resource_id.strip().lower()
    if not rid:
        return False
    raw = (hierarchy.raw_csv or "").lower()
    if rid in raw:
        return True
    for node in hierarchy.nodes:
        nrid = (node.resource_id or "").strip().lower()
        if not nrid:
            continue
        if rid == nrid or rid in nrid or nrid in rid:
            return True
    return False


def ranked_selector_matches_hierarchy(
    hierarchy: HierarchySnapshot,
    *,
    selector_type: SelectorType,
    expression: str,
) -> bool:
    """Whether a ranked ``id:`` / ``text:`` style expression is reflected in the hierarchy."""
    expr = (expression or "").strip()
    if not expr:
        return False
    lowered = expr.lower()
    if lowered.startswith("id:"):
        inner = expr[3:].strip()
        return bool(inner) and resource_id_visible_in_hierarchy(hierarchy, inner)
    if lowered.startswith("text:"):
        inner = expr[5:].strip()
        return bool(inner) and text_substring_present(hierarchy, inner)
    if selector_type is SelectorType.ID:
        return resource_id_visible_in_hierarchy(hierarchy, expr)
    if selector_type in (SelectorType.TEXT, SelectorType.TEXT_WITH_STATE):
        return text_substring_present(hierarchy, expr)
    return False


def raw_csv_contains_literal(hierarchy: HierarchySnapshot, literal: str) -> bool:
    """
    True when ``literal`` appears in the raw Maestro CSV (case-insensitive).

    Used conservatively for input reflection when visible_text coalescing hides field values.
    """
    if not literal.strip():
        return False
    return literal.lower().strip() in (hierarchy.raw_csv or "").lower()


def raw_csv_suggests_input_literal(hierarchy: HierarchySnapshot, literal: str) -> bool:
    """
    True when ``literal`` appears on a CSV line that also hints at an input control.

    Avoids matching the literal on unrelated rows (e.g. a nearby label ``TextView``).
    """
    low = literal.lower().strip()
    if not low or not hierarchy.raw_csv:
        return False
    inputish = (
        "edittext",
        "textfield",
        "uitextfield",
        "textinput",
        "value=",
        "query=",
        "searchview",
    )
    for line in hierarchy.raw_csv.lower().splitlines():
        if low not in line:
            continue
        if any(token in line for token in inputish):
            return True
    return False


def _node_class_input_like(class_name: str | None) -> bool:
    if not class_name:
        return False
    lowered = class_name.lower()
    return any(
        token in lowered
        for token in (
            "edittext",
            "textfield",
            "uitextfield",
            "textinput",
            "autocompletetextview",
            "securefield",
            "searchview",
        )
    )


def input_literal_reflected_in_hierarchy(hierarchy: HierarchySnapshot, literal: str) -> bool:
    """
    True when the literal appears on an input-like control or in raw CSV (Maestro value/text).

    Avoids treating unrelated visible labels (e.g. a sibling ``TextView``) as proof of entry.
    """
    if raw_csv_suggests_input_literal(hierarchy, literal):
        return True
    low = literal.lower().strip()
    if not low:
        return False
    for node in hierarchy.nodes:
        if not _node_class_input_like(node.class_name):
            continue
        parts = [
            (effective_visible_text(node) or "").lower(),
            (node.text or "").lower(),
        ]
        if node.attributes:
            attrs = node.attributes
            parts.append(str(attrs.get("value", "")).lower())
            parts.append(str(attrs.get("query", "")).lower())
            parts.append(str(attrs.get("hint", "")).lower())
        blob = " ".join(parts)
        if low in blob:
            return True
    return False


def hierarchy_meaningfully_changed(before: HierarchySnapshot, after: HierarchySnapshot) -> bool:
    """True when fingerprint differs (any node/text/rid change)."""
    return hierarchy_fingerprint(before) != hierarchy_fingerprint(after)


def _selection_pairs(hierarchy: HierarchySnapshot) -> frozenset[tuple[str, str]] | None:
    """Per-node ``selected=`` values when present (Maestro/Android attribute blob)."""
    rows: set[tuple[str, str]] = set()
    for node in hierarchy.nodes:
        raw = node.attributes.get("selected") if node.attributes else None
        if raw is None:
            continue
        v = str(raw).strip().lower()
        if not v:
            continue
        rows.add((node.node_index, v))
    return frozenset(rows) if rows else None


def selected_state_changed(before: HierarchySnapshot, after: HierarchySnapshot) -> bool:
    """
    True when any node's ``selected`` attribute differs between snapshots.

    Used as post-tap evidence when fingerprints are otherwise unchanged.
    """
    b = _selection_pairs(before)
    a = _selection_pairs(after)
    if b is None and a is None:
        return False
    return b != a
