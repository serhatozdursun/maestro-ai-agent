"""Types and errors for MCP (or other) tool transports."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, Field


class ToolCallResult(BaseModel):
    """
    Normalized outcome of a single MCP tool invocation.

    MCP payloads vary by client/version; this type keeps what the adapter needs:
    concatenated text content, optional binary parts (e.g. screenshots), and flags.
    """

    tool_name: str
    text: str = ""
    binary: list[bytes] = Field(default_factory=list)
    is_error: bool = False
    raw: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional diagnostic payload from the transport (not for business logic).",
    )


class TransportNotConfiguredError(RuntimeError):
    """Raised when no MCP transport is wired but a tool call was attempted."""

    def __init__(self, message: str | None = None) -> None:
        super().__init__(
            message
            or "Maestro MCP transport is not configured. Provide a concrete MaestroToolTransport "
            "implementation (stdio/HTTP client) when wiring the integration layer."
        )


class MaestroIntegrationError(RuntimeError):
    """Raised when Maestro returns an error payload or an unexpected response shape."""

    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details = dict(details or {})
