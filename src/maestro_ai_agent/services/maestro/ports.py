"""Protocols for Maestro MCP-style integrations (mock-friendly, transport-agnostic)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from maestro_ai_agent.services.maestro.models import (
    ActionResult,
    DeviceInfo,
    ProviderCapabilities,
    ScreenshotArtifact,
)
from maestro_ai_agent.services.maestro.transport_types import ToolCallResult


class MaestroToolTransport(Protocol):
    """
    Lowest-level boundary: invoke a named MCP tool with JSON-serializable arguments.

    Concrete implementations may wrap stdio MCP, HTTP+SSE, or in-process fakes for tests.
    This repository does not ship a full MCP client yet.
    """

    def call_tool(self, name: str, arguments: Mapping[str, Any]) -> ToolCallResult:
        """Invoke tool ``name`` with arguments and return a normalized result."""
        ...


class MaestroScreenProvider(Protocol):
    """
    Stable orchestrator-facing surface for Maestro device actions.

    Implemented by :class:`McpMaestroAdapter` today; a future CLI adapter can implement
    the same protocol so the orchestrator stays backend-agnostic.
    """

    def capabilities(self) -> ProviderCapabilities:
        """Describe which operations this provider maps to Maestro capabilities."""
        ...

    def list_devices(self) -> list[DeviceInfo]:
        """Return connected devices (best-effort JSON parsing of Maestro output)."""
        ...

    def launch_app(
        self,
        *,
        app_id: str,
        device_id: str | None = None,
        permissions: Mapping[str, Any] | None = None,
    ) -> ActionResult:
        """
        Launch ``app_id`` on the optional ``device_id``.

        ``permissions`` is optional Maestro ``launchApp.permissions`` (e.g. ``{"all": "allow"}``).
        """
        ...

    def stop_app(self, *, app_id: str, device_id: str | None = None) -> ActionResult:
        """Stop ``app_id`` on the optional ``device_id``."""
        ...

    def inspect_view_hierarchy(self, *, device_id: str | None = None) -> str:
        """Return raw CSV hierarchy text from Maestro."""
        ...

    def take_screenshot(self, *, device_id: str | None = None) -> ScreenshotArtifact:
        """Capture a screenshot; may include raw bytes when the transport supplies them."""
        ...

    def tap_on(
        self,
        *,
        tap_id: str | None = None,
        tap_text: str | None = None,
        device_id: str | None = None,
    ) -> ActionResult:
        """Tap using Maestro MCP structured ``id`` or ``text`` (exactly one should be set)."""
        ...

    def run_flow(self, *, flow_yaml: str, device_id: str | None = None) -> ActionResult:
        """Run an inline Maestro flow document (YAML string)."""
        ...

    def input_text(self, *, text: str, device_id: str | None = None) -> ActionResult:
        """Input text into the focused field."""
        ...

    def check_flow_syntax(self, *, flow_yaml: str) -> ActionResult:
        """Validate a Maestro YAML snippet (syntax-only)."""
        ...
