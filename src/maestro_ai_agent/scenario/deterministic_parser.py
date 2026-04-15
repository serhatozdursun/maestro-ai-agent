"""First-pass deterministic normalization to :class:`CanonicalScenario`."""

from __future__ import annotations

import re

from maestro_ai_agent.domain.selectors.tap_qualifier import find_tap_qualifier_in_text
from maestro_ai_agent.scenario.canonical_model import CanonicalScenario, CanonicalStep
from maestro_ai_agent.scenario.classifier import (
    InputStructure,
    ScenarioInputProfile,
    classify_scenario_text,
)

_LEADING_ENUM = re.compile(
    r"^\s*(?:" r"[*\-•]+\s*" r"|\d+[.)]\s*" r")\s*",
    flags=re.UNICODE,
)
_QUOTED = re.compile(r"['\"](?P<body>[^'\"]+)['\"]")
_GHERKIN_CLAUSE = re.compile(
    r"^\s*(Given|When|Then|And|But)\s+(?P<body>.+)$",
    re.IGNORECASE,
)
_SCENARIO_TITLE = re.compile(r"^\s*Scenario:\s*(?P<title>.+?)\s*$", re.IGNORECASE)


def _strip_markers(line: str) -> str:
    previous = None
    current = line
    while previous != current:
        previous = current
        current = _LEADING_ENUM.sub("", current)
    return current.strip()


def _first_quote(text: str) -> str | None:
    m = _QUOTED.search(text)
    return m.group("body") if m else None


def _iter_body_lines(text: str) -> tuple[list[tuple[int, str]], list[str]]:
    warnings: list[str] = []
    out: list[tuple[int, str]] = []
    for line_no, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        normalized = _strip_markers(stripped)
        if not normalized:
            warnings.append(f"Line {line_no} empty after marker strip; skipped.")
            continue
        out.append((line_no, normalized))
    if not out:
        warnings.append("No non-empty lines.")
    return out, warnings


def _step(
    action: str,
    target: str | None,
    value: str | None,
    index: int,
    source: str,
    *,
    target_qualifier_phrase_raw: str | None = None,
    target_container_hint: str | None = None,
    tap_qualifier_preposition: str | None = None,
) -> CanonicalStep:
    return CanonicalStep(
        action=action,
        target=target,
        value=value,
        index=index,
        source_text=source,
        target_qualifier_phrase_raw=target_qualifier_phrase_raw,
        target_container_hint=target_container_hint,
        tap_qualifier_preposition=tap_qualifier_preposition,
    )


_KEY_ALIASES = {
    "enter": "enter",
    "return": "enter",
    "tab": "tab",
    "backspace": "backspace",
    "back": "back",
    "escape": "back",
    "esc": "back",
}


def _normalize_press_key_token(token: str) -> str:
    t = (token or "").strip().lower().replace(" ", "")
    return _KEY_ALIASES.get(t, t)


