"""
Map internal ranked selector expressions to Maestro-native ``tapOn`` YAML (draft preview).

Internal forms (``id:…``, ``text:…``, ``point:…``) are for logs and MCP mapping; Maestro
YAML uses shorthand text or structured maps per https://maestro.mobile.dev/ .
"""

from __future__ import annotations

from maestro_ai_agent.domain.enums import SelectorType


def yaml_quote_scalar(value: str) -> str:
    """Quote a scalar for a single-line Maestro YAML value (minimal escaping)."""
    if not value:
        return '""'
    if '"' not in value and "\n" not in value and ":" not in value:
        return f'"{value}"'
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def build_tap_on_yaml_lines(
    selector_type: SelectorType,
    expression: str | None,
) -> list[str]:
    """
    Build YAML lines for one ``tapOn`` step (list item + optional indented map).

    Does **not** include the ``appId`` header or ``---`` document marker.
    """
    expr = (expression or "").strip()
    if not expr:
        msg = "TAP step requires non-empty selector expression for YAML."
        raise ValueError(msg)

    lower = expr.lower()
    if lower.startswith("point:"):
        inner = expr[6:].strip()
        if not inner:
            msg = "Empty point value in point:… expression."
            raise ValueError(msg)
        return ["- tapOn:", f"    point: {yaml_quote_scalar(inner)}"]

    if lower.startswith("id:"):
        inner = expr[3:].strip()
        if not inner:
            msg = "Empty id value in id:… expression."
            raise ValueError(msg)
        return ["- tapOn:", f"    id: {yaml_quote_scalar(inner)}"]

    if lower.startswith("text:"):
        inner = expr[5:].strip()
        if not inner:
            msg = "Empty text value in text:… expression."
            raise ValueError(msg)
        return [f"- tapOn: {yaml_quote_scalar(inner)}"]

    if selector_type is SelectorType.ID:
        return ["- tapOn:", f"    id: {yaml_quote_scalar(expr)}"]

    if selector_type is SelectorType.POINT:
        return ["- tapOn:", f"    point: {yaml_quote_scalar(expr)}"]

    if selector_type in (
        SelectorType.TEXT,
        SelectorType.RELATIONAL,
        SelectorType.TEXT_WITH_STATE,
    ):
        return [f"- tapOn: {yaml_quote_scalar(expr)}"]

    msg = f"Unsupported selector_type for tap YAML: {selector_type!r}"
    raise ValueError(msg)


def build_minimal_input_text_flow_yaml(*, app_id: str, text: str) -> str:
    """
    Minimal Maestro document: ``appId``, ``---``, one ``inputText`` (for ``run_flow`` fallback).

    ``text`` is the literal string to enter (YAML-escaped).
    """
    aid = (app_id or "").strip()
    if not aid:
        msg = "app_id is required to build an inputText run_flow document."
        raise ValueError(msg)
    return (
        "\n".join(
            [
                f"appId: {aid}",
                "---",
                f"- inputText: {yaml_quote_scalar(text)}",
            ],
        )
        + "\n"
    )


def build_blocking_popup_optional_tap_yaml_lines(
    *,
    handled: bool,
    tap_selector_basis: str | None,
    dismiss_tap_text: str | None,
    dismiss_tap_id: str | None,
) -> list[str]:
    """
    Maestro-native optional structured ``tapOn`` for a **verified** preflight popup dismiss.

    Emitted only when ``handled`` is true and the basis matches a non-empty dismiss target
    (same ``text`` / ``id`` keys as MCP ``tap_on``). Returns an empty list otherwise.
    """
    if not handled:
        return []
    basis = (tap_selector_basis or "").strip().lower()
    if basis == "text":
        t = (dismiss_tap_text or "").strip()
        if not t:
            return []
        return [
            "- tapOn:",
            f"    text: {yaml_quote_scalar(t)}",
            "    optional: true",
        ]
    if basis == "id":
        i = (dismiss_tap_id or "").strip()
        if not i:
            return []
        return [
            "- tapOn:",
            f"    id: {yaml_quote_scalar(i)}",
            "    optional: true",
        ]
    return []


def build_minimal_single_tap_flow_yaml(
    *,
    app_id: str,
    selector_type: SelectorType,
    expression: str,
) -> str:
    """
    Minimal Maestro document: ``appId``, ``---``, one ``tapOn`` (for ``run_flow`` fallback).

    Matches Studio-style flows (e.g. ``tapOn: Continue`` for text, structured maps for id/point).
    """
    aid = (app_id or "").strip()
    if not aid:
        msg = "app_id is required to build a tap run_flow document."
        raise ValueError(msg)
    body = build_tap_on_yaml_lines(selector_type, expression)
    return "\n".join([f"appId: {aid}", "---", *body]) + "\n"
