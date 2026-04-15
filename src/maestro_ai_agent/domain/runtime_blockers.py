"""
Deterministic runtime blocker patterns (hierarchy-only matching, no AI).

Used by preflight popup dismissal: detect → resolve dismiss tap from hierarchy →
verify cleared on a fresh hierarchy. Patterns are explicit and ordered; the first
detecting pattern wins.

**Invocation policy:** ``dismiss_known_blocking_popups_if_present`` is used from device
preflight and from the ``DISMISS_BLOCKER`` scenario execution path (same engine). No
automatic re-scan after other intents—keeps behavior bounded.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from maestro_ai_agent.domain.dialog_signals import (
    collect_allowlist_dismiss_nodes,
    text_substring_present,
)
from maestro_ai_agent.domain.enums import SelectorType
from maestro_ai_agent.domain.hierarchy import HierarchyNode, HierarchySnapshot


@dataclass(frozen=True)
class BlockerDismissAction:
    """Hierarchy-derived dismiss tap (Maestro ``tap_on`` text or id)."""

    tap_text: str | None
    tap_id: str | None
    selector_type: SelectorType
    expression: str
    selector_basis: str
    """``text`` or ``id`` for YAML / MCP basis."""

    choice_reason: str
    """Short deterministic audit string (e.g. why id was preferred)."""


class BlockerPattern(Protocol):
    """One explicit blocker: detect → resolve dismiss → verify post-dismiss."""

    pattern_id: str

    def detect(self, hierarchy: HierarchySnapshot) -> bool:
        """True when this blocker is considered present."""

    def resolve_dismiss(self, hierarchy: HierarchySnapshot) -> BlockerDismissAction | None:
        """Return a dismiss action from current hierarchy, or None if not safely resolvable."""

    def verify_cleared(self, hierarchy: HierarchySnapshot) -> bool:
        """True when this blocker condition no longer holds after a dismiss attempt."""


def _norm_rid(node: HierarchyNode) -> str | None:
    rid = (node.resource_id or "").strip()
    if rid:
        return rid
    alt = (node.attributes.get("resource-id") or node.attributes.get("resource_id") or "").strip()
    return alt or None


def build_dismiss_action_from_allowlist_candidates(
    candidates: list[HierarchyNode],
    *,
    choice_reason_prefix: str = "allowlist",
) -> BlockerDismissAction | None:
    """
    Pick one dismiss target deterministically from allowlist-labeled nodes.

    Preference: **id** only when there is **exactly one distinct** non-empty
    ``resource-id`` among candidates (stable choice). If several distinct ids
    appear, fall back to **text** on the smallest ``node_index`` to avoid an
    ambiguous id tap. If no ids, use **text** the same way.
    """
    if not candidates:
        return None

    distinct_ids = sorted(
        {rid for n in candidates if (rid := (_norm_rid(n) or "").strip())},
    )
    if len(distinct_ids) == 1:
        only = distinct_ids[0]
        nodes_rid = [n for n in candidates if (_norm_rid(n) or "").strip() == only]
        nodes_rid.sort(key=lambda n: n.node_index)
        node = nodes_rid[0]
        reason = f"{choice_reason_prefix}:prefer_id:{only}:node_index={node.node_index}"
        return BlockerDismissAction(
            tap_text=None,
            tap_id=only,
            selector_type=SelectorType.ID,
            expression=f"id:{only}",
            selector_basis="id",
            choice_reason=reason,
        )

    text_nodes: list[tuple[str, HierarchyNode]] = []
    for n in candidates:
        label = (n.visible_text or n.text or "").strip()
        if label:
            text_nodes.append((n.node_index, n))

    if not text_nodes:
        return None
    text_nodes.sort(key=lambda t: t[0])
    node = text_nodes[0][1]
    tap_text = (node.visible_text or node.text or "").strip()
    if not tap_text:
        return None
    suffix = ":prefer_text"
    if len(distinct_ids) > 1:
        suffix = ":ambiguous_multiple_ids:prefer_text"
    reason = f"{choice_reason_prefix}{suffix}:{tap_text!r}:node_index={node.node_index}"
    return BlockerDismissAction(
        tap_text=tap_text,
        tap_id=None,
        selector_type=SelectorType.TEXT,
        expression=f"text:{tap_text}",
        selector_basis="text",
        choice_reason=reason,
    )


@dataclass(frozen=True)
class DeveloperModeAllowlistPattern:
    """Developer-mode style copy + an allowlisted dismiss control (not global taps)."""

    pattern_id: str = "developer_mode_continue"

    def detect(self, hierarchy: HierarchySnapshot) -> bool:
        if not text_substring_present(hierarchy, "developer mode"):
            return False
        return bool(collect_allowlist_dismiss_nodes(hierarchy))

    def resolve_dismiss(self, hierarchy: HierarchySnapshot) -> BlockerDismissAction | None:
        cands = collect_allowlist_dismiss_nodes(hierarchy)
        return build_dismiss_action_from_allowlist_candidates(
            cands,
            choice_reason_prefix="developer_mode",
        )

    def verify_cleared(self, hierarchy: HierarchySnapshot) -> bool:
        return not self.detect(hierarchy)


@dataclass(frozen=True)
class KeywordAllowlistPattern:
    """
    At least one keyword substring in visible text **and** an allowlisted dismiss
    control. Scoped to explicit keyword sets—does not tap allowlist labels globally.
    """

    pattern_id: str
    keywords: tuple[str, ...]

    def detect(self, hierarchy: HierarchySnapshot) -> bool:
        if text_substring_present(hierarchy, "developer mode"):
            return False
        if not any(text_substring_present(hierarchy, k) for k in self.keywords):
            return False
        return bool(collect_allowlist_dismiss_nodes(hierarchy))

    def resolve_dismiss(self, hierarchy: HierarchySnapshot) -> BlockerDismissAction | None:
        cands = collect_allowlist_dismiss_nodes(hierarchy)
        return build_dismiss_action_from_allowlist_candidates(
            cands,
            choice_reason_prefix=self.pattern_id,
        )

    def verify_cleared(self, hierarchy: HierarchySnapshot) -> bool:
        return not self.detect(hierarchy)


def default_runtime_blocker_patterns() -> list[BlockerPattern]:
    """Ordered registry: first match wins."""
    return [
        DeveloperModeAllowlistPattern(),
        KeywordAllowlistPattern(
            pattern_id="tracking_prompt",
            keywords=("tracking", "analytics", "cookies"),
        ),
        KeywordAllowlistPattern(
            pattern_id="notification_prompt",
            keywords=("notification", "notifications"),
        ),
        KeywordAllowlistPattern(
            pattern_id="permission_prompt",
            keywords=("permission", "would like to"),
        ),
        KeywordAllowlistPattern(
            pattern_id="onboarding_prompt",
            keywords=("what's new", "update available", "welcome to"),
        ),
    ]
