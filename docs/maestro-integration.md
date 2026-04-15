# Maestro integration strategy

This document explains **how this repository integrates with Maestro** today, how **MCP** and **CLI** relate, and what remains intentionally out of scope.

## What is implemented in Python (today)

The `maestro_ai_agent.services.maestro` package provides:

- **`MaestroToolTransport`** — a narrow boundary for “call MCP tool *X* with JSON arguments”. **`McpStdioTransport`** implements NDJSON-over-stdio for `maestro mcp`; HTTP+SSE is not implemented here.
- **`McpMaestroAdapter`** (`MaestroScreenProvider`) — maps orchestration-friendly methods onto **documented Maestro MCP tool names** (for example `inspect_view_hierarchy`, `take_screenshot`, `launch_app`). Argument keys follow Maestro docs where known; they may evolve upstream.
- **`parse_maestro_hierarchy_csv`** — converts `inspect_view_hierarchy` **CSV** into `HierarchySnapshot` / `HierarchyNode` models (primary structured observation for future selector work).
- **`MaestroScreenService`** — **`observe_current_screen`** composes hierarchy inspection (required) with optional screenshot capture (secondary context); **`tap_on`** and **`input_text`** forward to the same **`MaestroScreenProvider`**. The orchestrator may call **`observe_current_screen`** again after a successful action to drive **deterministic post-execution validation** (hierarchy-only; no transport-specific parsing beyond existing CSV rules).
- **`UnconfiguredMcpTransport`** — explicit stub that **fails fast** until a real transport is injected.

This layer is **honest scaffolding**: it is structured for production use, but **does not pretend** a transport is connected unless you provide one (for example in tests via a mock transport).

## Relationship to upstream Maestro MCP

Upstream Maestro ships an MCP server via `maestro mcp`; see [Maestro MCP Server](https://docs.maestro.dev/mcp). That server still assumes the **Maestro CLI** is installed on `PATH`.

This repository does **not** embed a full MCP client SDK; **`scenario-run`** uses **`McpStdioTransport`** against `maestro mcp`. Other hosts can supply their own **`MaestroToolTransport`**.

**Device preflight extras:** `launch_app` may pass `permissions: { all: allow }` for native permission prompts. After the first hierarchy stability wait, **`dismiss_known_blocking_popups_if_present`** (in `services.maestro.blocking_popup_dismissal`) performs a single conservative check (e.g. “Developer Mode” + **Continue**); if it taps **Continue**, the runner calls **`wait_for_hierarchy_stable`** again before planning. The main orchestrator loop is unchanged.

## CLI-first vs MCP-first (project history vs current code)

Earlier docs emphasized a **CLI-first MVP** for ubiquity in CI. The **first concrete integration code** in this repo is **MCP-oriented** because:

- `inspect_view_hierarchy` is already specified around **CSV** output suited to LLM and agent consumption.
- MCP tool names give a **stable contract** to mock in unit tests without subprocess brittleness.
- A future **CLI adapter** can implement the same `MaestroScreenProvider` protocol, keeping orchestration code agnostic.

CLI subprocess support remains a **planned adapter**, not duplicate logic.

## Tradeoffs

| Aspect | MCP provider (implemented) | CLI adapter (planned) |
|--------|--------------------------|------------------------|
| **Setup** | Requires a working MCP client + Maestro on `PATH` | Requires Maestro on `PATH` only |
| **Testing** | Mock `MaestroToolTransport` responses | Mock subprocess I/O |
| **CI** | Depends on how MCP is hosted in the runner | Straightforward local binary |
| **Hierarchy fidelity** | CSV parsing centralized in `hierarchy_csv.py` | Same parser can wrap CLI output |

## Screen-by-screen operation

Regardless of transport, the integration layer is designed so the orchestrator can treat **`HierarchySnapshot` as the primary structured observation** and screenshots as **optional supporting context**.

## Hierarchy CSV assumptions

Maestro’s CSV has evolved over time. The parser supports:

- common **4-column** rows (`node_index`, `depth`, quoted `attributes`, `parent_index`);
- **3-column** rows without an explicit parent;
- optional **header** rows (detected heuristically and skipped with a warning);
- **single-column** semicolon attribute blobs (synthetic root node, warning recorded).

When non-empty CSV cannot be parsed into nodes, the parser raises `HierarchyParseError` with collected warnings—callers should surface this in runtime reports.
