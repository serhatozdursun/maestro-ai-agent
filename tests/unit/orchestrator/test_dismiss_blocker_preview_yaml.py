"""Maestro preview YAML for resolved dismiss selectors."""

from __future__ import annotations

from maestro_ai_agent.orchestrator.execution.inline_flow_yaml import (
    build_dismiss_blocker_preview_flow_yaml,
)


def test_preview_flow_yaml_uses_resolved_id() -> None:
    yml = build_dismiss_blocker_preview_flow_yaml(
        app_id="com.example.app",
        tap_selector_basis="id",
        dismiss_tap_text=None,
        dismiss_tap_id="com.example.app:id/allow_btn",
    )
    assert "appId: com.example.app" in yml
    assert "com.example.app:id/allow_btn" in yml
    assert "optional: true" in yml
    assert "Continue" not in yml


def test_preview_flow_yaml_uses_resolved_text() -> None:
    yml = build_dismiss_blocker_preview_flow_yaml(
        app_id="com.example.app",
        tap_selector_basis="text",
        dismiss_tap_text="Not now",
        dismiss_tap_id=None,
    )
    assert "Not now" in yml
    assert "optional: true" in yml


def test_preview_empty_when_no_basis() -> None:
    yml = build_dismiss_blocker_preview_flow_yaml(
        app_id="com.example.app",
        tap_selector_basis=None,
        dismiss_tap_text=None,
        dismiss_tap_id=None,
    )
    assert "no resolved selector" in yml
