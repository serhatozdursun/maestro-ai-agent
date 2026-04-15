"""Service-layer models for Maestro devices, hierarchy, screenshots, and actions."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import AliasChoices, BaseModel, Field

from maestro_ai_agent.domain.enums import Platform
from maestro_ai_agent.domain.hierarchy import HierarchyNode, HierarchySnapshot

__all__ = [
    "ActionRequest",
    "ActionResult",
    "DeviceInfo",
    "HierarchyNode",
    "HierarchySnapshot",
    "ProviderCapabilities",
    "ScreenshotArtifact",
    "StructuredScreenObservation",
]


class DeviceInfo(BaseModel):
    """A connected device as reported by Maestro (shape may vary by Maestro version)."""

    device_id: str = Field(validation_alias=AliasChoices("device_id", "id", "deviceId"))
    description: str | None = Field(
        default=None,
        validation_alias=AliasChoices("description", "name", "title"),
    )
    platform: Platform | None = Field(
        default=None,
        description="Best-effort platform hint when the payload includes it.",
    )

    model_config = {"populate_by_name": True}


class ScreenshotArtifact(BaseModel):
    """Metadata for a screenshot returned by Maestro (bytes optional for tests/offline use)."""

    captured_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    mime_type: str = Field(default="image/png")
    byte_length: int = Field(ge=0, default=0)
    sha256: str | None = Field(
        default=None,
        description="Hex digest when precomputed by the adapter.",
    )
    image_bytes: bytes | None = Field(
        default=None,
        description="Present when the transport returned raw image bytes.",
    )
    source: str = Field(
        default="mcp",
        description="Provenance label (e.g. mcp, cli) for reporting.",
    )


class ActionRequest(BaseModel):
    """Intent to perform a Maestro-level action (transport-agnostic)."""

    name: str = Field(min_length=1, description="Logical action name (tap, input_text, ...).")
    selector: str | None = None
    text: str | None = None
    app_id: str | None = None
    device_id: str | None = None
    extra: dict[str, str] = Field(default_factory=dict)


class ActionResult(BaseModel):
    """Outcome of an action or auxiliary call (syntax check, etc.)."""

    ok: bool
    message: str | None = None
    raw_text: str | None = Field(default=None, description="Raw textual payload from Maestro/MCP.")


class ProviderCapabilities(BaseModel):
    """Advertised tool surface for a provider implementation."""

    supports_list_devices: bool = True
    supports_launch_app: bool = True
    supports_stop_app: bool = True
    supports_inspect_view_hierarchy: bool = True
    supports_take_screenshot: bool = True
    supports_tap_on: bool = True
    supports_input_text: bool = True
    supports_check_flow_syntax: bool = True
    supports_run_flow: bool = True
    notes: str | None = Field(
        default=None,
        description="Human-readable caveats (e.g. transport not wired, schema assumptions).",
    )


class StructuredScreenObservation(BaseModel):
    """
    Primary orchestrator-facing observation: hierarchy + optional screenshot metadata.

    This is intentionally richer than ``domain.observation.ScreenObservation`` so services
    can evolve Maestro-specific fields without overloading domain models.
    """

    app_id: str
    platform: Platform
    device_id: str | None = None
    hierarchy: HierarchySnapshot
    screenshot: ScreenshotArtifact | None = None
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
