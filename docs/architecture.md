# Architecture

**Product intent** (multi-format scenarios, deterministic-first, where AI is allowed): see the repository root **[ARCHITECTURE.md](../ARCHITECTURE.md)**.

This document describes the intended layout of **maestro-ai-agent** at a high level. The codebase is organized for long-term evolution: clear boundaries, testable pure logic where possible, and thin integration at the edges.

**Posture:** the project is **experimental but production-minded**—small surface area first, strict boundaries, structured logging, and documentation that matches reality.

## Goals

- Convert a natural-language scenario plus `appId` / `platform` into an executable Maestro YAML flow.
- Explore the app **screen-by-screen** using Maestro: hierarchy inspection → selector choice → action → validation before advancing (see [maestro-integration.md](maestro-integration.md)).
- Keep planning, execution, selector decisions, and YAML generation as separate concerns.

## Maestro backends (current vs future)

- **Implemented today (Python):** an **MCP-oriented integration layer** under `services.maestro` exposes a stable `MaestroScreenProvider` protocol, a concrete `McpMaestroAdapter`, CSV hierarchy parsing, and `MaestroScreenService.observe_current_screen`. **JSON-RPC / stdio / HTTP transport is intentionally not implemented here**—inject a `MaestroToolTransport` implementation (or use `UnconfiguredMcpTransport` to fail fast).
- **Still planned:** a **Maestro CLI** subprocess adapter can implement the same provider protocol for CI-style runs without an MCP host.
- **Editor MCP:** upstream `maestro mcp` remains the reference server; this repository consumes it only through the transport boundary. Tradeoffs live in [maestro-integration.md](maestro-integration.md).

## Scenario understanding (`maestro_ai_agent.scenario`)

**Classify** raw text → **deterministic** canonical steps (`CanonicalScenario` / `CanonicalStep`: `action`, `target`, `value`) → **confidence** → optional **AI fallback** that may only refine canonical steps (never Maestro YAML).

**Planner bridge:** `planning_adapter.build_parsed_scenario_from_canonical` maps a canonical scenario into :class:`ParsedScenario` so :func:`maestro_ai_agent.domain.planning.plan_intents` runs unchanged.

**Orchestrator entry (two paths):**

1. **Default (legacy):** :class:`ScenarioRunRequest` with `scenario_input` → `parse_scenario_input` → `plan_intents` → existing step loop. Deterministic-first; unchanged from before the canonical layer.
2. **Opt-in canonical:** set `ScenarioRunRequest.use_canonical_scenario_normalization=True` (requires `scenario_input`). Runs `normalize_scenario_text(..., enable_ai_fallback=False)` then `build_parsed_scenario_from_canonical` inside `_resolve_parsed`—no AI, no new runtime behavior. `parsed_scenario`-only requests cannot use this flag.

**Preferred direction** for rich or Gherkin-like text is path (2); path (1) remains supported for simple line scenarios and backward compatibility. The **`scenario-run`** CLI wires path (2) explicitly.

## Package map (`src/maestro_ai_agent/`)