def _parse_imperative_line(line: str) -> CanonicalStep:
    """English / Turkish / mixed one-liners (shopping flow cues + common Maestro NL)."""
    raw = line.strip()
    lower = raw.lower()

    # --- AI scenario grammar (docs/ai-scenario-grammar.md), before generic heuristics ---
    if re.search(r"(?i)^dismiss\b", raw) and re.search(
        r"(?i)\b(popup|dialog|blocker|continue)\b",
        raw,
    ):
        return _step("dismiss_blocker", None, None, 0, raw)
    if re.match(r"(?i)^launchapp\b", raw) or lower.startswith("open app"):
        return _step("launch_app", None, None, 0, raw)
    if re.match(r"(?i)^assertnotvisible\b", raw):
        q = _first_quote(raw)
        return _step("assert_not_visible", q, None, 0, raw)
    m_avn = re.match(r"(?i)^assert\s+not\s+visible\s+(.+)$", raw)
    if m_avn:
        tail = m_avn.group(1).strip()
        q = _first_quote(tail) or tail.strip("'\"").strip() or None
        return _step("assert_not_visible", q, None, 0, raw)
    if re.match(r"(?i)^assertvisible\b", raw):
        q = _first_quote(raw)
        if q:
            return _step("assert_visible", q, None, 0, raw)
    m_av = re.match(r"(?i)^assert\s+visible\s+(.+)$", raw)
    if m_av:
        tail = m_av.group(1).strip()
        q = _first_quote(tail) or tail.strip("'\"").strip() or None
        return _step("assert_visible", q, None, 0, raw)
    m_suv = re.match(r"(?i)^scrolluntilvisible\s+(.+)$", raw) or re.match(
        r"(?i)^scroll\s+until\s+visible\s+(.+)$",
        raw,
    )
    if m_suv:
        tail = m_suv.group(1).strip()
        q = _first_quote(tail) or tail.strip("'\"").strip() or None
        return _step("scroll_until_visible", q, None, 0, raw)
    m_sc = re.match(r"(?i)^scroll\s+(down|up|left|right)\s*$", raw)
    if m_sc:
        return _step("scroll", None, m_sc.group(1).lower(), 0, raw)
    if re.match(r"(?i)^scrolldown\b", raw):
        return _step("scroll", None, "down", 0, raw)
    if re.match(r"(?i)^scrollup\b", raw):
        return _step("scroll", None, "up", 0, raw)
    if re.match(r"(?i)^press\s+enter\s*$", raw):
        return _step("press_key", None, "enter", 0, raw)
    m_pk = re.match(r"(?i)^press\s+key\s+['\"]?([^'\"]+)['\"]?\s*$", raw)
    if m_pk:
        return _step(
            "press_key",
            None,
            _normalize_press_key_token(m_pk.group(1)),
            0,
            raw,
        )

    if lower.startswith(("assert ", "verify ", "ensure ", "check that ", "assert that")):
        return _step("assert", _first_quote(raw) or raw, None, 0, raw)
    if "görün" in lower or "görüntü" in lower or "doğrula" in lower:
        return _step("assert", _first_quote(raw) or raw, None, 0, raw)
    if re.search(r"(?i)^login\s+ol$|^giriş\s+yap$", raw):
        return _step("login", None, None, 0, raw)
    m = re.search(r"(?i)^(.+?)'e\s+git$", raw)
    if m:
        return _step("navigate", m.group(1).strip(), None, 0, raw)
    m = re.search(r"(?i)^(.+?)\s+ara$", raw)
    if m:
        return _step("search", m.group(1).strip(), None, 0, raw)
    if re.search(r"(?i)ilk\s+ürünü\s+aç", raw):
        return _step("open_first_product", None, None, 0, raw)
    if re.search(r"(?i)cart'a\s+ekle|sepete\s+ekle", raw):
        return _step("add_to_cart", "cart", None, 0, raw)
    if lower.startswith("launch ") or lower in {"launch app"}:
        return _step("launch_app", None, None, 0, raw)
    if any(lower.startswith(p) for p in ("tap ", "click ", "dokun ")):
        tq = find_tap_qualifier_in_text(raw)
        if tq:
            return _step(
                "tap",
                tq.label,
                None,
                0,
                raw,
                target_qualifier_phrase_raw=tq.qualifier_phrase_raw,
                target_container_hint=tq.container_hint,
                tap_qualifier_preposition=tq.preposition,
            )
        return _step("tap", _first_quote(raw), None, 0, raw)
    if lower.startswith("press ") and not re.match(r"(?i)^press\s+(enter|key)\b", raw):
        tq = find_tap_qualifier_in_text(raw)
        if tq:
            return _step(
                "tap",
                tq.label,
                None,
                0,
                raw,
                target_qualifier_phrase_raw=tq.qualifier_phrase_raw,
                target_container_hint=tq.container_hint,
                tap_qualifier_preposition=tq.preposition,
            )
        return _step("tap", _first_quote(raw), None, 0, raw)
    if any(token in lower for token in ("enter ", "type ", "input ")):
        return _step("input", _first_quote(raw), None, 0, raw)
    if lower.startswith(("go back", "navigate back", "press back")) or lower == "back":
        return _step("back", None, None, 0, raw)
    if "swipe" in lower:
        return _step("swipe", None, None, 0, raw)

    return _step("unknown", raw, None, 0, raw)


