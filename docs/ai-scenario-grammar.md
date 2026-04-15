# AI scenario grammar

This document defines the **supported, deterministic** scenario surface for **humans and automation clients** when authoring steps for `maestro-ai-agent`. It is **not** a full natural-language spec: lines that do not match these shapes fall through to legacy heuristics or `unknown` canonical actions.

## Purpose

- Give **stable, copy-pastable** step forms that normalize to a **canonical scenario** (`CanonicalStep`: `action`, `target`, `value`, …).
- Keep parsing **rule-based** (regex + keyword order), so runs are **auditable** and reproducible.
- Align CLI inputs (`--scenario-file`, `--scenario`, repeated `--step`) so they **converge to one scenario string** before normalization.

## Design goals

1. **Deterministic first** — no LLM required to interpret grammar lines.
2. **Lightweight** — one primary verb per line; limited parameters.
3. **Quoted literals** — UI text and search strings use **straight single or double quotes** where a literal is required.
4. **Stable slugs** — canonical `action` values use `snake_case` (e.g. `press_key`, `scroll_until_visible`).
5. **Bounded runtime** — grammar may map to **Maestro-native** primitives (`tapOn`, `inputText`, `pressKey`, `swipe`, `scrollUntilVisible`, optional taps) via **fixed templates** in code, not arbitrary user YAML.

## Supported step types (canonical `action`)

| Canonical `action`     | Typical source lines                                           | `target` / `value`                                                                                                      |
| ---------------------- | -------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `launch_app`           | `Launch app`, `LaunchApp`, `open app`                          | —                                                                                                                       |
| `tap`                  | `Tap 'Search'`, `Press 'OK'`, `Tap 'Shop' on the tab bar`      | quoted label → `target`; optional `on` / `in` / `from` + phrase → `target_container_hint` (slug) + raw qualifier fields |
| `input_text`           | `Enter 'shoe'`, `Type "x"`, `Input 'y'`                        | quoted text → `target`                                                                                                  |
| `press_key`            | `Press Enter`, `Press key 'tab'`                               | key name → `value` (Maestro key, e.g. `enter`)                                                                          |
| `assert_visible`       | `AssertVisible 'Results'`, `Assert visible "Results"`          | literal → `target`                                                                                                      |
| `assert_not_visible`   | `AssertNotVisible 'Loading'`, `Assert not visible "Spinner"`   | literal → `target`                                                                                                      |
| `scroll`               | `Scroll Down`, `Scroll up`, `ScrollDown`                       | direction → `value` (`down` / `up` / `left` / `right`)                                                                  |
| `swipe`                | `Swipe left`, `Swipe Right` (plain directional line)           | direction → `value`; **scenario-run** maps to the same Maestro directional `swipe` YAML as `scroll`                     |
| `swipe` (targeted)     | `Swipe left on 'Story card'`, `Swipe 'Story card' left`        | quoted label → `target`; direction → `value`; Maestro `swipe` with `from: text:`                                        |
| `scroll_until_visible` | `ScrollUntilVisible 'Checkout'`, `Scroll until visible 'Item'` | literal → `target`                                                                                                      |
| `dismiss_blocker`      | `Dismiss any popup and continue`, `Dismiss popup dialog`       | —                                                                                                                       |

Other legacy verbs (`back`, shopping heuristics, Gherkin, Turkish cues) may still exist in the deterministic parser but are **outside** this grammar table unless listed above.

## Preferred canonical style

- **One step per line** after normalization (list markers and `#` comments are stripped like elsewhere).
- **Title Case or sentence case** for grammar keywords is accepted (`Press Enter`, `press enter`).
- **Quoted literals** for user-visible strings: `Tap 'Cart'`, `Assert visible "Total"`.

## Optional tap context (soft ranking hints)

After the quoted literal, you may add a **contextual qualifier** using `on`, `in`, or `from` followed by a short phrase. The phrase is **not** a hard filter: it nudges deterministic selector ranking when hierarchy/geometry supports it.

Examples:

- `Tap 'Shop' on the tab bar`
- `Tap 'Close' in the popup`
- `Tap 'Filter' from the modal`
- `Tap 'Search' in the top bar`

Synonyms (deterministic) map to internal slugs such as `tab_bar`, `header`, `modal`, `footer`, `drawer`, `card`, `search_field` (see `domain/selectors/tap_qualifier.py`).

## Quoted text guidance

- Use **ASCII quotes** `'` or `"` around UI copy and search strings.
- Avoid embedding the same quote character inside the literal without switching quote styles (parser uses a simple first-match extract).
- If a line has **no** quoted literal where one is required (e.g. `Assert visible` with no quotes), planning may **skip** execution for that step.

## Unsupported / deferred (by design)

- **Arbitrary Maestro YAML** or passthrough command lists from the user.
- **Multi-tap macros**, **variables**, **data tables**, **examples** blocks.
- **Coordinates** as a grammar-first choice (still handled elsewhere as lower-priority selectors).
- **Per-platform key sets** beyond what Maestro documents for `pressKey`.
- **Rich Gherkin** (full feature files) — only the existing Gherkin-lite path applies.
- **Automatic multi-popup sweeps** between steps — known dismiss patterns remain **preflight-only** today; `dismiss_blocker` is a **bounded optional-tap** `run_flow` template, not full OS sheet handling.

## Examples

```text
Launch app
Tap 'Search'
Enter 'shoe'
Press Enter
Assert visible 'Results'
Assert not visible 'Loading'
Scroll Down
Swipe left
Swipe 'Story card' left
Scroll until visible 'Checkout'
Dismiss any popup and continue
```

## Input convergence (`scenario-run`)

Exactly **one** of the following must be provided:

1. **`--scenario-file <path>`** — file body (UTF-8), newline-separated steps (same as inline).
2. **`--scenario "<text>"`** — inline multi-line string (shell quoting as usual).
3. **Repeated `--step "…"`** — each flag is one step; **order is preserved** and steps are joined with `\n`.

If **more than one** source is active, the CLI **exits with an error** (no silent precedence).

All three paths produce **one** `scenario_text` string, then:

`normalize_scenario_text` → `CanonicalScenario` → `build_parsed_scenario_from_canonical` → `plan_intents` → orchestrator.

So the **same logical lines** in any of the three surfaces yield the **same** canonical + planner pipeline, modulo file encoding and line endings.

## Related docs

- [scenario-format.md](scenario-format.md) — broader scenario conventions.
- [selector-strategy.md](selector-strategy.md) — hierarchy-first selector policy.
