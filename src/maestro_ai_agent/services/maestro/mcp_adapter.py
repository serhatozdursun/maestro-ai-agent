"""
MCP-oriented Maestro adapter.

Maps high-level operations onto Maestro MCP tool names documented at
https://docs.maestro.dev/mcp . This module does **not** implement JSON-RPC or stdio
transport; it depends on :class:`MaestroToolTransport` for that boundary.
"""

from __future__ import annotations

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
        return self._action_tool("launch_app", payload)

    def stop_app(self, *, app_id: str, device_id: str | None = None) -> ActionResult:
        payload = {"appId": app_id, **_device_args(device_id)}
        return self._action_tool("stop_app", payload)

    def inspect_view_hierarchy(self, *, device_id: str | None = None) -> str:
        result = self._transport.call_tool("inspect_view_hierarchy", _device_args(device_id))
        self._raise_if_error(result)
        return result.text

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
        return self._action_tool("tap_on", payload)

    def input_text(self, *, text: str, device_id: str | None = None) -> ActionResult:
        payload = input_text_mcp_arguments(text=text, device_id=device_id)
        return self._action_tool("input_text", payload)

    def run_flow(self, *, flow_yaml: str, device_id: str | None = None) -> ActionResult:
        payload = run_flow_mcp_arguments(flow_yaml=flow_yaml, device_id=device_id)
        return self._action_tool("run_flow", payload)

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
