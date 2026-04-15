# maestro-ai-agent

**Experimental but production-minded** Python **Maestro orchestration runtime** for mobile apps using [Maestro](https://maestro.mobile.dev/). It runs a deterministic **observe → plan → execute → validate** loop on a **real device**, resolves selectors from hierarchy-first evidence, executes supported actions, and writes auditable artifacts (hierarchy captures, ranking traces, execution outcomes, and validation evidence).

**Maestro YAML emitted by this repo is a draft preview only**, not the authoritative product output. It is a convenience for replay or hand-off. **External AI providers/backends** (via Cursor, Claude, Copilot, and similar tools) are expected to transform the structured runtime outputs into project-specific Maestro flows; naming, environments, subflows, and layout stay outside this runtime. See [ARCHITECTURE.md](ARCHITECTURE.md) and [PROJECT_GOALS.md](PROJECT_GOALS.md).

This repository is **not** a one-shot “generate the whole flow” tool. The **`scenario-run`** CLI is a **deterministic-first exploration runtime** on a real device (canonical normalization → orchestrator planning → observe / act / validate per line). Parsing, planning, selector ranking, execution mapping, and validation are deterministic-first; AI is only in explicit fallback/advisory roles.

## What we are building

- **Explore** the live app: launch (where configured), wait for stable hierarchy, observe, act, re-observe.
- **Capture** view hierarchy (CSV → structured snapshot) and optional screenshots for context.
- **Resolve** selectors using hierarchy-first ranking and clear decision logging—not a blind “generate the whole flow” pass.
- **Execute** mapped actions via Maestro (MCP today for `scenario-run`; CLI adapter **planned**).
- **Record** structured run data: phases, candidates, chosen actions, provider results, post-action validation.
- **Optionally emit** minimal **Maestro-shaped YAML** as a **draft preview** for review or for an external tool to rewrite into your real project—**not** as final production flow output.

**AI** is intended for **fallback only**: e.g. optional parsing assistance when confidence is low, optional **visual/locator hints** when hierarchy is insufficient ([docs/visual-advisory-fallback.md](docs/visual-advisory-fallback.md)), and possibly **failure explanation** later—**not** as the primary implementation for parsing, ranking, orchestration, or validation **cores**.

## How this runtime fits into an AI-assisted workflow

This repo focuses on **device-grounded exploration and evidence**. It does **not** read your Maestro project or apply your team’s conventions.

Typical pipeline:

```
human scenario (intent)
        ↓
maestro-ai-agent (orchestration runtime on device)
        ↓
exploration_report.json   ← structured run / selector / validation data
        ↓
external AI backend/tooling (Cursor, Claude, Copilot, …)
        ↓
project-specific Maestro flow
```

**`exploration_report.json`** is the primary machine-readable exploration report. **`scenario-run`** writes it under `--output-dir`, together with per-step hierarchy CSVs under `steps/NN/`, **`canonical_scenario.json`**, and **`maestro_draft_preview.yaml`** when the accumulated flow draft can be mapped. The **contract** is: **structured exploration output → external AI → real repo**.

## Example input (tested style)

**English — step list**

> 1. Tap "Sign in"  
> 2. Input email  
> 3. Tap "Continue"

Today’s **deterministic** parsers focus on **line-oriented** scenario text. Richer free-form natural language, Gherkin, and multilingual normalization are **feature plan** items, not validated behavior yet.

## Current status

- **Domain & orchestrator:** `ScenarioInput` → `ParsedScenario` → `StepIntent` (default: `parse_scenario_input`). Optional: `ScenarioRunRequest.use_canonical_scenario_normalization=True` runs deterministic canonical normalization first, then the same planner loop. Hierarchy CSV → selector ranking; planning-only and observe-plan-execute; post-action validation; run report and decision log. See [docs/architecture.md](docs/architecture.md).
- **Maestro integration:** **MCP-oriented** provider surface and **`maestro-ai-agent scenario-run`** for **multi-line** scenarios with artifacts (`exploration_report.json`, `steps/*/pre_hierarchy.csv` / `post_hierarchy.csv`, **`maestro_draft_preview.yaml`** when mappable). **CLI subprocess** adapter remains **planned** ([docs/maestro-integration.md](docs/maestro-integration.md)).
- **Visual advisory:** optional second ranking pass behind `VisualTargetSuggester` (off by default); hierarchy stays primary.
- **Not done yet:** full multi-format + multilingual normalization, AI parse provider wiring, richer reporting beyond the current exploration contract.

## MVP scope (summary)

Single scenario, single session, one platform; basic actions (launch, tap, input, assert visible); step-by-step exploration with validation signals. **Detail:** [docs/mvp-scope.md](docs/mvp-scope.md).

## Non-goals (for now)

- **Owning** project-specific Maestro layout, naming, environments, or subflows (that stays with your repo + external AI).
- Multi-agent orchestration or fully autonomous regression generation.
- Cloud execution pipelines as a built-in product surface.
- “True” self-healing beyond documented fallbacks.
- WebView-specialized logic unless added as a dedicated module.

## High-level architecture (code)

Layers stay separated so planning, Maestro integration, selector ranking, and draft preview emission can evolve independently. **Package map and data flow:** [docs/architecture.md](docs/architecture.md). **Product intent and AI boundaries:** [ARCHITECTURE.md](ARCHITECTURE.md).

## Cursor / AI-assisted development

- **Root rules:** [.cursorrules](.cursorrules) (alignment with deterministic-first design).
- **Editor rules:** [`.cursor/rules/maestro-ai-agent.mdc`](.cursor/rules/maestro-ai-agent.mdc) (Maestro, selectors, validation habits).

## Requirements

- Python 3.11+

## Getting started (development)

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env
pytest
ruff check src tests
black --check src tests
```

```bash
maestro-ai-agent --help
```

### CLI from any directory (no `source .venv`)

Install with your **system Python 3.11** (Homebrew: `/opt/homebrew/bin/python3.11`) so the `maestro-ai-agent` script lands in your user bin:

```bash
cd /path/to/maestro-ai-agent
python3.11 -m pip install --user -e .
```

Then put **user scripts** on `PATH` (macOS default for this layout is `~/Library/Python/3.11/bin`). For example in `~/.zshrc`:

```bash
export PATH="$HOME/Library/Python/3.11/bin:$PATH"
```

Open a **new** terminal (or `source ~/.zshrc`). The command works from **any working directory**; editable install still reads sources from this repo.

**Note:** `pipx` is fine too if your `pipx`/Python stack is healthy. If `pipx install` crashes inside `pyexpat` / `libexpat`, use the `python3.11 -m pip install --user` path above instead of fighting a broken interpreter mix.

## Scenario run (device-backed)

Runs a **multi-line** scenario end-to-end on a real device: **preflight** `launch_app`, hierarchy stability wait, optional known blocking-popup handling, then for each line **observe** hierarchy → rank selectors → execute supported actions → re-observe → deterministic validation (stops on first hard failure by default). Uses a **minimal MCP stdio client** to spawn `maestro mcp` (override with `--mcp-command`) and speaks **newline-delimited JSON** (one JSON-RPC object per line). **Prerequisites:** Maestro CLI on `PATH` and a connected device or emulator.

**Scenario input (exactly one):** `--scenario-file`, `--scenario` (alias `--scenario-text` / `-S`), or repeated `--step` (order preserved). See [docs/ai-scenario-grammar.md](docs/ai-scenario-grammar.md).

**Example:**

```bash
maestro-ai-agent scenario-run \
  --app-id com.example.app \
  --platform android \
  --device YOUR_DEVICE_ID \
  --scenario-file ./scenario.txt \
  --output-dir ./scenario-out
```

**Artifacts** (under `--output-dir`): **`exploration_report.json`** (primary hand-off for tooling), **`canonical_scenario.json`**, **`steps/NN/pre_hierarchy.csv`** / **`post_hierarchy.csv`**, and **`maestro_draft_preview.yaml`** when the flow draft maps—a **draft preview** in Maestro-native shapes—**review** before relying on it.

**Honest limits:** MCP protocol version may need `--mcp-protocol-version`; read timeouts are Unix-first (`select`); Maestro may install a driver on first use. See `maestro-ai-agent scenario-run --help`.

**Selector hints:** Prefer **quoted** literals in scenario lines (e.g. `Tap 'UK'`). If you see `skipped_no_selector`, inspect hierarchy CSVs under `steps/` and **`exploration_report.json`**.

**Tap context (optional):** Lines such as `Tap 'Shop' on the tab bar` attach a **soft** container hint to deterministic ranking (not a hard filter). When two on-screen targets collide, use `--ambiguity-strategy suggest` to skip auto-picking a tap and inspect `ranked_candidates` (with optional coarse `--show-target-regions` hints) in **`exploration_report.json`**.

## Documentation

| Document | Description |
|----------|-------------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Product intent, pipeline, where AI is allowed / not |
| [PROJECT_GOALS.md](PROJECT_GOALS.md) | Goals, non-goals, near-term vs deferred |
| [docs/architecture.md](docs/architecture.md) | Components, boundaries, data flow in code |
| [docs/mvp-scope.md](docs/mvp-scope.md) | MVP boundaries and deliverables |
| [docs/maestro-integration.md](docs/maestro-integration.md) | MCP vs CLI strategy, transport, hierarchy CSV |
| [docs/selector-strategy.md](docs/selector-strategy.md) | Selector priority and anti-patterns |
| [docs/visual-advisory-fallback.md](docs/visual-advisory-fallback.md) | Screenshot-backed locator advisory (optional) |
| [docs/scenario-format.md](docs/scenario-format.md) | Scenario conventions and deterministic parsing notes |
| [docs/ai-scenario-grammar.md](docs/ai-scenario-grammar.md) | AI-friendly deterministic step grammar + CLI input surfaces |
| `maestro_ai_agent.scenario` | Scenario understanding: raw text → canonical steps → optional AI; `planning_adapter` bridges to `ParsedScenario` / `plan_intents` (`scenario-run` enables canonical normalization) |

## License

MIT (see `pyproject.toml`).
