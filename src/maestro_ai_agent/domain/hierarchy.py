"""Structured view hierarchy models shared by services and selector logic."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field


class HierarchyNode(BaseModel):
    """One row from Maestro hierarchy CSV, normalized for selector generation."""

    node_index: str = Field(description="Stable row identifier from Maestro CSV (first column).")
    depth: int = Field(ge=0)
    parent_index: str | None = Field(
        default=None,
        description="Parent row identifier from Maestro CSV (last column), if present.",
    )
    attributes: dict[str, str] = Field(default_factory=dict)
    resource_id: str | None = None
    class_name: str | None = None
    text: str | None = Field(
        default=None,
        description="Raw ``text=`` attribute from Maestro when present (Android / some rows).",
    )
    visible_text: str | None = Field(
        default=None,
        description=(
            "Normalized visible label: first non-empty among text, accessibilityText, "
            "label, name, value (iOS often exposes labels only as accessibilityText)."
        ),
    )
    bounds: str | None = None
    package: str | None = None
    enabled: bool | None = None


def effective_visible_text(node: HierarchyNode) -> str:
    """Prefer coalesced ``visible_text``, then raw ``text``, for matching and ranking."""
    vt = (node.visible_text or "").strip()
    if vt:
        return vt
    return (node.text or "").strip()


class HierarchySnapshot(BaseModel):
    """Structured result of parsing ``inspect_view_hierarchy`` CSV output."""

    nodes: list[HierarchyNode] = Field(default_factory=list)
    raw_csv: str = Field(default="", description="Original CSV text (trimmed) for debugging.")
    parse_warnings: list[str] = Field(default_factory=list)
    captured_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
