"""Heuristic input classification (structure + language hint)."""

from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel, Field

_LEADING_ENUM = re.compile(
    r"^\s*(?:" r"[*\-•]+\s*" r"|\d+[.)]\s*" r")\s*",
    flags=re.UNICODE,
)
_GHERKIN_START = re.compile(
    r"^\s*(Given|When|Then|And|But)\s+.+",
    re.IGNORECASE,
)
_SCENARIO_LINE = re.compile(r"^\s*Scenario:\s*.+", re.IGNORECASE)
_TURKISH_CHARS = frozenset("ğüşıöçĞÜŞİÖÇ")


class InputStructure(StrEnum):
    """Coarse structural bucket for routing the deterministic parser."""

    GHERKIN = "gherkin"
    STEP_LIST = "step_list"
    PROSE = "prose"


class LanguageHint(StrEnum):
    """Best-effort language / mix signal (orthogonal to structure)."""

    ENGLISH = "english"
    TURKISH = "turkish"
    MIXED_TR_EN = "mixed_tr_en"
    UNKNOWN = "unknown"


class ScenarioInputProfile(BaseModel):
    """Outcome of the input classifier (no parsing of individual steps yet)."""

    structure: InputStructure
    language_hint: LanguageHint
    notes: list[str] = Field(default_factory=list)


def _non_comment_lines(text: str) -> list[str]:
    return [
        raw.strip() for raw in text.splitlines() if raw.strip() and not raw.strip().startswith("#")
    ]


def _detect_language_hint(blob: str) -> LanguageHint:
    has_tr_char = any(c in _TURKISH_CHARS for c in blob)
    lower = blob.lower()
    tr_cues = (
        "'e git",
        "'a ekle",
        "cart'a",
        "ürünü",
        "login ol",
        " sepete",
        " doğrula",
        " görün",
        " giriş",
    )
    has_tr_cue = any(c in lower for c in tr_cues) or bool(
        re.search(r"\bara\b|\bsepet\b|\bürün", lower),
    )
    # Small English cue set (Gherkin + common NL).
    en_markers = (
        " the ",
        " user ",
        "given",
        "when",
        "then",
        " tap ",
        " search",
        " cart",
        "scenario:",
    )
    en_hits = sum(1 for m in en_markers if m in lower)
    if (has_tr_char or has_tr_cue) and en_hits >= 2:
        return LanguageHint.MIXED_TR_EN
    if has_tr_char or has_tr_cue:
        return LanguageHint.TURKISH
    if en_hits >= 1 or blob.isascii():
        return LanguageHint.ENGLISH
    return LanguageHint.UNKNOWN


def classify_scenario_text(text: str) -> ScenarioInputProfile:
    """
    Classify raw scenario text for parser routing.

    This is intentionally lightweight and extendable (regex + counts), not an LLM.
    """
    lines = _non_comment_lines(text)
    if not lines:
        return ScenarioInputProfile(
            structure=InputStructure.PROSE,
            language_hint=LanguageHint.UNKNOWN,
            notes=["No non-empty lines; treated as empty prose."],
        )

    blob = "\n".join(lines)
    lang = _detect_language_hint(blob)

    gherkin_lines = sum(1 for line in lines if _GHERKIN_START.match(line))
    has_scenario = any(_SCENARIO_LINE.match(line) for line in lines)
    if gherkin_lines >= 2 or (gherkin_lines >= 1 and has_scenario):
        return ScenarioInputProfile(
            structure=InputStructure.GHERKIN,
            language_hint=lang,
            notes=["Detected Gherkin-style keywords."],
        )

    marked = sum(1 for line in lines if _LEADING_ENUM.match(line))
    if len(lines) > 1 and marked >= max(1, len(lines) // 2):
        return ScenarioInputProfile(
            structure=InputStructure.STEP_LIST,
            language_hint=lang,
            notes=["Several lines look like a Markdown/plain list."],
        )

    return ScenarioInputProfile(
        structure=InputStructure.PROSE,
        language_hint=lang,
        notes=["Defaulted to prose / imperative lines."],
    )
