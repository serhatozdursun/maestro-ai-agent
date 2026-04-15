"""Maestro-native tapOn YAML lines from internal selector type + expression."""

from __future__ import annotations

import pytest

from maestro_ai_agent.app.maestro_draft_preview import (
    build_blocking_popup_optional_tap_yaml_lines,
    build_minimal_input_text_flow_yaml,
    build_minimal_single_tap_flow_yaml,
    build_tap_on_yaml_lines,
)
from maestro_ai_agent.domain.enums import SelectorType


def test_text_selector_emits_shorthand_tap_on() -> None:
    lines = build_tap_on_yaml_lines(SelectorType.TEXT, "text:Cart")
    assert lines == ['- tapOn: "Cart"']


def test_id_selector_emits_tap_on_id_map() -> None:
    lines = build_tap_on_yaml_lines(SelectorType.ID, "id:bag")
    assert lines == ["- tapOn:", '    id: "bag"']


def test_point_selector_emits_tap_on_point_map() -> None:
    lines = build_tap_on_yaml_lines(SelectorType.POINT, "point:126,822")
    assert lines == ["- tapOn:", '    point: "126,822"']


def test_build_minimal_single_tap_flow_includes_app_id_header() -> None:
    y = build_minimal_single_tap_flow_yaml(
        app_id="com.example.app",
        selector_type=SelectorType.TEXT,
        expression="text:Continue",
    )
    lines = y.strip().split("\n")
    assert lines[0] == "appId: com.example.app"
    assert lines[1] == "---"
    assert "Continue" in y


def test_empty_expression_raises() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        build_tap_on_yaml_lines(SelectorType.TEXT, "")


def test_blocking_popup_optional_tap_yaml_text_basis() -> None:
    lines = build_blocking_popup_optional_tap_yaml_lines(
        handled=True,
        tap_selector_basis="text",
        dismiss_tap_text="Continue",
        dismiss_tap_id=None,
    )
    assert lines == [
        "- tapOn:",
        '    text: "Continue"',
        "    optional: true",
    ]


def test_blocking_popup_optional_tap_yaml_id_basis() -> None:
    lines = build_blocking_popup_optional_tap_yaml_lines(
        handled=True,
        tap_selector_basis="id",
        dismiss_tap_text=None,
        dismiss_tap_id="continue_button",
    )
    assert lines == [
        "- tapOn:",
        '    id: "continue_button"',
        "    optional: true",
    ]


def test_blocking_popup_optional_tap_yaml_not_emitted_when_not_handled() -> None:
    assert (
        build_blocking_popup_optional_tap_yaml_lines(
            handled=False,
            tap_selector_basis="text",
            dismiss_tap_text="Continue",
            dismiss_tap_id=None,
        )
        == []
    )


def test_build_minimal_input_text_flow_yaml() -> None:
    y = build_minimal_input_text_flow_yaml(app_id="com.example.app", text="shoe")
    lines = y.strip().split("\n")
    assert lines[0] == "appId: com.example.app"
    assert lines[1] == "---"
    assert "inputText" in lines[2]
    assert "shoe" in lines[2]
