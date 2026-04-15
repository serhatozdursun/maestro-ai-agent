# Visual advisory fallback (screenshot + AI-ready port)

## Hierarchy-first

The product path is **deterministic hierarchy → selector proposals → rank → plan → execute**.
Nothing in this document changes that ordering: the first ranking pass is always hierarchy-only.

## When advisory fallback runs

If **all** of the following hold:

1. `ScenarioRunRequest.enable_visual_advisory_fallback` is **true**.
2. The orchestrator was constructed with a non-null `VisualTargetSuggester` implementation.
3. The **first** ranking pass yields **no** primary planned selector (`SKIPPED_NO_SELECTOR` path).
4. The first observation includes **screenshot bytes** (`include_screenshot=True` and the provider returned `image_bytes`).

…then the orchestrator builds a `VisualAdvisoryRequest`, calls `VisualTargetSuggester.suggest`, and—when the response passes a minimum confidence threshold—**merges** suggested visible text / semantic labels into `TargetHints` and runs **one** additional `plan_selector_ranking` pass.

Advisory output is **never** executed as a raw tap selector: it only nudges the existing generator/ranker.

## Why screenshot-only automation is risky

- Pixels are **non-semantic**: small UI changes, themes, or dynamic content break brittle image matchers.
- **Latency and cost**: every fallback may invoke an external model.
- **False confidence**: models can hallucinate labels that are not tappable; we keep **deterministic** ranking as the gate.

Use screenshots as **context for hint extraction**, not as the primary automation surface. **Point** selectors remain a last resort inside the deterministic ranker, not the default outcome of advisory.

## Extension points

| Piece                                                 | Role                                                                   |
| ----------------------------------------------------- | ---------------------------------------------------------------------- |
| `domain.visual_advisory`                              | `VisualAdvisoryRequest` / `VisualAdvisoryResponse` / `BoundingBoxHint` |
| `services.maestro.visual_target_suggester`            | `VisualTargetSuggester` protocol + `NullVisualTargetSuggester`         |
| `orchestrator.visual_advisory_support`                | Build request from `StepRunState` + digest; merge response into hints  |
| `orchestrator.step_processing.rank_and_plan_for_step` | Hook: optional second rank after failed first pass                     |
| `ObservationCycleResult.screenshot`                   | Carries `ScreenshotArtifact` from observe for advisory                 |

## Safest next experiment

1. Implement `VisualTargetSuggester` against your chosen multimodal API (send `VisualAdvisoryRequest.screenshot_bytes` + short text instructions).
2. Return `likely_visible_text` / `likely_semantic_label` with **conservative** `confidence`.
3. Run `ScenarioPlanningOrchestrator(..., visual_target_suggester=...)` with `enable_visual_advisory_fallback=True` and `include_screenshot=True` on a scenario that currently **skips** for lack of hierarchy text.
4. Inspect the **second** ranking in logs / decision log warnings before enabling in CI.

**Deferred:** wiring `likely_region` into geometry-aware proposals; ambiguity detection when a weak primary exists; dedicated `scenario-run` flags for visual advisory (callers can set request fields programmatically today).
