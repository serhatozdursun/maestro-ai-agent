"""
MCP-oriented Maestro adapter.

Maps high-level operations onto Maestro MCP tool names documented at
https://docs.maestro.dev/mcp . This module does **not** implement JSON-RPC or stdio
transport; it depends on :class:`MaestroToolTransport` for that boundary.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from maestro_ai_agent.services.maestro.device_payload import parse_device_list_text
from maestro_ai_agent.services.maestro.models import (
    ActionResult,
    DeviceInfo,
    ProviderCapabilities,
    ScreenshotArtifact,
)
from maestro_ai_agent.services.maestro.ports import MaestroToolTransport
from maestro_ai_agent.services.maestro.transport_types import (
    MaestroIntegrationError,
    ToolCallResult,
)


def tap_on_mcp_arguments(
    *,
    tap_id: str | None = None,
    tap_text: str | None = None,
    device_id: str | None = None,
) -> dict[str, Any]:
    """
    Exact JSON object sent to Maestro MCP ``tap_on`` (tool name not included).

    Mirrors :meth:`McpMaestroAdapter.tap_on` so callers can log or assert payloads without
    invoking the transport.
    """
    payload: dict[str, Any] = {**_device_args(device_id)}
    tid = (tap_id or "").strip()
    ttxt = (tap_text or "").strip()
    if tid:
        payload["id"] = tid
    elif ttxt:
        payload["text"] = ttxt
    return payload


def input_text_mcp_arguments(*, text: str, device_id: str | None = None) -> dict[str, Any]:
    """Exact JSON object for Maestro MCP ``input_text`` (tool name not included)."""
    return {"text": text, **_device_args(device_id)}


def run_flow_mcp_arguments(*, flow_yaml: str, device_id: str | None = None) -> dict[str, Any]:
    """Exact JSON object for Maestro MCP ``run_flow`` (tool name not included)."""
    return {"flow_yaml": flow_yaml, **_device_args(device_id)}


def tap_on_selector_basis(payload: Mapping[str, Any]) -> str:
    """Coarse classification for logs: ``text``, ``id``, or ``none`` (invalid / empty)."""
    if "id" in payload:
        return "id"
    if "text" in payload:
        return "text"
    return "none"


class McpMaestroAdapter:
    """Translate :class:`MaestroScreenProvider` calls into MCP tool invocations."""

    def __init__(self, transport: MaestroToolTransport) -> None:
        self._transport = transport

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            notes=(
                "Maps to Maestro MCP tools (list_devices, launch_app, ...). "
                "Argument keys follow Maestro's documented JSON shapes where known; "
                "transport wiring is still an application concern."
            )
        )

    def list_devices(self) -> list[DeviceInfo]:
        result = self._transport.call_tool("list_devices", {})
        self._raise_if_error(result)
        return parse_device_list_text(result.text)

    def launch_app(
        self,
        *,
        app_id: str,
        device_id: str | None = None,
        permissions: Mapping[str, Any] | None = None,
    ) -> ActionResult:
        payload: dict[str, Any] = {"appId": app_id, **_device_args(device_id)}
        if permissions is not None:
            payload["permissions"] = dict(permissions)
        result = self._action_tool("launch_app", payload)
        if result.ok or not _is_tool_not_found_message(result.message, "launch_app"):
            return result
        return self._action_tool(
            "run",
            {
                **_device_args(device_id),
                "yaml": _build_launch_app_fallback_yaml(app_id=app_id),
            },
        )

    def stop_app(self, *, app_id: str, device_id: str | None = None) -> ActionResult:
        payload = {"appId": app_id, **_device_args(device_id)}
        return self._action_tool("stop_app", payload)

    def inspect_view_hierarchy(self, *, device_id: str | None = None) -> str:
        result = self._transport.call_tool("inspect_view_hierarchy", _device_args(device_id))
        if not result.is_error:
            return result.text
        if not _is_tool_not_found_message(result.text, "inspect_view_hierarchy"):
            self._raise_if_error(result)
            return result.text
        modern = self._transport.call_tool("inspect_screen", _device_args(device_id))
        self._raise_if_error(modern)
        return inspect_screen_json_to_legacy_hierarchy_csv(modern.text)

    def take_screenshot(self, *, device_id: str | None = None) -> ScreenshotArtifact:
        result = self._transport.call_tool("take_screenshot", _device_args(device_id))
        self._raise_if_error(result)
        if result.binary:
            data = result.binary[0]
            return ScreenshotArtifact(
                mime_type="image/png",
                byte_length=len(data),
                image_bytes=data,
            )
        # Some transports may only return metadata or base64 text; keep bytes unset honestly.
        return ScreenshotArtifact(
            mime_type="image/png",
            byte_length=0,
            image_bytes=None,
        )

    def tap_on(
        self,
        *,
        tap_id: str | None = None,
        tap_text: str | None = None,
        device_id: str | None = None,
    ) -> ActionResult:
        """
        Maestro MCP ``tap_on`` expects structured ``id`` and/or ``text`` keys, not a single
        serialized selector string (``id:…`` / ``text:…`` from ranking is parsed upstream).
        """
        payload = tap_on_mcp_arguments(tap_id=tap_id, tap_text=tap_text, device_id=device_id)
        if "id" not in payload and "text" not in payload:
            return ActionResult(
                ok=False,
                message="Either 'text' or 'id' parameter must be provided",
                raw_text=None,
            )
        result = self._action_tool("tap_on", payload)
        if result.ok or not _is_tool_not_found_message(result.message, "tap_on"):
            return result
        return self._action_tool(
            "run",
            {
                **_device_args(device_id),
                "yaml": _build_tap_fallback_yaml(tap_id=tap_id, tap_text=tap_text),
            },
        )

    def input_text(self, *, text: str, device_id: str | None = None) -> ActionResult:
        payload = input_text_mcp_arguments(text=text, device_id=device_id)
        result = self._action_tool("input_text", payload)
        if result.ok or not _is_tool_not_found_message(result.message, "input_text"):
            return result
        return self._action_tool(
            "run",
            {
                **_device_args(device_id),
                "yaml": _build_input_text_fallback_yaml(text=text),
            },
        )

    def run_flow(self, *, flow_yaml: str, device_id: str | None = None) -> ActionResult:
        payload = run_flow_mcp_arguments(flow_yaml=flow_yaml, device_id=device_id)
        result = self._action_tool("run_flow", payload)
        if result.ok or not _is_tool_not_found_message(result.message, "run_flow"):
            return result
        return self._action_tool("run", {**_device_args(device_id), "yaml": flow_yaml})

    def check_flow_syntax(self, *, flow_yaml: str) -> ActionResult:
        # Maestro MCP documents this tool; exact argument naming can evolve—keep centralized.
        payload = {"flow": flow_yaml}
        return self._action_tool("check_flow_syntax", payload)

    def _action_tool(self, tool: str, arguments: Mapping[str, Any]) -> ActionResult:
        result = self._transport.call_tool(tool, dict(arguments))
        if result.is_error:
            return ActionResult(
                ok=False,
                message=result.text.strip() or "Maestro tool error",
                raw_text=result.text,
            )
        return ActionResult(ok=True, message=None, raw_text=result.text)

    @staticmethod
    def _raise_if_error(result: ToolCallResult) -> None:
        if result.is_error:
            raise MaestroIntegrationError(
                result.text.strip() or "Maestro tool returned an error payload",
                details={"tool": result.tool_name},
            )


def _device_args(device_id: str | None) -> dict[str, Any]:
    """
    Maestro MCP tools expect a device selector; naming has varied (``device_id`` vs ``deviceId``).

    Send **both** keys when set so stdio MCP matches current Maestro servers (which may reject
    ``deviceId``-only payloads with ``device_id is required``).
    """
    d = (device_id or "").strip()
    if not d:
        return {}
    return {"device_id": d, "deviceId": d}


def _is_tool_not_found_message(message: str | None, tool_name: str) -> bool:
    text = (message or "").strip().lower()
    needle = f"tool {tool_name}".lower()
    return "not found" in text and needle in text


def _yaml_quote(value: str) -> str:
    if not value:
        return '""'
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _build_launch_app_fallback_yaml(*, app_id: str) -> str:
    aid = (app_id or "").strip()
    if not aid:
        raise ValueError("app_id is required for launch fallback yaml")
    return "\n".join(
        [
            f"appId: {aid}",
            "---",
            "- launchApp:",
            f"    appId: {aid}",
        ]
    )


def _build_input_text_fallback_yaml(*, text: str) -> str:
    return "\n".join(["---", f"- inputText: {_yaml_quote(text)}"])


def _build_tap_fallback_yaml(*, tap_id: str | None, tap_text: str | None) -> str:
    rid = (tap_id or "").strip()
    txt = (tap_text or "").strip()
    if rid:
        return "\n".join(["---", "- tapOn:", f"    id: {_yaml_quote(rid)}"])
    if txt:
        return "\n".join(["---", f"- tapOn: {_yaml_quote(txt)}"])
    raise ValueError("tap fallback yaml requires id or text")


def inspect_screen_json_to_legacy_hierarchy_csv(payload_text: str) -> str:
    """Best-effort conversion: modern ``inspect_screen`` JSON -> legacy hierarchy CSV text."""
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError as e:
        raise MaestroIntegrationError(
            "inspect_screen returned non-JSON payload",
            details={"error": str(e)},
        ) from e
    if not isinstance(payload, dict):
        raise MaestroIntegrationError("inspect_screen payload is not a JSON object")
    root = payload.get("elements")
    if root is None:
        raise MaestroIntegrationError("inspect_screen payload missing 'elements'")
    rows: list[str] = []
    counter = 0

    def walk(node: Any, depth: int, parent_index: str | None) -> None:
        nonlocal counter
        if not isinstance(node, dict):
            return
        idx = str(counter)
        counter += 1
        attrs = _node_attrs_from_modern_json(node)
        attr_blob = "; ".join(f"{k}={v}" for k, v in attrs.items())
        attr_blob_escaped = attr_blob.replace('"', '""')
        parent = parent_index or ""
        rows.append(f'{idx},{depth},"{attr_blob_escaped}",{parent}')
        children = node.get("c")
        if isinstance(children, list):
            for child in children:
                walk(child, depth + 1, idx)

    if isinstance(root, list):
        for item in root:
            walk(item, 0, None)
    else:
        walk(root, 0, None)
    return "\n".join(rows) + ("\n" if rows else "")


def _node_attrs_from_modern_json(node: dict[str, Any]) -> dict[str, str]:
    attrs: dict[str, str] = {}
    _put(attrs, "resource-id", _string(node.get("rid")))
    _put(attrs, "text", _string(node.get("txt")))
    _put(attrs, "accessibilityText", _string(node.get("a11y")))
    _put(attrs, "class", _string(node.get("cls")))
    _put(attrs, "value", _string(node.get("val")))
    _put(attrs, "hint", _string(node.get("hint")))
    b = _bounds_to_legacy_string(node.get("b"))
    _put(attrs, "bounds", b)
    for key in ("enabled", "clickable", "checked", "focused", "selected", "scroll"):
        if key in node and isinstance(node.get(key), bool):
            attrs[key] = "true" if node.get(key) else "false"
    return attrs


def _string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _put(attrs: dict[str, str], key: str, value: str | None) -> None:
    if value is not None:
        attrs[key] = value


def _bounds_to_legacy_string(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        s = value.strip()
        return s or None
    if isinstance(value, dict):
        left = value.get("left", value.get("x"))
        top = value.get("top", value.get("y"))
        right = value.get("right")
        bottom = value.get("bottom")
        width = value.get("width")
        height = value.get("height")
        if right is None and left is not None and width is not None:
            right = _to_int(left) + _to_int(width)
        if bottom is None and top is not None and height is not None:
            bottom = _to_int(top) + _to_int(height)
        if None not in (left, top, right, bottom):
            return f"[{_to_int(left)},{_to_int(top)}][{_to_int(right)},{_to_int(bottom)}]"
    if isinstance(value, (list, tuple)) and len(value) == 4:
        a, b, c, d = value
        return f"[{_to_int(a)},{_to_int(b)}][{_to_int(c)},{_to_int(d)}]"
    return str(value).strip() or None


def _to_int(value: Any) -> int:
    return int(float(value))
