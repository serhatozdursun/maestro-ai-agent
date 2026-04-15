# Architecture (product intent)

This document locks in **what maestro-ai-agent is for** and **how control should flow** across the stack. For the **current package layout, modules, and data flow in code**, see [docs/architecture.md](docs/architecture.md).

---

## Purpose

**maestro-ai-agent** is a **runtime exploration and execution engine** for mobile apps using Maestro: it **observes** the UI hierarchy on a real device, **resolves** selectors with **deterministic** logic, **executes** actions when configured, **validates** outcomes against structured evidence, and **records structured run data**. **Deterministic logic first**; **AI only where explicitly allowed as a fallback** (parsing, optional visual hints—not the control plane).

**Maestro YAML** produced by the tooling is a **draft preview artifact** (replay / hand-off / rough Maestro shape). It is **not** the authoritative product output. **External AI tools** and your **Maestro project** own naming, environments, subflows, and final flow layout; this repository does **not** encode project-specific conventions.

The project is **not** a one-step-only demo. The **`scenario-run`** CLI (MCP-oriented exploration) is the primary **device-backed** path: multi-line scenarios with canonical normalization, planning, and structured artifacts.

---

## Naming and control-plane clarity

- The repository/package/CLI name stays **`maestro-ai-agent`** for continuity.
- Architecturally, the system is a **deterministic-first orchestration runtime**, not an LLM-led agent.
- The primary runtime actor is **`ScenarioPlanningOrchestrator`**: it drives observe → plan → execute → validate with structured state transitions.
- AI-facing ports such as **`AIFallbackParser`** and **`VisualTargetSuggester`** are **optional fallback/advisory boundaries**.
- External LLM integrations should be described as **AI providers/backends** behind those ports, never as the core control plane.

---

## Supported input styles (long-term)

Inputs should be classifiable and normalizable into one **canonical scenario format** (see [docs/scenario-format.md](docs/scenario-format.md) for current conventions):

| Style                     | Examples (illustrative)                                             |
| ------------------------- | ------------------------------------------------------------------- |
| Natural language          | “Open the cart and verify checkout is visible.”                     |
| Step lists                | Numbered or bulleted lines the user treats as ordered steps.        |
| Gherkin / BDD             | `Given` / `When` / `Then` style scenarios (normalization target).   |
| English / Turkish / mixed | Same intent expressed in one or multiple languages in one scenario. |

**Today:** deterministic parsing focuses on **newline / list-style** scenario text in English-oriented heuristics; **broader classification and multilingual parsing** are **roadmap**, not fully implemented.

---

## Deterministic-first principle

**Default:** every stage that can be rule-based, schema-based, or hierarchy-based **should be**.

**AI is allowed only as an advisory or fallback layer**, for example:

1. **Scenario parsing fallback** — when classification or parse confidence is too low, optional structured assistance to propose or repair steps **into** the canonical format (not open-ended “write a whole flow”).
2. **Locator / visual fallback** — when hierarchy-backed selector generation fails or is inconclusive; see [docs/visual-advisory-fallback.md](docs/visual-advisory-fallback.md).
3. **Failure explanation (future)** — human-readable summaries **on top of** deterministic evidence, not a replacement for validation logic.

**AI must not become the main implementation for:**

- Hierarchy parsing (CSV → `HierarchySnapshot`, node semantics)
- Selector proposal and **ranking core**
- Provider / transport mapping to Maestro tools
- Maestro YAML **serialization** for **draft previews** (shapes stay Maestro-native and reviewable; not “final project flow” generation)
- Orchestrator **state machine** and step transitions
- **Validation core** (pass/fail/inconclusive rules on structured evidence)

---

## Target pipeline (conceptual)

End state the codebase should grow toward:

```
Scenario Input
  → Input Classification
  → Deterministic Scenario Parsing
  → Parse Confidence Evaluation
  → AI Parsing Fallback (optional)
  → Canonical Scenario Format
  → Intent / step planning
  → Runtime Exploration (Maestro MCP / CLI) when needed
  → Selector Resolution (hierarchy-first; visual advisory optional)
  → Validation
  → Structured run artifacts + optional Maestro draft preview
```

