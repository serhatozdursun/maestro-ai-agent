# Scenario format

Scenarios are **natural-language** descriptions of what a human tester would do on device. The tool will later parse or structure them into ordered **intents**; this document defines conventions so scenarios stay consistent and machine-assistable.

## Required inputs (run metadata)

- **`appId`**: Application identifier (e.g. Android application ID or iOS bundle id), as required by Maestro for launch.
- **`platform`**: `android` or `ios` (or the exact enum the implementation standardizes on).

The scenario body is separate text describing user actions and expectations.

## Writing style

- Use short, imperative steps: “Open the app”, “Dismiss the onboarding sheet”, “Log in with valid credentials”.
- Call out **stable landmarks**: screen titles, primary buttons, key labels that appear in the hierarchy.
- State **expected outcomes** after important transitions: “Home feed is visible”, “Error message shows invalid email”.
- Prefer one intent per sentence or bullet; avoid long paragraphs mixing unrelated goals.

## Example (illustrative)

```text
Launch the retail app.
If a location permission dialog appears, deny it.
Tap "Sign in".
Enter email "user@example.com" into the email field.
Enter password "hunter2" into the password field.
Tap the primary submit button.
Assert that the text "Welcome back" is visible on the home screen.
```

## Parameters

- Use quoted literals for data you want echoed exactly in generated steps (emails, SKUs, search terms).
- The implementation may later support explicit parameter blocks (YAML/JSON); until then, quotes and clear labels help the planner map values to `inputText` steps.

## Deterministic first-pass parsing (implemented)

The library ships a **simple line-based parser** (`parse_scenario_input` in `maestro_ai_agent.domain.parse_scenario`) that:

- splits the body on newlines;
- skips blank lines and lines whose trimmed text starts with `#`;
- strips common list markers (`-`, `*`, `•`, `1.` / `1)` style prefixes, including repeated markers);
- preserves the original **source line number** for each retained step (leading/trailing blank lines in the file are kept so line numbers stay meaningful—`ScenarioInput.scenario_text` is not glob-trimmed).

This parser is intentionally easy to **swap** for an LLM-assisted parser later: downstream code should depend on `ParsedScenario` / `ScenarioStep`, not on the parser implementation name.

## Non-goals of the format

- This is not a formal grammar yet; keep prose clear. Richer NLU belongs in alternate parsers behind the same `ParsedScenario` contract.
