"""Bounded Maestro ``run_flow`` YAML for grammar steps (no arbitrary user YAML)."""

from __future__ import annotations

from maestro_ai_agent.app.maestro_draft_preview import (
    build_blocking_popup_optional_tap_yaml_lines,
    yaml_quote_scalar,
)
from maestro_ai_agent.domain.enums import SelectorType


def _header(app_id: str) -> str:
    return f"appId: {app_id}\n---\n"


def build_press_key_flow_yaml(*, app_id: str, key: str) -> str:
    """Single ``pressKey`` command (Maestro key names, e.g. ``enter``)."""
    k = (key or "").strip().lower()
    return _header(app_id) + f"- pressKey: {yaml_quote_scalar(k)}\n"


def build_swipe_flow_yaml(*, app_id: str, direction: str) -> str:
    """One directional swipe (``DOWN`` / ``UP`` / ``LEFT`` / ``RIGHT``)."""
    d = (direction or "down").strip().upper()
    if d not in {"DOWN", "UP", "LEFT", "RIGHT"}:
        d = "DOWN"
    return _header(app_id) + f"- swipe:\n    direction: {d}\n"


def build_swipe_from_text_flow_yaml(*, app_id: str, element_text: str, direction: str) -> str:
    """
    Directional swipe starting at the center of an element located by visible ``text``.

    Maestro-native ``swipe`` with ``from:`` selector (see Maestro swipe reference).
    """
    d = (direction or "down").strip().upper()
    if d not in {"DOWN", "UP", "LEFT", "RIGHT"}:
        d = "DOWN"
    t = yaml_quote_scalar((element_text or "").strip())
    return (
        _header(app_id)
        + "- swipe:\n"
        + "    from:\n"
        + f"      text: {t}\n"
        + f"    direction: {d}\n"
    )


def build_swipe_from_ranked_candidate_flow_yaml(
    *,
    app_id: str,
    direction: str,
    selector_type: SelectorType,
    expression: str,
) -> str | None:
    """
    Directional swipe anchored to a hierarchy-ranked selector (``id`` or ``text`` family).

    Uses the same ``id:`` / ``text:`` conventions as ``tapOn`` mapping (``maestro_draft_preview``).
    Returns ``None`` when the selector type cannot be expressed as a simple Maestro ``from`` map.
    """
    if selector_type not in (
        SelectorType.ID,
        SelectorType.TEXT,
        SelectorType.TEXT_WITH_STATE,
    ):
        return None

    d = (direction or "down").strip().upper()
    if d not in {"DOWN", "UP", "LEFT", "RIGHT"}:
        d = "DOWN"

    expr = (expression or "").strip()
    if not expr:
        return None

    lowered = expr.lower()
    from_lines: tuple[str, str]

    if lowered.startswith("id:"):
        inner = expr[3:].strip()
        if not inner:
            return None
        from_lines = ("    from:", f"      id: {yaml_quote_scalar(inner)}")
    elif lowered.startswith("text:"):
        inner = expr[5:].strip()
        if not inner:
            return None
        from_lines = ("    from:", f"      text: {yaml_quote_scalar(inner)}")
    elif selector_type is SelectorType.ID:
        from_lines = ("    from:", f"      id: {yaml_quote_scalar(expr)}")
    elif selector_type in (SelectorType.TEXT, SelectorType.TEXT_WITH_STATE):
        from_lines = ("    from:", f"      text: {yaml_quote_scalar(expr)}")
    else:
        return None

    return (
        _header(app_id)
        + "- swipe:\n"
        + from_lines[0]
        + "\n"
        + from_lines[1]
        + "\n"
        + f"    direction: {d}\n"
    )


def build_scroll_until_visible_flow_yaml(*, app_id: str, element_text: str) -> str:
    """``scrollUntilVisible`` with a text selector (bounded grammar subset)."""
    t = (element_text or "").strip()
    return (
        _header(app_id)
        + "- scrollUntilVisible:\n"
        + f"    element: {yaml_quote_scalar(t)}\n"
        + "    direction: DOWN\n"
        + "    timeout: 20000\n"
    )


def build_scroll_until_visible_ranked_flow_yaml(
    *,
    app_id: str,
    selector_type: SelectorType,
    expression: str,
) -> str | None:
    """
    ``scrollUntilVisible`` with ``element`` as an id/text map (Maestro selector object).

    See Maestro docs: ``element`` may be a string or object with ``id`` / ``text`` keys.
    """
    if selector_type not in (
        SelectorType.ID,
        SelectorType.TEXT,
        SelectorType.TEXT_WITH_STATE,
    ):
        return None

    expr = (expression or "").strip()
    if not expr:
        return None

    lowered = expr.lower()
    element_lines: tuple[str, str]

    if lowered.startswith("id:"):
        inner = expr[3:].strip()
        if not inner:
            return None
        element_lines = ("    element:", f"      id: {yaml_quote_scalar(inner)}")
    elif lowered.startswith("text:"):
        inner = expr[5:].strip()
        if not inner:
            return None
        element_lines = ("    element:", f"      text: {yaml_quote_scalar(inner)}")
    elif selector_type is SelectorType.ID:
        element_lines = ("    element:", f"      id: {yaml_quote_scalar(expr)}")
    elif selector_type in (SelectorType.TEXT, SelectorType.TEXT_WITH_STATE):
        element_lines = ("    element:", f"      text: {yaml_quote_scalar(expr)}")
    else:
        return None

    return (
        _header(app_id)
        + "- scrollUntilVisible:\n"
        + element_lines[0]
        + "\n"
        + element_lines[1]
        + "\n"
        + "    direction: DOWN\n"
        + "    timeout: 20000\n"
    )


def build_dismiss_blocker_preview_flow_yaml(
    *,
    app_id: str,
    tap_selector_basis: str | None,
    dismiss_tap_text: str | None,
    dismiss_tap_id: str | None,
) -> str:
    """
    Single optional ``tapOn`` from **resolved** hierarchy dismiss data (Maestro draft).

    Used when a verified preflight or step outcome exposes ``tap_selector_basis`` plus
    text/id—never a blind global Continue/OK list.
    """
    basis = (tap_selector_basis or "").strip().lower()
    has_text = basis == "text" and (dismiss_tap_text or "").strip()
    has_id = basis == "id" and (dismiss_tap_id or "").strip()
    lines = build_blocking_popup_optional_tap_yaml_lines(
        handled=bool(has_text or has_id),
        tap_selector_basis=tap_selector_basis,
        dismiss_tap_text=dismiss_tap_text,
        dismiss_tap_id=dismiss_tap_id,
    )
    if not lines:
        return _header(app_id) + "# dismiss_blocker: no resolved selector for preview\n"
    return _header(app_id) + "\n".join(lines) + "\n"