| Area             | Responsibility                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| ---------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **domain**       | Pydantic models for scenarios, intents, selectors, hierarchy snapshots, flow drafts, observations, and execution attempts; deterministic **parse** (`parse_scenario_input`), **plan** (`plan_intents`), and **selector ranking** (`plan_selector_ranking`); **FlowDraftBuilder** for step accumulation (`append_successful`, **`append_planned`**, **`append_executed_*`** including validated / failed / inconclusive / skipped / unvalidated). No Maestro IO.                                                                                                         |
| **services**     | Maestro integration: **MCP provider surface** (`MaestroScreenProvider`, `McpMaestroAdapter`), **CSV hierarchy parser**, **`MaestroScreenService`** (`observe_current_screen`, **`tap_on`**, **`input_text`** delegating to the provider), future **CLI** adapter, YAML writer, artifacts. Side effects live here.                                                                                                                                                                                                                                                       |
| **orchestrator** | **`ScenarioPlanningOrchestrator`**: **`run_planning_only`** vs **`run_observe_plan_execute`** (observe → rank → plan → execute → **re-observe → validate**). **`PostExecutionValidationService`** compares before/after **`HierarchySnapshot`** using **`ValidationGoal`** heuristics; **`FlowDraftBuilder`** appends **`append_executed_validated`** / **`append_executed_validation_*`** with explicit metadata. **No** retries; orchestrator does **not** emit product YAML (**`app.scenario_run`** may write **`maestro_draft_preview.yaml`** from the flow draft). |
| **app**          | CLI (Typer), **`scenario-run`** (MCP session, device preflight, hierarchy stability wait, **`exploration_report.json`** + **`maestro_draft_preview.yaml`**), process entrypoints.                                                                                                                                                                                                                                                                                                                                                                                       |
| **shared**       | Structured logging setup, shared constants, small helpers used across layers.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |

## Domain module map (`maestro_ai_agent.domain`)

| Module                      | Role                                                                                                                                                             |
| --------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `enums.py`                  | `Platform`, `ActionType`, `SelectorType`, `StepStatus`, `ConfidenceLevel`, `ValidationSignalType`                                                                |
| `scenario.py`               | `ScenarioInput`, `ScenarioStep`, `ParsedScenario`                                                                                                                |
| `parse_scenario.py`         | Deterministic newline + list-marker parsing into `ParsedScenario`                                                                                                |
| `planning.py`               | Keyword heuristics: `ParsedScenario` → `list[StepIntent]` with coarse `ValidationGoal`s; **`quoted_literal_from_step_text`** for execution-safe input extraction |
| `intent.py`                 | `StepIntent`, `ValidationGoal`                                                                                                                                   |
| `hierarchy.py`              | `HierarchyNode`, `HierarchySnapshot`, `effective_visible_text` (shared with services for parsing + selector work)                                                |
| `selector.py`               | `SelectorCandidate` (attached to intents after ranking)                                                                                                          |
| `selectors/`                | Evidence, explanations, `generate_proposals`, `rank_selector_proposals`, `plan_selector_ranking`                                                                 |
| `confidence.py`             | `ConfidenceScore`                                                                                                                                                |
| `flow.py` / `flow_draft.py` | `FlowDraftBuilder`: `append_planned`, `append_executed_*` (validated / failed / inconclusive / skipped / unvalidated); not Maestro YAML                          |
| `observation.py`            | `ScreenObservation`, `ExecutionAttempt`                                                                                                                          |

## Data flow (target)

1. **Input**: scenario text, `appId`, `platform`, optional run configuration (`ScenarioInput`).
2. **Parse**: `parse_scenario_input` → `ParsedScenario` (atomic lines).
3. **Plan**: `plan_intents` → `StepIntent` rows with validation goals.
4. **Select**: `plan_selector_ranking(hierarchy, intent)` → ranked `SelectorCandidate`s (+ structured `SelectorExplanation`s); optionally `apply_ranking_to_intent`.
5. **Per step (planning-only default)**: `MaestroScreenService.observe_current_screen` → **`plan_selector_ranking`** → record **`StepRunState`**, **`RunDecisionLogEntry`**, optional **`append_planned`**. **No** Maestro action invocation.
6. **Per step (limited execution — `OBSERVE_PLAN_EXECUTE`)**: same as (5) when a primary exists → **`ProviderStepExecutionService`** → on **`ActionResult.ok`**, **`PostExecutionValidationService`** re-observes and sets **`RunStepPhase`** to **`VALIDATED`**, **`VALIDATION_FAILED`**, **`VALIDATION_INCONCLUSIVE`**, or **`VALIDATION_SKIPPED`**, plus **`PostActionValidationRecord`**. Flow draft uses **`append_executed_validated`** / **`append_executed_validation_failed`** / etc.
7. **Per step (future)**: richer signals (screenshots, WebView), **`append_successful`** alignment, YAML export.
8. **Output**: runtime report + decision log; Maestro YAML remains **services** / later milestone.

