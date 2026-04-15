# Selector strategy

Selectors must be **stable**, **unique enough**, and **explainable** in the decision log. The hierarchy is the source of truth; screenshots are for human context and debugging, not primary targeting.

## Runtime vs artifact (important)

- **Candidate ranking / primary plan / emitted YAML** still prefer **stability** (typically **id** first when unique), so generated flows stay maintainable.
- **Runtime tap execution** (provider `tap_on` retries) uses a **separate attempt order**: **text → id → relational → point**, because Maestro often resolves visible labels reliably at tap time (e.g. dismissals), even when the saved flow should keep a stable id.
- **Per-candidate tap delivery** is **two-stage**: (1) direct MCP **`tap_on`**; (2) if that is **ineffective** (provider failure, hierarchy unchanged, or known blocking dialog still visible), **`run_flow`** with a **minimal one-step flow** built from the current `appId` and the same selector (`tapOn` shorthand for text, or `id` / `point` maps). Post-action hierarchy validation remains required either way.

**Input fields** are not forced through text-first retries unless the mapping already makes that appropriate.

## Priority order (ranking / YAML-oriented)

1. **id** — Prefer resource IDs / accessibility identifiers when present and unique.
2. **text** — Visible, user-facing copy (from Maestro `text=`, `accessibilityText=`, etc.; see hierarchy CSV parser) that is unlikely to change every release.
3. **text + traits/state** — Disambiguate when the same text appears multiple times.
4. **Relational selectors** — Prefer hierarchy structure: `childOf`, `containsChild`, `containsDescendants`, anchored off a stable parent. Use spatial relations (`above`, `below`, `leftOf`, `rightOf`) only when anchored to a stable element.
5. **point** — Last resort when hierarchy-based targeting is not possible.

## Rules

- Prefer a unique ID over any text match **for ranking and committed flow steps** (not for the ordered list of runtime tap retries; see above).
- If using text, confirm it is visible in the hierarchy and likely stable (avoid volatile timestamps or dynamic placeholders unless intentionally parameterized).
- If multiple nodes match, refine with relational selectors rather than guessing coordinates.
- Log both the primary hypothesis and at least one fallback for auditability.

## Anti-patterns

- Using **point** when `id` or reliable `text` exists.
- Overly deep relational chains that are brittle and hard to read in generated YAML.
- Guessing selectors from screenshots alone when the hierarchy is available.
- Selecting by dynamic content (e.g. full timestamps) without explicit scenario parameters.

## Alignment with Maestro

Generated flows should use Maestro’s selector expressions consistently with this priority, so flows remain readable and maintainable for human reviewers.

## Implemented deterministic layer (`domain.selectors`)

The codebase now includes a **pure domain** pipeline that:

- infers modest `TargetHints` from a `StepIntent` (`infer_target_hints`);
- generates `ProposedSelector` rows from a `HierarchySnapshot` (`generate_proposals`);
- scores and orders them into `SelectorRankingResult` / `RankedSelectorCandidate` with `SelectorExplanation` reason codes (`rank_selector_proposals`, `plan_selector_ranking`).

**What exists today:** `id`, `text`, basic **relational** disambiguation when duplicate visible text shares a parent with a stable `resource-id`, and **point** proposals derived from `bounds` (heavily down-ranked).

**What is deferred:** rich `text + traits/state` combinations (the enum value exists, but generation is not fully wired yet), deep relational graphs (`childOf` chains), and any LLM-based re-ranking. A future LLM should **augment** (annotate / re-score) rather than replace this deterministic core so logs stay auditable.
