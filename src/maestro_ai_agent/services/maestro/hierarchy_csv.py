"""Parse Maestro ``inspect_view_hierarchy`` CSV into structured nodes."""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Iterable

from maestro_ai_agent.domain.hierarchy import HierarchyNode, HierarchySnapshot

_HEADER_HINTS = frozenset({"index", "node", "nodeindex", "depth", "attributes", "parent"})

# iOS / Studio CSV often uses a dedicated bounds column before the attribute blob.
_BOUNDS_ONLY_CELL = re.compile(r"^\[\s*\d+\s*,\s*\d+\s*\]\s*\[\s*\d+\s*,\s*\d+\s*\]$")


class HierarchyParseError(ValueError):
    """Raised when CSV text cannot be interpreted even at a minimal level."""


def _cell_looks_like_bounds_column(cell: str) -> bool:
    s = cell.strip()
    return bool(_BOUNDS_ONLY_CELL.match(s))


def _coalesce_visible_text(attrs: dict[str, str]) -> str | None:
    """
    First non-empty among Maestro attribute keys that carry user-visible strings.

    Order: ``text``, ``accessibilityText``, ``label``, ``name``, ``value``.
    """
    for key in ("text", "accessibilityText", "label", "name", "value"):
        raw = attrs.get(key)
        if raw is None:
            continue
        v = str(raw).strip()
        if v:
            return v
    return None


def _split_attribute_blob(blob: str) -> dict[str, str]:
    """Parse Maestro's ``key=value; key=value`` attribute strings."""
    out: dict[str, str] = {}
    for chunk in blob.split(";"):
        piece = chunk.strip()
        if not piece:
            continue
        if "=" not in piece:
            continue
        key, _, value = piece.partition("=")
        k = key.strip()
        v = value.strip()
        if k:
            out[k] = v
    return out


def _parse_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    lower = value.lower()
    if lower in {"true", "1", "yes"}:
        return True
    if lower in {"false", "0", "no"}:
        return False
    return None


def _looks_like_header_row(row: list[str]) -> bool:
    if not row:
        return False
    lowered = [c.strip().lower() for c in row if c.strip()]
    if not lowered:
        return False
    hits = sum(1 for cell in lowered if cell in _HEADER_HINTS or "attr" in cell)
    return hits >= 2


def _row_to_node(
    *,
    node_index: str,
    depth_raw: str,
    attr_blob: str,
    parent: str | None,
    bounds_cell: str | None,
    warnings: list[str],
    row_number: int,
) -> HierarchyNode | None:
    try:
        depth = int(depth_raw)
        if depth < 0:
            raise ValueError
    except ValueError:
        warnings.append(f"Row {row_number}: invalid depth {depth_raw!r}; skipped.")
        return None
    attrs = _split_attribute_blob(attr_blob)
    resource = attrs.get("resource-id") or attrs.get("resource_id")
    class_name = attrs.get("class")
    raw_text = attrs.get("text")
    visible_text = _coalesce_visible_text(attrs)
    bounds_from_cell = bounds_cell.strip() if bounds_cell and bounds_cell.strip() else None
    bounds = bounds_from_cell or attrs.get("bounds")
    package = attrs.get("package")
    enabled = _parse_bool(attrs.get("enabled"))
    parent_index = parent.strip() if parent and parent.strip() else None
    return HierarchyNode(
        node_index=node_index.strip(),
        depth=depth,
        parent_index=parent_index,
        attributes=attrs,
        resource_id=resource,
        class_name=class_name,
        text=raw_text,
        visible_text=visible_text,
        bounds=bounds,
        package=package,
        enabled=enabled,
    )


def _consume_rows(rows: Iterable[list[str]], *, warnings: list[str]) -> list[HierarchyNode]:
    nodes: list[HierarchyNode] = []
    rows_list = list(rows)
    if not rows_list:
        return nodes

    start_idx = 0
    if _looks_like_header_row(rows_list[0]):
        warnings.append("Detected header row; Maestro versions may omit headers—parser skipped it.")
        start_idx = 1

    for offset, row in enumerate(rows_list[start_idx:], start=start_idx + 1):
        if not row or all(not c.strip() for c in row):
            continue
        if len(row) == 5 and _cell_looks_like_bounds_column(row[2]):
            node = _row_to_node(
                node_index=row[0],
                depth_raw=row[1],
                attr_blob=row[3],
                parent=row[4],
                bounds_cell=row[2],
                warnings=warnings,
                row_number=offset,
            )
            if node:
                nodes.append(node)
            continue
        if len(row) >= 4:
            node = _row_to_node(
                node_index=row[0],
                depth_raw=row[1],
                attr_blob=row[2],
                parent=row[3],
                bounds_cell=None,
                warnings=warnings,
                row_number=offset,
            )
            if node:
                nodes.append(node)
            continue
        if len(row) == 3:
            node = _row_to_node(
                node_index=row[0],
                depth_raw=row[1],
                attr_blob=row[2],
                parent="",
                bounds_cell=None,
                warnings=warnings,
                row_number=offset,
            )
            if node:
                nodes.append(node)
            continue
        if len(row) == 1 and ";" in row[0]:
            warnings.append(
                f"Row {offset}: single-column attribute blob converted into a synthetic root node."
            )
            attrs = _split_attribute_blob(row[0])
            raw_text = attrs.get("text")
            nodes.append(
                HierarchyNode(
                    node_index="0",
                    depth=0,
                    parent_index=None,
                    attributes=attrs,
                    resource_id=attrs.get("resource-id") or attrs.get("resource_id"),
                    class_name=attrs.get("class"),
                    text=raw_text,
                    visible_text=_coalesce_visible_text(attrs),
                    bounds=attrs.get("bounds"),
                    package=attrs.get("package"),
                    enabled=_parse_bool(attrs.get("enabled")),
                )
            )
            continue
        warnings.append(f"Row {offset}: unrecognized shape ({len(row)} columns); skipped.")
    return nodes


def parse_maestro_hierarchy_csv(csv_text: str) -> HierarchySnapshot:
    """
    Parse Maestro hierarchy CSV into :class:`HierarchySnapshot`.

    Supported shapes:
    - **5-column** rows: ``node_index, depth, bounds, "attributes...", parent_index`` (common iOS).
    - **4-column** rows: ``node_index, depth, "attributes...", parent_index`` (common Android MCP).
    - **3-column** rows: ``node_index, depth, "attributes..."`` (parent omitted).
    - **Header row** containing words like ``depth`` / ``attributes`` (skipped after warning).
    - **Single-column** attribute blob (synthetic root node ``0``).

    Extra trailing columns are ignored for the 4-column Android shape; the 5-column iOS shape
    is detected when column 2 is a ``[x,y][x,y]`` bounds cell.
    """
    raw = csv_text or ""
    trimmed = raw.strip()
    warnings: list[str] = []
    if not trimmed:
        warnings.append("Empty hierarchy CSV.")
        return HierarchySnapshot(raw_csv=raw, parse_warnings=warnings)

    reader = csv.reader(io.StringIO(trimmed))
    rows = list(reader)
    if not rows:
        warnings.append("CSV reader returned no rows.")
        return HierarchySnapshot(raw_csv=trimmed, parse_warnings=warnings)

    nodes = _consume_rows(rows, warnings=warnings)
    if not nodes and trimmed:
        message = "; ".join(warnings) if warnings else "No nodes parsed from hierarchy CSV."
        raise HierarchyParseError(message)
    return HierarchySnapshot(nodes=nodes, raw_csv=trimmed, parse_warnings=warnings)