**Implemented slice:** `maestro_ai_agent.scenario` performs classification → deterministic canonical parse (+ optional AI normalize), then `planning_adapter.build_parsed_scenario_from_canonical` feeds :class:`ParsedScenario` into existing `plan_intents`. The CLI `scenario-run` sets `ScenarioRunRequest.use_canonical_scenario_normalization=True` (deterministic `normalize_scenario_text` only). Other callers may still use the legacy line parse unless they set the flag.

**Runtime exploration** is used **when** the planner needs **ground truth** from the device (current hierarchy, execution outcome, post-action hierarchy)—not to fabricate a full project flow without evidence.

---

## Three responsibilities

| Responsibility             | Meaning                                                                                                                                                                                                                      |
| -------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Scenario understanding** | Parse + normalize input → canonical steps and intents (mostly deterministic; optional AI assist). Feeds **what to try** on the device; does **not** apply your Maestro repo’s naming or structure rules.                     |
| **Runtime exploration**    | Per step: observe hierarchy, rank selectors, execute when enabled, re-observe, validate, record—**Maestro MCP or CLI** behind a stable provider boundary. This is the **core product surface**: device-grounded behavior.    |
| **Artifact generation**    | Emit **structured run data** (reports, decision logs, hierarchy captures, flow draft bookkeeping) plus **optional Maestro-shaped draft preview** YAML for replay or external tooling—not authoritative “final” project YAML. |

---

## Canonical scenario format

A **single internal representation** (steps, intents, validation goals, metadata) that all input styles converge on. Parsing and planning code should target this format so Gherkin, Turkish prose, and English lists **do not** fork the orchestrator.

Implementation today centers on **`ScenarioInput` → `ParsedScenario` → `StepIntent`** in `maestro_ai_agent.domain`; the **full** normalization story for Gherkin/TR-EN mixed input is **incremental**.

---

## Current capabilities vs deferred

**Implemented (high level):**

- Domain models, deterministic scenario parse/plan, hierarchy CSV parsing, selector ranking, flow draft bookkeeping.
- Orchestrator: planning-only and observe-plan-execute paths; post-execution validation; decision log and run report.
- **MCP-oriented** Maestro integration and **`scenario-run`** for scenario-driven hierarchy-backed execution + artifacts (see [README.md](README.md)).
- **Extension points** for optional **visual / locator advisory** (screenshot + `VisualTargetSuggester`); hierarchy remains primary—see [docs/visual-advisory-fallback.md](docs/visual-advisory-fallback.md).

**Intentionally deferred (non-exhaustive):**

- Full Gherkin and rich multilingual parsers.
- AI scenario-parse fallback wired to a provider.
- **Final** project-aware Maestro export (this repo targets structured artifacts + **draft** YAML preview only; external tools adapt to real projects).
- CLI subprocess Maestro adapter (planned; domain depends on protocols, not transport).
- True self-healing, multi-agent CI farms, WebView-specialized strategies—unless added as dedicated modules.

For **MVP boundaries** in more detail, see [docs/mvp-scope.md](docs/mvp-scope.md).

---

## Related documents

| Document                                                             | Role                                    |
| -------------------------------------------------------------------- | --------------------------------------- |
| [docs/architecture.md](docs/architecture.md)                         | Packages, modules, dependency direction |
| [PROJECT_GOALS.md](PROJECT_GOALS.md)                                 | Goals, non-goals, principles            |
| [docs/mvp-scope.md](docs/mvp-scope.md)                               | MVP in/out scope                        |
| [docs/visual-advisory-fallback.md](docs/visual-advisory-fallback.md) | Locator AI fallback contract            |
| [docs/selector-strategy.md](docs/selector-strategy.md)               | Selector priority                       |
| [docs/maestro-integration.md](docs/maestro-integration.md)           | MCP vs CLI, transport                   |
