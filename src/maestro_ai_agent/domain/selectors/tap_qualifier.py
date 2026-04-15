"""
Optional contextual qualifiers for tap steps (deterministic parse + synonym normalization).

Examples: ``Tap 'Shop' on the tab bar``, ``Tap 'Close' in the popup``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_TAP_QUAL = re.compile(
    r"""
    ^\s*
    (?:tap|press|click)\s+
    (?P<q>['"])(?P<label>[^'"]+)(?P=q)  # quoted label
    \s+
    (?P<prep>on|in|from)\s+
    (?P<rest>.+?)
    \s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Embedded tap+qualifier (e.g. Gherkin: user taps 'X' on the tab bar).
_EMBEDDED_TAP_QUAL = re.compile(
    r"(?:^|\s)(?:tap|press|click)(?:s)?\s+"
    r"(?P<q>['\"])(?P<label>[^'\"]+)(?P=q)\s+"
    r"(?P<prep>on|in|from)\s+"
    r"(?P<rest>[^\n]+)$",
    re.IGNORECASE,
)


def _norm_phrase(s: str) -> str:
    return " ".join(s.lower().split())


# phrase substring / token keys -> stable container hint slugs
_SYNONYM_TO_HINT: list[tuple[tuple[str, ...], str]] = [
    (("tab bar", "tabbar", "bottom nav", "bottom navigation", "tabs", "tab strip"), "tab_bar"),
    (("header", "top bar", "navigation bar", "nav bar", "toolbar", "app bar"), "header"),
    (("popup", "dialog", "modal", "alert"), "modal"),
    (("footer", "bottom area"), "footer"),
    (("drawer", "side menu", "navigation drawer"), "drawer"),
    (("card", "product card"), "card"),
    (("search field", "search box", "search bar"), "search_field"),
]


def normalize_qualifier_phrase(phrase: str) -> str | None:
    """
    Map a free-text qualifier (after on/in/from) to a stable slug, or None if unknown.
    """
    p = _norm_phrase(phrase)
    if not p:
        return None
    for keys, slug in _SYNONYM_TO_HINT:
        if any(k in p for k in keys):
            return slug
    return None


@dataclass(frozen=True)
class TapQualifierParse:
    """Result of parsing a tap line that may carry a contextual qualifier."""

    label: str
    """Visible text / tap target literal."""
    container_hint: str | None
    """Normalized slug (e.g. ``tab_bar``) when synonyms matched."""
    qualifier_phrase_raw: str
    """Trimmed text after on/in/from for logs and planner line reconstruction."""
    preposition: str
    """``on``, ``in``, or ``from`` as written (lowercased)."""


def parse_tap_with_qualifier(line: str) -> TapQualifierParse | None:
    """
    Return structured parse when the line matches ``Tap 'X' on|in|from <qualifier>``.

    Returns ``None`` when there is no contextual qualifier clause.
    """
    m = _TAP_QUAL.match(line.strip())
    if not m:
        return None
    label = (m.group("label") or "").strip()
    rest = (m.group("rest") or "").strip()
    prep = (m.group("prep") or "on").strip().lower()
    if not label or not rest:
        return None
    hint = normalize_qualifier_phrase(rest)
    return TapQualifierParse(
        label=label,
        container_hint=hint,
        qualifier_phrase_raw=rest,
        preposition=prep if prep in {"on", "in", "from"} else "on",
    )


def find_tap_qualifier_in_text(text: str) -> TapQualifierParse | None:
    """
    Detect a tap + quoted label + contextual qualifier anywhere in ``text``.

    Tries a strict line match first, then a trailing embedded clause match.
    """
    stripped = text.strip()
    direct = parse_tap_with_qualifier(stripped)
    if direct is not None:
        return direct
    m = _EMBEDDED_TAP_QUAL.search(stripped)
    if not m:
        return None
    label = (m.group("label") or "").strip()
    rest = (m.group("rest") or "").strip()
    prep = (m.group("prep") or "on").strip().lower()
    if not label or not rest:
        return None
    hint = normalize_qualifier_phrase(rest)
    return TapQualifierParse(
        label=label,
        container_hint=hint,
        qualifier_phrase_raw=rest,
        preposition=prep if prep in {"on", "in", "from"} else "on",
    )