## Services module map (`maestro_ai_agent.services.maestro`)

| Module                                             | Role                                                                                                               |
| -------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| `ports.py`                                         | `MaestroToolTransport` (MCP tool boundary) and `MaestroScreenProvider` (device + screen operations).               |
| `transport_types.py` / `transport_unconfigured.py` | `ToolCallResult`, errors, explicit unwired transport stub.                                                         |
| `mcp_adapter.py`                                   | Maps provider methods to Maestro MCP tool names (`inspect_view_hierarchy`, `take_screenshot`, …).                  |
| `hierarchy_csv.py`                                 | Parses Maestro hierarchy CSV into domain `HierarchySnapshot` / `HierarchyNode`.                                    |
| `device_payload.py`                                | Best-effort JSON parsing for `list_devices`.                                                                       |
| `screen_service.py`                                | `observe_current_screen`, `tap_on`, `input_text` facades over the provider.                                        |
| `models.py`                                        | Service DTOs (`DeviceInfo`, `StructuredScreenObservation`, …); re-exports hierarchy types from `domain.hierarchy`. |

## Orchestrator module map (`maestro_ai_agent.orchestrator`)

| Module                       | Role                                                                                                                                                                                                   |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `models.py`                  | `ScenarioRunRequest`, `ScenarioRunContext`, `ScenarioRunState`, `StepRunState`, `PlannedActionAttempt`, `ObservationCycleResult`, `RunDecisionLogEntry`, `RunReport`, `PlanningOrchestrationResult`, … |
| `enums.py`                   | `RunStepPhase`, `StepValidationStatus`, `PlanningRunMode`, `DecisionExecutionFootprint`                                                                                                                |
| `planning_service.py`        | `ScenarioPlanningOrchestrator` — `run_planning_only`, `run_observe_plan_execute`                                                                                                                       |
| `step_processing.py`         | Observe + rank + plan for one `StepIntent` (composition)                                                                                                                                               |
| `observation_cycle.py`       | `StructuredScreenObservation` → `ObservationCycleResult`                                                                                                                                               |
| `action_attempt_planning.py` | Ranking → `PlannedActionAttempt` (no execution)                                                                                                                                                        |
| `run_state.py`               | Pure `StepRunState` transitions after observe / rank                                                                                                                                                   |
| `decision_log.py`            | Build `RunDecisionLogEntry` from terminal step state                                                                                                                                                   |
| `run_report.py`              | Assemble honest `RunReport` (limitations, counts)                                                                                                                                                      |
| `execution/`                 | **`action_mapping`**, **`execution_service`** (`ProviderStepExecutionService`, **`classify_skipped_step_for_execute_mode`**)                                                                           |
| `validation/`                | **`hierarchy_compare`**, **`heuristics`**, **`PostExecutionValidationService`** (post-tap/input re-observe + deterministic goals)                                                                      |

## Dependency direction

- `app` → `orchestrator` → `services` → external processes (Maestro).
- `domain` is imported by all layers; it must not import `services` or `app`.
- `orchestrator` coordinates; it should not embed low-level Maestro command strings (delegate to `services`). It may call **`MaestroScreenService`** for observation because that is the supported façade over `MaestroScreenProvider`.

## Testability

- Unit tests target **domain** (schemas, small pure functions), **hierarchy CSV parsing**, and **selector generation/ranking** (deterministic heuristics).
- **Services** integration tests use fakes or recorded responses for Maestro/hierarchy payloads.
- **Orchestrator** tests use stub `MaestroScreenProvider` / `MaestroScreenService` fakes to assert observation calls, ranking inputs, `RunStepPhase` transitions, and report contents without a device.

## Configuration

Runtime settings (paths, log level, device identifiers) should load from environment variables with Pydantic Settings in `app` or `shared`, keeping secrets out of the repository (see `.env.example`).