def _semantic_from_gherkin_clause(
    clause_kind: str,
    body: str,
) -> tuple[str, str | None, str | None]:
    """Map a Gherkin clause body to (action, target, value)."""
    lower = body.lower()
    quoted = _first_quote(body)

    ck = clause_kind.lower()
    if ck == "given":
        if "logged in" in lower or "giriş" in lower:
            return "login", None, None
        return "given_context", body.strip(), None

    if ck in {"when", "and"}:
        if "add" in lower and "cart" in lower:
            return "add_to_cart", "cart", None
        if "searches for" in lower or re.search(r"\bsearch(es)?\s+for\b", lower):
            return "search", quoted or body.strip(), None
        if "tap" in lower or "press" in lower or "clicks" in lower:
            return "tap", quoted, None
        if "input" in lower or "enter" in lower or "type" in lower:
            return "input", quoted, quoted
        return "when_action", body.strip(), None

    if ck in {"then", "and"}:
        if "see" in lower or "visible" in lower or "displayed" in lower:
            return "assert", quoted or body.strip(), None
        if "add" in lower and "cart" in lower:
            return "add_to_cart", "cart", None
        return "assert", quoted or body.strip(), None

    return "unknown", body.strip(), None


def _parse_gherkin(text: str) -> CanonicalScenario:
    warnings: list[str] = []
    title: str | None = None
    steps: list[CanonicalStep] = []
    idx = 0
    last_kw = "Given"

    for line_no, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        m_sc = _SCENARIO_TITLE.match(stripped)
        if m_sc:
            title = m_sc.group("title").strip()
            continue
        m = _GHERKIN_CLAUSE.match(stripped)
        if not m:
            warnings.append(f"Line {line_no} skipped (not Gherkin-shaped): {stripped[:60]}")
            continue
        kw = m.group(1)
        body = m.group("body").strip()
        if kw.lower() == "and":
            kw_use = last_kw
        else:
            kw_use = kw
            last_kw = kw
        action, target, value = _semantic_from_gherkin_clause(kw_use, body)
        tq_kw = find_tap_qualifier_in_text(body) if action == "tap" else None
        if tq_kw:
            steps.append(
                _step(
                    action,
                    tq_kw.label if (target or "").strip() in {"", tq_kw.label} else target,
                    value,
                    idx,
                    stripped,
                    target_qualifier_phrase_raw=tq_kw.qualifier_phrase_raw,
                    target_container_hint=tq_kw.container_hint,
                    tap_qualifier_preposition=tq_kw.preposition,
                ),
            )
        else:
            steps.append(_step(action, target, value, idx, stripped))
        idx += 1

    return CanonicalScenario(steps=steps, title=title, warnings=warnings)


def _parse_prose_or_list(text: str, _profile: ScenarioInputProfile) -> CanonicalScenario:
    lines, w = _iter_body_lines(text)
    warnings = list(w)
    steps: list[CanonicalStep] = []
    for i, (_ln, body) in enumerate(lines):
        # Skip orphan Scenario: handled in gherkin only; here treat as plain line
        if _SCENARIO_TITLE.match(body):
            warnings.append("Scenario: line seen outside Gherkin parser path; parsed as text.")
        st = _parse_imperative_line(body)
        steps.append(
            CanonicalStep(
                action=st.action,
                target=st.target,
                value=st.value,
                index=i,
                source_text=st.source_text,
                target_qualifier_phrase_raw=st.target_qualifier_phrase_raw,
                target_container_hint=st.target_container_hint,
                tap_qualifier_preposition=st.tap_qualifier_preposition,
            ),
        )
    return CanonicalScenario(steps=steps, warnings=warnings)


def parse_scenario_text(
    text: str,
    profile: ScenarioInputProfile | None = None,
) -> CanonicalScenario:
    """
    Deterministic parse: always runs before any optional AI fallback.

    If ``profile`` is omitted, classifies internally (same as pipeline entry).
    """
    prof = profile or classify_scenario_text(text)
    if prof.structure == InputStructure.GHERKIN:
        return _parse_gherkin(text)
    return _parse_prose_or_list(text, prof)
