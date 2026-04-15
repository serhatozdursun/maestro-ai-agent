# MVP scope

This MVP defines what the first shippable iteration should do—and what it explicitly defers.

**Integration note:** the repository ships an **MCP-oriented Maestro provider surface** (see [maestro-integration.md](maestro-integration.md)); **MCP transport wiring** and a **CLI subprocess adapter** are still application/roadmap concerns—the domain and orchestrator should depend on `MaestroScreenProvider`, not a specific transport.

## In scope

- **Planning-only orchestrator (default):** `ScenarioPlanningOrchestrator.run_planning_only` with **`PlanningRunMode.PLANNING_ONLY`**: observe hierarchy via `MaestroScreenService`, rank selectors, choose a primary candidate, write **`RunReport`** + **`RunDecisionLogEntry`**, optional **`FlowDraftBuilder.append_planned`**. No provider actions.
- **Limited execution + validation (current code):** `run_observe_plan_execute` with **`PlanningRunMode.OBSERVE_PLAN_EXECUTE`** may call **`tap_on`** / **`input_text`**, then **re-observes** the hierarchy and runs **deterministic** checks against **`ValidationGoal`** signals (and small fallbacks when goals are empty). Outcomes are honest: **`VALIDATED`**, **`VALIDATION_FAILED`**, **`VALIDATION_INCONCLUSIVE`**, or **`VALIDATION_SKIPPED`** (e.g. empty post-action hierarchy). **No** retries, **no** full autonomous exploration, **no** final Maestro YAML from this orchestrator path. The **`scenario-run`** CLI writes **`maestro_draft_preview.yaml`** from the accumulated flow draft (review-only; not the full productized YAML export pipeline). `ActionResult.ok` is only tool-level success; UI validation can still fail or be inconclusive.
- **Single scenario**: one natural-language description per run.
- **Single session**: one continuous app session from launch through the described goal state (or failure).
- **One platform at a time**: Android or iOS, selected explicitly for the run.
- **Screen-by-screen exploration**: one step at a time—hierarchy-backed selector choice, action, validation—then advance; not blind generation of a full flow without per-step feedback.
- **Basic Maestro actions** (via Maestro tools): launch app, tap, input text, assert visible (and equivalents Maestro supports for the chosen platform).
- **Exploration loop**: inspect hierarchy before each interaction; prefer stable selectors (`id`, then `text`, then relational refinements); see [selector-strategy.md](selector-strategy.md).
- **Validation**: after each action, check a simple signal (e.g. expected text visible, screen change) before appending the next YAML step.
- **Artifacts**: structured runtime report, selector decision log, generated Maestro YAML suitable for human review and re-execution.

## Out of scope (MVP)

- Parallel scenarios, multi-device farms, or scheduled CI without a separate runner.
- Automatic repair across major UI redesigns (“true” self-healing).
- Deep WebView-specific selector strategies unless added as a dedicated module later.
- Full natural-language understanding beyond structured intents derived from the scenario (keep the planner explicit and auditable).

## Definition of done (MVP)

- A developer can install the package, point at an app and platform, supply a scenario, and obtain a YAML flow plus logs that explain selector choices.
- The YAML is syntactically valid for Maestro and matches the steps actually attempted during the exploratory run (modulo manual edits the user might make afterward).

Until the **execution** path lands, the repository still delivers **structured planning artifacts** (run report + decision log + planned flow draft rows) that a future executor can consume without pretending steps were executed on device.
