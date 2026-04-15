"""Enumerations shared across domain models."""

from __future__ import annotations

from enum import StrEnum


class Platform(StrEnum):
    """Mobile platform target for a run."""

    ANDROID = "android"
    IOS = "ios"


class ActionType(StrEnum):
    """High-level Maestro-aligned action kinds the planner may emit."""

    LAUNCH_APP = "launch_app"
    TAP = "tap"
    INPUT_TEXT = "input_text"
    PRESS_KEY = "press_key"
    ASSERT_VISIBLE = "assert_visible"
    ASSERT_NOT_VISIBLE = "assert_not_visible"
    SCROLL = "scroll"
    SCROLL_UNTIL_VISIBLE = "scroll_until_visible"
    DISMISS_BLOCKER = "dismiss_blocker"
    BACK = "back"
    SWIPE = "swipe"
    UNKNOWN = "unknown"


class SelectorType(StrEnum):
    """Selector strategy category (ordering policy lives in docs, not in this enum)."""

    ID = "id"
    TEXT = "text"
    TEXT_WITH_STATE = "text_with_state"
    RELATIONAL = "relational"
    POINT = "point"


class StepStatus(StrEnum):
    """Lifecycle of a parsed/planned/executed step."""

    PENDING = "pending"
    PLANNED = "planned"
    EXECUTING = "executing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class ConfidenceLevel(StrEnum):
    """Discrete confidence band (can be derived from numeric score)."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ValidationSignalType(StrEnum):
    """What kind of signal should be checked after an action (MVP-friendly coarse types)."""

    TEXT_VISIBLE = "text_visible"
    TEXT_CONTAINS = "text_contains"
    ELEMENT_VISIBLE = "element_visible"
    ELEMENT_ABSENT = "element_absent"
    HIERARCHY_CHANGED = "hierarchy_changed"
    CUSTOM = "custom"
