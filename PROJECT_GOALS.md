# Project goals

Concise alignment doc for contributors and AI-assisted development. **Architecture narrative:** [ARCHITECTURE.md](ARCHITECTURE.md). **MVP detail:** [docs/mvp-scope.md](docs/mvp-scope.md).

---

## Project goal

Build **maestro-ai-agent** as a **Maestro orchestration runtime** that:

- **Understands** test scenarios (multiple input styles and languages; converging on a canonical representation over time).
- **Interacts** with a **real device** using Maestro (MCP today; CLI adapter planned behind the same provider idea).
- **Resolves selectors** using the **view hierarchy** and deterministic ranking—not opaque LLM-authored locators as the default path.
- **Executes actions** deterministically through an orchestrator-centered observe-plan-execute loop, with clear provider and validation records.
- **Records structured run artifacts** (hierarchy evidence, rankings, decisions, validation outcomes, flow draft bookkeeping).

**External AI tools/providers** (Cursor, Claude, Copilot, and similar) are expected to consume those artifacts and produce **project-specific** Maestro flows. This repository **does not** implement project rules, naming conventions, environment matrices, or subflow wiring.

---

## Key capabilities (target)

- **Input breadth:** natural language, step lists, Gherkin/BDD-style text, Turkish, English, and mixed Turkish/English—**converging on one canonical scenario format** as the hub for intents.
- **Deterministic core:** parsing, planning, hierarchy handling, selector ranking, validation rules; **draft** Maestro-shaped preview where the code emits YAML (Maestro-native shapes, not final project output).
- **Runtime grounding:** Maestro (MCP and/or CLI behind a provider boundary) for hierarchy and actions when the pipeline needs device truth—the **primary** value of the tool.
- **Optional AI fallbacks:** parsing assistance, visual/locator hints after hierarchy-first failure, and later failure explanation—**never** replacing the orchestrator/runtime core pipeline.

---

## Non-goals

- **Generating final, production-ready Maestro flows** tailored to a specific repository (that is for external AI + your project).
- **Understanding or applying project-specific conventions** (naming, folder layout, shared subflows, env files, CI glue).
- Replacing the **selector ranker**, **orchestrator state machine**, or **validation core** with LLM-generated logic.
- **One-shot** “generate the entire flow from a paragraph” without per-step structure, validation, and structured step assembly.
- Multi-agent orchestration, full autonomous regression generation, or cloud execution farms **as part of this repo’s core** (external runners may consume outputs later).
- **Overengineered** abstractions ahead of proven need; see design principles in [ARCHITECTURE.md](ARCHITECTURE.md).

---

## Near-term goals

- Harden **canonical scenario path**: raw text → `maestro_ai_agent.scenario` (`normalize_scenario_text` / `build_parsed_scenario_from_canonical`) → `ParsedScenario` → `StepIntent` → orchestrator → **structured artifacts** (legacy `parse_scenario_input` path remains).
- Keep **`scenario-run`** stable as the **hierarchy-first** runtime entrypoint; extend **only** through clear ports (e.g. `VisualTargetSuggester`, provider protocols).
- **Draft preview** Maestro YAML that is syntactically valid and **idiomatic** where the code emits it—clearly secondary to JSON/hierarchy **exploration reports**.
- Tests and docs that stay **honest** about what is implemented vs planned.

---

## Deferred goals

- Rich **Gherkin** and **multilingual** deterministic parsers + confidence scoring + optional AI parse fallback.
- **CLI** Maestro adapter alongside MCP.
- **Geometry / region** hints from vision models wired into proposals (response types may exist before behavior).
- Deeper **WebView** selector strategies and **self-healing** beyond documented fallbacks.

---

## Design principles

1. **Deterministic first, AI as fallback.**
2. **Canonical scenario format** as the hub between diverse inputs and the orchestrator.
3. **Runtime exploration when needed**—not mandatory for every YAML line.
4. **Structured artifacts first**; **Maestro-native draft preview** YAML only where it helps replay or external hand-off—not opaque LLM prose and not “final project flow.”
5. **Small, safe changes**; preserve working paths (especially **`scenario-run`** and the orchestrator observe-plan-execute loop).
6. **Documentation** updated when architecture or integration posture changes ([README.md](README.md), [ARCHITECTURE.md](ARCHITECTURE.md), `docs/`).
