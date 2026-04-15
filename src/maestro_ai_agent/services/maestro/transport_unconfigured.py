"""Explicit transport placeholder for environments without a wired MCP client."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, NoReturn

from maestro_ai_agent.services.maestro.transport_types import TransportNotConfiguredError


class UnconfiguredMcpTransport:
    """
    Stub transport that always fails fast.

    Use this as a default bean when wiring DI, or as documentation for what must be
    replaced with a real MCP transport implementation.
    """

    def call_tool(self, name: str, arguments: Mapping[str, Any]) -> NoReturn:
        raise TransportNotConfiguredError(
            f"Cannot call MCP tool {name!r}: transport is not configured. "
            "Inject a MaestroToolTransport implementation."
        )
