"""Deterministic runtime blocker registry helpers."""

from __future__ import annotations

from maestro_ai_agent.domain.dialog_signals import collect_allowlist_dismiss_nodes
from maestro_ai_agent.domain.runtime_blockers import (
    DeveloperModeAllowlistPattern,
    KeywordAllowlistPattern,
    build_dismiss_action_from_allowlist_candidates,
)
from maestro_ai_agent.services.maestro.hierarchy_csv import parse_maestro_hierarchy_csv


def test_build_dismiss_prefers_id_when_single_distinct_resource_id() -> None:
    csv = (
        '1,0,"text=Allow; resource-id=com.app:id/a; class=Button",\n'
        '2,0,"text=Skip; resource-id=com.app:id/a; class=Button",\n'
    )
    h = parse_maestro_hierarchy_csv(csv)
    cands = collect_allowlist_dismiss_nodes(h)
    action = build_dismiss_action_from_allowlist_candidates(cands)
    assert action is not None
    assert action.selector_basis == "id"
    assert action.tap_id == "com.app:id/a"
    assert action.tap_text is None


def test_build_dismiss_text_fallback_when_two_distinct_ids() -> None:
    csv = (
        '1,0,"text=Allow; resource-id=com.app:id/a; class=Button",\n'
        '2,0,"text=Skip; resource-id=com.app:id/b; class=Button",\n'
    )
    h = parse_maestro_hierarchy_csv(csv)
    cands = collect_allowlist_dismiss_nodes(h)
    action = build_dismiss_action_from_allowlist_candidates(cands)
    assert action is not None
    assert action.selector_basis == "text"
    assert "ambiguous_multiple_ids" in action.choice_reason
    assert action.tap_text in ("Allow", "Skip")


def test_developer_mode_pattern_detects_with_next_button() -> None:
    csv = (
        '1,0,"text=Developer Mode; class=android.widget.TextView",\n'
        '2,0,"text=Next; class=android.widget.Button",\n'
    )
    h = parse_maestro_hierarchy_csv(csv)
    p = DeveloperModeAllowlistPattern()
    assert p.detect(h) is True
    act = p.resolve_dismiss(h)
    assert act is not None
    assert act.tap_text == "Next"


def test_keyword_pattern_skips_when_developer_mode_present() -> None:
    csv = (
        '1,0,"text=Developer Mode; class=android.widget.TextView",\n'
        '2,0,"text=tracking enabled; class=android.widget.TextView",\n'
        '3,0,"text=Allow; class=android.widget.Button",\n'
    )
    h = parse_maestro_hierarchy_csv(csv)
    kp = KeywordAllowlistPattern(pattern_id="tracking_prompt", keywords=("tracking",))
    assert kp.detect(h) is False
