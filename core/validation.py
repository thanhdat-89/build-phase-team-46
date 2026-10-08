"""Validation foundation layer for bounding boxes, metadata, and scene tags.

Sprint 1: Schema Hardening + Validation Foundation.
Enforces geometric constraints, 4-state metadata taxonomy, and scene_info conflict detection.
Never silently fixes or modifies input coordinates or metadata values.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from core.schema import ImageRecord, ObjectRecord



# ---------------------------------------------------------------------------
# Metadata Taxonomies
# ---------------------------------------------------------------------------

# Defined according to Docs/METRIC_CATALOG.md and scene_info_guide/Huong_dan_scene_info_CVAT.md
KNOWN_TIMEOFDAY: frozenset[str] = frozenset({"day", "night", "dawn_dusk"})
KNOWN_WEATHER: frozenset[str] = frozenset({"clear", "rain", "fog", "overcast"})
UNKNOWN_METADATA_VALUE: str = "unknown"



# ---------------------------------------------------------------------------
# Metadata States
# ---------------------------------------------------------------------------

class MetadataState(str, Enum):
    """The four mutually exclusive metadata states defined by project theory:

    * known: a valid and determined value in the defined taxonomy
    * unknown: explicitly marked as 'unknown'
    * missing: the field is absent, null, or empty
    * invalid: a value exists but is outside the defined schema/taxonomy
    """

    KNOWN = "known"
    UNKNOWN = "unknown"
    MISSING = "missing"
    INVALID = "invalid"



# ---------------------------------------------------------------------------
# Bounding Box Failure Reasons
# ---------------------------------------------------------------------------

class BBoxFailureReason(str, Enum):
    """Failure reason codes for bounding box geometric validation."""

    NON_FINITE_COORDINATES = "non_finite_coordinates"
    INVALID_IMAGE_DIMENSIONS = "invalid_image_dimensions"
    REVERSED_X = "reversed_x"
    REVERSED_Y = "reversed_y"
    ZERO_WIDTH = "zero_width"
    NEGATIVE_WIDTH = "negative_width"
    ZERO_HEIGHT = "zero_height"
    NEGATIVE_HEIGHT = "negative_height"
    OUT_OF_BOUNDS = "out_of_bounds"



# ---------------------------------------------------------------------------
# Validation Containers
# ---------------------------------------------------------------------------

@dataclass
class BBoxValidationResult:
    """Result of validating a bounding box's geometry.

    Attributes
    ----------
    valid : bool
        True if all geometric criteria pass.
    reasons : list[str]
        List of failure reasons explaining why the bbox is invalid.
    """

    valid: bool
    reasons: list[str] = field(default_factory=list)


@dataclass
class InvalidObjectRecord:
    """Container preserving an invalid bounding box and why it failed.

    Ensures invalid bounding boxes do not disappear from Data Quality reporting.
    """

    object: ObjectRecord
    reasons: list[str]


@dataclass
class MetadataValidationResult:
    """Result of classifying a metadata field into one of four states.

    Attributes
    ----------
    field_name : str
        Name of the metadata field (e.g. 'timeofday', 'weather').
    state : MetadataState
        One of KNOWN, UNKNOWN, MISSING, INVALID.
    value : str | None
        Normalized value (None if missing).
    original_value : str | None
        Raw original string preserved for Data Lead audit.
    """

    field_name: str
    state: MetadataState
    value: str | None
    original_value: str | None = None


@dataclass
class SceneTagValidationResult:
    """Result of inspecting scene_info tags for duplicates and conflicts.

    Attributes
    ----------
    has_conflict : bool
        True if multiple scene_info tags have differing values.
    is_duplicate : bool
        True if multiple identical scene_info tags were found (not a conflict).
    timeofday : str | None
        Resolved timeofday value if no conflict occurred, else None.
    weather : str | None
        Resolved weather value if no conflict occurred, else None.
    conflicting_fields : list[str]
        Fields that caused conflict (e.g. ['timeofday']).
    reasons : list[str]
        Detailed failure reasons.
    tags : list[dict[str, str | None]]
        All parsed scene tags preserved for review.
    """

    has_conflict: bool
    is_duplicate: bool = False
    timeofday: str | None = None
    weather: str | None = None
    conflicting_fields: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    tags: list[dict[str, str | None]] = field(default_factory=list)



# ---------------------------------------------------------------------------
# Bounding Box Validation Logic
# ---------------------------------------------------------------------------

def validate_bbox(
    bbox: ObjectRecord,
    image_width: int,
    image_height: int,
) -> BBoxValidationResult:
    """Validate bounding box geometry against image dimensions.

    A bounding box is valid only when:
    - coordinates are finite numbers
    - x_max > x_min
    - y_max > y_min
    - image width > 0
    - image height > 0
    - coordinates are within image boundaries:
      0 <= x_min < x_max <= image_width
      0 <= y_min < y_max <= image_height

    Does NOT silently swap, clamp, or modify coordinates.
    """
    return validate_bbox_coordinates(
        x_min=bbox.x_min,
        y_min=bbox.y_min,
        x_max=bbox.x_max,
        y_max=bbox.y_max,
        image_width=image_width,
        image_height=image_height,
    )


def validate_bbox_coordinates(
    x_min: float,
    y_min: float,
    x_max: float,
    y_max: float,
    image_width: int,
    image_height: int,
) -> BBoxValidationResult:
    """Validate raw bounding box coordinates against image dimensions."""
    reasons: list[str] = []

    # 1. Non-finite coordinates check (NaN, Inf)
    coords = (x_min, y_min, x_max, y_max)
    if not all(isinstance(c, (int, float)) and math.isfinite(c) for c in coords):
        reasons.append(BBoxFailureReason.NON_FINITE_COORDINATES.value)
        return BBoxValidationResult(valid=False, reasons=reasons)

    # 2. Image dimensions check
    if image_width <= 0 or image_height <= 0:
        reasons.append(BBoxFailureReason.INVALID_IMAGE_DIMENSIONS.value)

    # 3. Horizontal axis checks (x_min, x_max)
    if x_min > x_max:
        reasons.append(BBoxFailureReason.REVERSED_X.value)
        reasons.append(BBoxFailureReason.NEGATIVE_WIDTH.value)
    elif x_min == x_max:
        reasons.append(BBoxFailureReason.ZERO_WIDTH.value)

    # 4. Vertical axis checks (y_min, y_max)
    if y_min > y_max:
        reasons.append(BBoxFailureReason.REVERSED_Y.value)
        reasons.append(BBoxFailureReason.NEGATIVE_HEIGHT.value)
    elif y_min == y_max:
        reasons.append(BBoxFailureReason.ZERO_HEIGHT.value)

    # 5. Out-of-bounds coordinates check
    is_out_of_bounds = False
    if x_min < 0 or y_min < 0 or x_max < 0 or y_max < 0:
        is_out_of_bounds = True
    if image_width > 0 and (x_min > image_width or x_max > image_width):
        is_out_of_bounds = True
    if image_height > 0 and (y_min > image_height or y_max > image_height):
        is_out_of_bounds = True

    if is_out_of_bounds:
        reasons.append(BBoxFailureReason.OUT_OF_BOUNDS.value)

    return BBoxValidationResult(valid=len(reasons) == 0, reasons=reasons)



# ---------------------------------------------------------------------------
# Metadata Validation Logic
# ---------------------------------------------------------------------------

def validate_metadata_value(
    field_name: str,
    value: str | None,
    known_values: frozenset[str],
) -> MetadataValidationResult:
    """Classify a metadata field value into one of four states:
    known, unknown, missing, invalid.

    - known: value is non-empty and in known_values.
    - unknown: value is explicitly 'unknown'.
    - missing: value is None, empty string, or whitespace.
    - invalid: value is non-empty, not 'unknown', and not in known_values.
      Preserves the original value.
    """
    if value is None:
        return MetadataValidationResult(
            field_name=field_name,
            state=MetadataState.MISSING,
            value=None,
            original_value=None,
        )

    stripped = value.strip()
    if not stripped:
        return MetadataValidationResult(
            field_name=field_name,
            state=MetadataState.MISSING,
            value=None,
            original_value=value,
        )

    lowered = stripped.lower()
    if lowered == UNKNOWN_METADATA_VALUE:
        return MetadataValidationResult(
            field_name=field_name,
            state=MetadataState.UNKNOWN,
            value=UNKNOWN_METADATA_VALUE,
            original_value=value,
        )

    if lowered in known_values:
        return MetadataValidationResult(
            field_name=field_name,
            state=MetadataState.KNOWN,
            value=lowered,
            original_value=value,
        )

    return MetadataValidationResult(
        field_name=field_name,
        state=MetadataState.INVALID,
        value=value,
        original_value=value,
    )


def validate_timeofday(value: str | None) -> MetadataValidationResult:
    """Validate timeofday metadata against the project taxonomy."""
    return validate_metadata_value("timeofday", value, KNOWN_TIMEOFDAY)


def validate_weather(value: str | None) -> MetadataValidationResult:
    """Validate weather metadata against the project taxonomy."""
    return validate_metadata_value("weather", value, KNOWN_WEATHER)



# ---------------------------------------------------------------------------
# Scene Tag Conflict Detection Logic
# ---------------------------------------------------------------------------

def validate_scene_tags(
    scene_tags: list[dict[str, str | None]],
) -> SceneTagValidationResult:
    """Inspect all scene_info tags for an image and detect conflicts.

    Rules:
    - 0 tags: no conflict, values are None.
    - 1 tag: no conflict, values from the single tag.
    - Multiple tags:
      - If all tags have identical normalized values:
        no conflict, is_duplicate = True, values from the tags.
      - If values differ across tags:
        conflict detected! Do NOT silently choose first or last tag.
        Conflicting fields are set to None and flagged.
    """
    if not scene_tags:
        return SceneTagValidationResult(
            has_conflict=False,
            is_duplicate=False,
            timeofday=None,
            weather=None,
            tags=[],
        )

    if len(scene_tags) == 1:
        tag = scene_tags[0]
        return SceneTagValidationResult(
            has_conflict=False,
            is_duplicate=False,
            timeofday=tag.get("timeofday"),
            weather=tag.get("weather"),
            tags=scene_tags,
        )

    # Normalize values for comparison
    normalized_tags: list[tuple[str | None, str | None]] = []
    for tag in scene_tags:
        tod = tag.get("timeofday")
        tod_norm = tod.strip() if tod else None
        wth = tag.get("weather")
        wth_norm = wth.strip() if wth else None
        normalized_tags.append((tod_norm, wth_norm))

    distinct_pairs = set(normalized_tags)
    if len(distinct_pairs) == 1:
        # Multiple tags with completely identical values: not a conflict!
        first_tod, first_wth = normalized_tags[0]
        return SceneTagValidationResult(
            has_conflict=False,
            is_duplicate=True,
            timeofday=first_tod,
            weather=first_wth,
            tags=scene_tags,
        )

    # Conflict detected between tags
    distinct_tod = {p[0] for p in normalized_tags}
    distinct_wth = {p[1] for p in normalized_tags}

    conflicting_fields: list[str] = []
    reasons: list[str] = []

    tod_val: str | None = None
    if len(distinct_tod) > 1:
        conflicting_fields.append("timeofday")
        reasons.append("conflicting_timeofday_tags")
    else:
        tod_val = list(distinct_tod)[0]

    wth_val: str | None = None
    if len(distinct_wth) > 1:
        conflicting_fields.append("weather")
        reasons.append("conflicting_weather_tags")
    else:
        wth_val = list(distinct_wth)[0]

    return SceneTagValidationResult(
        has_conflict=True,
        is_duplicate=False,
        timeofday=tod_val if "timeofday" not in conflicting_fields else None,
        weather=wth_val if "weather" not in conflicting_fields else None,
        conflicting_fields=conflicting_fields,
        reasons=reasons,
        tags=scene_tags,
    )
