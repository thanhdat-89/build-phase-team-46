"""Statistics and metric calculation layer for N2-05B CVAT Dashboard.

Implements Data Profiling (DP01-DP04) and Data Quality (DQ02-DQ06, DQ09) metrics
strictly adhering to Co_so_ly_thuyet_Data_Quality_Coverage_N2-05B.md and
Coverage_Recommendation_Engine_Coding_Spec_N2-05B.md.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any


from core.schema import ImageRecord, ObjectRecord
from core.validation import (
    KNOWN_TIMEOFDAY,
    KNOWN_WEATHER,
    InvalidObjectRecord,
    MetadataState,
    MetadataValidationResult,
    validate_bbox,
    validate_metadata_value,
    validate_timeofday,
    validate_weather,
)


# ---------------------------------------------------------------------------
# Metadata classification and ID resolution helpers
# ---------------------------------------------------------------------------

def classify_field(
    img: ImageRecord,
    field_name: str,
) -> MetadataValidationResult:
    """Classify a metadata field into known, unknown, missing, or invalid."""
    if field_name == "timeofday":
        return validate_timeofday(img.timeofday)
    if field_name == "weather":
        return validate_weather(img.weather)

    value = getattr(img, field_name, None)
    return validate_metadata_value(field_name, value, frozenset())


def resolve_obj_image_key(
    obj: ObjectRecord,
    images_by_key: dict[str, ImageRecord],
    images_by_id: dict[str, list[ImageRecord]],
) -> str:
    """Resolve an ObjectRecord's parent image key across datasets."""
    key = obj.image_key
    if key in images_by_key:
        return key

    matching_images = images_by_id.get(obj.image_id, [])
    if len(matching_images) == 1:
        return matching_images[0].image_key

    return key


# ---------------------------------------------------------------------------
# 1. DP01 — Inventory
# ---------------------------------------------------------------------------

def dp01_inventory(
    images: list[ImageRecord],
    valid_objects: list[ObjectRecord],
    all_objects: list[ObjectRecord] | None = None,
) -> dict[str, int]:
    """Return inventory counts, separating all boxes from valid boxes.

    ``total_objects`` counts all parsed objects when ``all_objects`` is supplied;
    otherwise it falls back to the valid-object count for backward compatibility.
    Image coverage is computed using dataset-aware image keys.
    """
    total_images = len(images)
    m_valid = len(valid_objects)
    m_total = len(all_objects) if all_objects is not None else m_valid

    images_by_key = {img.image_key: img for img in images}
    images_by_id: dict[str, list[ImageRecord]] = {}
    for img in images:
        images_by_id.setdefault(img.image_id, []).append(img)

    annotated_image_keys = {
        resolve_obj_image_key(obj, images_by_key, images_by_id)
        for obj in valid_objects
    }
    valid_annotated_keys = annotated_image_keys.intersection(images_by_key)
    annotated_images = len(valid_annotated_keys)
    unannotated_images = len(set(images_by_key) - valid_annotated_keys)
    total_classes = len({obj.class_name for obj in valid_objects})

    return {
        "total_images": total_images,
        "total_objects": m_total,
        "total_valid_objects": m_valid,
        "total_classes": total_classes,
        "annotated_image_count": annotated_images,
        "unannotated_image_count": unannotated_images,
        "annotated_images": annotated_images,
        "unannotated_images": unannotated_images,
    }


def dataset_summary(
    images: list[ImageRecord],
    objects: list[ObjectRecord],
) -> dict[str, int]:
    """Return legacy inventory counts with the keys expected by the UI/tests."""
    inv = dp01_inventory(images, objects, all_objects=objects)
    return {
        "total_images": inv["total_images"],
        "total_objects": inv["total_objects"],
        "total_classes": inv["total_classes"],
        "annotated_images": inv["annotated_images"],
        "unannotated_images": inv["unannotated_images"],
    }


# ---------------------------------------------------------------------------
# 2. DP02 — Class Instance Share
# ---------------------------------------------------------------------------

def dp02_class_instance_share(
    valid_objects: list[ObjectRecord],
    classes: list[str] | None = None,
) -> list[dict[str, Any]]:
    """DP02 — Class Instance Share.

    Calculates the proportion of valid bounding boxes belonging to each class.
    Formula: class_object_count / M_valid

    Parameters
    ----------
    valid_objects : list[ObjectRecord]
        Valid bounding boxes (M_valid). Invalid objects must be excluded.
    classes : list[str] | None
        Optional explicit list of classes. If None, unique classes are discovered
        from valid_objects.

    Returns
    -------
    list[dict[str, Any]]
        List of dicts for each class, sorted by count descending, then class_name.
        Each dict contains:
        - ``class_name``: str
        - ``class_object_count``: int
        - ``class_object_ratio``: float | None (None when M_valid == 0)
        - ``status``: str ("available" or "not_available")
        - ``percentage``: float | None (ratio * 100 or None)
    """
    m_valid = len(valid_objects)

    object_counts: Counter[str] = Counter()
    for obj in valid_objects:
        object_counts[obj.class_name] += 1

    if classes is not None:
        target_classes = list(classes)
    else:
        target_classes = sorted(
            object_counts.keys(), key=lambda c: (-object_counts[c], c)
        )

    result: list[dict[str, Any]] = []
    for class_name in target_classes:
        count = object_counts.get(class_name, 0)
        if m_valid == 0:
            ratio: float | None = None
            status = "not_available"
            percentage: float | None = None
        else:
            ratio = count / m_valid
            status = "available"
            percentage = ratio * 100.0

        result.append({
            "class_name": class_name,
            "class_object_count": count,
            "class_object_ratio": ratio,
            "status": status,
            "percentage": percentage,
        })

    return result


# ---------------------------------------------------------------------------
# 3. DP03 — Class Image Prevalence
# ---------------------------------------------------------------------------


def dp03_class_image_prevalence(
    images: list[ImageRecord],
    valid_objects: list[ObjectRecord],
    classes: list[str] | None = None,
) -> list[dict[str, Any]]:
    """DP03 — Class Image Prevalence.

    Calculates the proportion of images containing at least one valid object
    of each class. Multiple objects of the same class in one image count as 1.
    Formula: class_image_count / N

    Parameters
    ----------
    images : list[ImageRecord]
        All imported image records (N), including unannotated images.
    valid_objects : list[ObjectRecord]
        Valid bounding boxes. Invalid objects must be excluded.
    classes : list[str] | None
        Optional explicit list of classes.

    Returns
    -------
    list[dict[str, Any]]
        List of dicts for each class, sorted by image count descending, then class_name.
    """
    n = len(images)

    images_by_key = {img.image_key: img for img in images}
    images_by_id: dict[str, list[ImageRecord]] = {}
    for img in images:
        images_by_id.setdefault(img.image_id, []).append(img)

    image_sets: dict[str, set[str]] = {}
    for obj in valid_objects:
        key = resolve_obj_image_key(obj, images_by_key, images_by_id)
        image_sets.setdefault(obj.class_name, set()).add(key)

    if classes is not None:
        target_classes = list(classes)
    else:
        target_classes = sorted(
            image_sets.keys(), key=lambda c: (-len(image_sets[c]), c)
        )

    result: list[dict[str, Any]] = []
    for class_name in target_classes:
        img_count = len(image_sets.get(class_name, set()))
        if n == 0:
            ratio: float | None = None
            status = "not_available"
            percentage: float | None = None
        else:
            ratio = img_count / n
            status = "available"
            percentage = ratio * 100.0

        result.append({
            "class_name": class_name,
            "class_image_count": img_count,
            "class_image_ratio": ratio,
            "status": status,
            "percentage": percentage,
        })

    return result


# ---------------------------------------------------------------------------
# 4. Class distribution (Unified & backward-compatible)
# ---------------------------------------------------------------------------


def class_distribution(
    objects: list[ObjectRecord],
    images: list[ImageRecord] | None = None,
    valid_objects: list[ObjectRecord] | None = None,
) -> list[dict[str, Any]]:
    """Per-class breakdown of object count, image count, percentage, and ratios.

    Backward-compatible with existing callers.
    """
    total_objects = len(objects)
    n = len(images) if images is not None else None

    images_by_key = {img.image_key: img for img in images} if images is not None else {}
    images_by_id: dict[str, list[ImageRecord]] = {}
    if images is not None:
        for img in images:
            images_by_id.setdefault(img.image_id, []).append(img)

    # Resolve valid_objects for DP02/DP03 profiling metrics
    if valid_objects is not None:
        effective_valid = valid_objects
    elif images is not None:
        effective_valid = []
        for obj in objects:
            resolved_key = resolve_obj_image_key(obj, images_by_key, images_by_id)
            if resolved_key in images_by_key:
                parent_img = images_by_key[resolved_key]
                if validate_bbox(
                    obj,
                    image_width=parent_img.width,
                    image_height=parent_img.height,
                ).valid:
                    effective_valid.append(obj)
    else:
        effective_valid = [
            obj for obj in objects
            if math.isfinite(obj.x_min)
            and math.isfinite(obj.x_max)
            and math.isfinite(obj.y_min)
            and math.isfinite(obj.y_max)
            and obj.x_max > obj.x_min
            and obj.y_max > obj.y_min
            and obj.x_min >= 0.0
            and obj.y_min >= 0.0
        ]

    m_valid = len(effective_valid)

    # Legacy counts over all objects (M)
    legacy_counts: Counter[str] = Counter()
    legacy_image_sets: dict[str, set[str]] = {}
    for obj in objects:
        legacy_counts[obj.class_name] += 1
        key = resolve_obj_image_key(obj, images_by_key, images_by_id) if images else obj.image_id
        legacy_image_sets.setdefault(obj.class_name, set()).add(key)

    # Profiling counts over valid objects (M_valid)
    valid_counts: Counter[str] = Counter()
    valid_image_sets: dict[str, set[str]] = {}
    for obj in effective_valid:
        valid_counts[obj.class_name] += 1
        key = resolve_obj_image_key(obj, images_by_key, images_by_id) if images else obj.image_id
        valid_image_sets.setdefault(obj.class_name, set()).add(key)

    result: list[dict[str, Any]] = []
    for class_name, obj_count in legacy_counts.most_common():
        img_count = len(legacy_image_sets[class_name])
        valid_obj_count = valid_counts.get(class_name, 0)
        valid_img_count = len(valid_image_sets.get(class_name, set()))

        dp02_ratio = (valid_obj_count / m_valid) if m_valid > 0 else None
        dp03_ratio = (valid_img_count / n) if (n is not None and n > 0) else None

        result.append({
            "class_name": class_name,
            # Legacy fields over M (preserving backward compatibility)
            "object_count": obj_count,
            "image_count": img_count,
            "percentage": (obj_count / total_objects * 100.0) if total_objects > 0 else None,
            # DP02 fields over M_valid
            "class_object_count": valid_obj_count,
            "class_object_ratio": dp02_ratio,
            # DP03 fields over valid objects and N
            "class_image_count": valid_img_count,
            "class_image_ratio": dp03_ratio,
            "status": "available" if m_valid > 0 else "not_available",
        })

    return result


# ---------------------------------------------------------------------------
# 5. DP04 — Attribute Distribution
# ---------------------------------------------------------------------------


def dp04_attribute_distribution(
    images: list[ImageRecord],
    field_name: str,
) -> dict[str, Any]:
    """DP04 — Attribute Distribution(f, v).

    Calculates proportion of images having each value v over N,
    and proportion over known values.
    Also provides 4-state taxonomy breakdown (known, unknown, missing, invalid).

    If N == 0: returns not_available with reason.
    """
    n = len(images)
    if n == 0:
        return {
            "metric_id": "DP04",
            "field": field_name,
            "total_images": 0,
            "status": "not_available",
            "reason": "Empty dataset (N=0)",
            "state_counts": {
                "known": 0,
                "unknown": 0,
                "missing": 0,
                "invalid": 0,
            },
            "state_ratios": {
                "known": None,
                "unknown": None,
                "missing": None,
                "invalid": None,
            },
            "value_counts": {},
            "value_ratios_over_total": {},
            "value_ratios_over_known": {},
        }

    state_counts = {
        "known": 0,
        "unknown": 0,
        "missing": 0,
        "invalid": 0,
    }
    value_counts: dict[str, int] = {}
    known_value_counts: dict[str, int] = {}

    for img in images:
        res = classify_field(img, field_name)
        state_key = res.state.value
        state_counts[state_key] = state_counts.get(state_key, 0) + 1

        val_key = res.value if res.value is not None else "missing"
        value_counts[val_key] = value_counts.get(val_key, 0) + 1

        if res.state == MetadataState.KNOWN and res.value is not None:
            known_value_counts[res.value] = known_value_counts.get(res.value, 0) + 1

    known_total = state_counts["known"]

    return {
        "metric_id": "DP04",
        "field": field_name,
        "total_images": n,
        "status": "available",
        "reason": None,
        "state_counts": state_counts,
        "state_ratios": {k: v / n for k, v in state_counts.items()},
        "value_counts": value_counts,
        "value_ratios_over_total": {k: v / n for k, v in value_counts.items()},
        "value_ratios_over_known": {
            k: (v / known_total) if known_total > 0 else None
            for k, v in known_value_counts.items()
        },
    }


# ---------------------------------------------------------------------------
# 6. Time-of-day & Weather distributions (Legacy & Dashboard building blocks)
# ---------------------------------------------------------------------------

def timeofday_distribution(
    images: list[ImageRecord],
) -> dict[str, int]:
    """Image-level distribution of the ``timeofday`` metadata field.

    Returns counts for day, night, dawn_dusk, unknown, missing.
    """
    counts: dict[str, int] = {
        "day": 0,
        "night": 0,
        "dawn_dusk": 0,
        "unknown": 0,
        "missing": 0,
    }

    for img in images:
        res = classify_field(img, "timeofday")
        if res.state == MetadataState.MISSING:
            counts["missing"] += 1
        elif res.state == MetadataState.UNKNOWN:
            counts["unknown"] += 1
        elif res.state == MetadataState.KNOWN and res.value:
            counts[res.value] = counts.get(res.value, 0) + 1
        else:
            counts["invalid"] = counts.get("invalid", 0) + 1

    return counts


def weather_distribution(
    images: list[ImageRecord],
) -> dict[str, int]:
    """Image-level distribution of the ``weather`` metadata field.

    Returns counts for clear, rain, fog, overcast, unknown, missing.
    """
    counts: dict[str, int] = {
        "clear": 0,
        "rain": 0,
        "fog": 0,
        "overcast": 0,
        "unknown": 0,
        "missing": 0,
    }

    for img in images:
        res = classify_field(img, "weather")
        if res.state == MetadataState.MISSING:
            counts["missing"] += 1
        elif res.state == MetadataState.UNKNOWN:
            counts["unknown"] += 1
        elif res.state == MetadataState.KNOWN and res.value:
            counts[res.value] = counts.get(res.value, 0) + 1
        else:
            counts["invalid"] = counts.get("invalid", 0) + 1

    return counts


def class_image_distribution(
    objects: list[ObjectRecord],
) -> list[dict[str, Any]]:
    """Per-class object count and image count, for dashboard reuse."""
    object_counts: Counter[str] = Counter()
    image_sets: dict[str, set[str]] = {}

    for obj in objects:
        object_counts[obj.class_name] += 1
        img_identifier = getattr(obj, "image_key", obj.image_id)
        image_sets.setdefault(obj.class_name, set()).add(img_identifier)

    result: list[dict[str, Any]] = []
    for class_name, obj_count in object_counts.most_common():
        result.append({
            "class_name": class_name,
            "object_count": obj_count,
            "image_count": len(image_sets[class_name]),
        })

    return result


# ---------------------------------------------------------------------------
# 7. Data Quality Metrics: DQ02, DQ03, DQ04, DQ05
# ---------------------------------------------------------------------------

def dq02_metadata_missing_rate(
    images: list[ImageRecord],
    field_name: str,
) -> dict[str, Any]:
    """DQ02 — Metadata Missing Rate(f).

    Formula: count(image missing field f) / N.
    Denominator: N. If N == 0: value=None, status="not_available".
    """
    n = len(images)
    if n == 0:
        return {
            "metric_id": "DQ02",
            "scope": "dataset",
            "field": field_name,
            "unit": "image",
            "numerator": 0,
            "denominator": 0,
            "value": None,
            "status": "not_available",
            "reason": "Empty dataset (N=0)",
        }

    missing_count = sum(
        1 for img in images
        if classify_field(img, field_name).state == MetadataState.MISSING
    )
    return {
        "metric_id": "DQ02",
        "scope": "dataset",
        "field": field_name,
        "unit": "image",
        "numerator": missing_count,
        "denominator": n,
        "value": missing_count / n,
        "status": "available",
        "reason": None,
    }


def dq03_unknown_metadata_rate(
    images: list[ImageRecord],
    field_name: str,
) -> dict[str, Any]:
    """DQ03 — Unknown Metadata Rate(f).

    Formula: count(image with unknown at field f) / N.
    Denominator: N. If N == 0: value=None, status="not_available".
    """
    n = len(images)
    if n == 0:
        return {
            "metric_id": "DQ03",
            "scope": "dataset",
            "field": field_name,
            "unit": "image",
            "numerator": 0,
            "denominator": 0,
            "value": None,
            "status": "not_available",
            "reason": "Empty dataset (N=0)",
        }

    unknown_count = sum(
        1 for img in images
        if classify_field(img, field_name).state == MetadataState.UNKNOWN
    )
    return {
        "metric_id": "DQ03",
        "scope": "dataset",
        "field": field_name,
        "unit": "image",
        "numerator": unknown_count,
        "denominator": n,
        "value": unknown_count / n,
        "status": "available",
        "reason": None,
    }


def dq04_invalid_metadata_rate(
    images: list[ImageRecord],
    field_name: str,
) -> dict[str, Any]:
    """DQ04 — Invalid Metadata Rate(f).

    Formula: count(image with value outside schema at field f) / N.
    Denominator: N. If N == 0: value=None, status="not_available".
    """
    n = len(images)
    if n == 0:
        return {
            "metric_id": "DQ04",
            "scope": "dataset",
            "field": field_name,
            "unit": "image",
            "numerator": 0,
            "denominator": 0,
            "value": None,
            "status": "not_available",
            "reason": "Empty dataset (N=0)",
        }

    invalid_count = sum(
        1 for img in images
        if classify_field(img, field_name).state == MetadataState.INVALID
    )
    return {
        "metric_id": "DQ04",
        "scope": "dataset",
        "field": field_name,
        "unit": "image",
        "numerator": invalid_count,
        "denominator": n,
        "value": invalid_count / n,
        "status": "available",
        "reason": None,
    }


def dq05_known_metadata_rate(
    images: list[ImageRecord],
    field_name: str,
) -> dict[str, Any]:
    """DQ05 — Known Metadata Rate(f).

    Formula: count(image with valid and determined value at field f) / N.
    Denominator: N. If N == 0: value=None, status="not_available".

    Constraint: DQ02 + DQ03 + DQ04 + DQ05 = 100% when N > 0.
    """
    n = len(images)
    if n == 0:
        return {
            "metric_id": "DQ05",
            "scope": "dataset",
            "field": field_name,
            "unit": "image",
            "numerator": 0,
            "denominator": 0,
            "value": None,
            "status": "not_available",
            "reason": "Empty dataset (N=0)",
        }

    known_count = sum(
        1 for img in images
        if classify_field(img, field_name).state == MetadataState.KNOWN
    )
    return {
        "metric_id": "DQ05",
        "scope": "dataset",
        "field": field_name,
        "unit": "image",
        "numerator": known_count,
        "denominator": n,
        "value": known_count / n,
        "status": "available",
        "reason": None,
    }


# ---------------------------------------------------------------------------
# 8. Data Quality Metric: DQ06
# ---------------------------------------------------------------------------

def dq06_invalid_bbox_rate(
    total_objects: list[ObjectRecord] | int,
    invalid_objects: list[Any] | int,
) -> dict[str, Any]:
    """DQ06 — BBox Invalid Rate.

    Formula: count(bbox violating at least one geometric rule) / M.
    A bounding box violating multiple rules counts only ONCE in the numerator.
    Denominator: M. If M == 0: value=None, status="not_available", reason="No bounding boxes (M=0)".
    Never report 0% as if the metric were measured when M=0.
    """
    m = len(total_objects) if isinstance(total_objects, list) else total_objects
    inv_count = len(invalid_objects) if isinstance(invalid_objects, list) else invalid_objects

    if m <= 0:
        return {
            "metric_id": "DQ06",
            "scope": "dataset",
            "unit": "object",
            "numerator": inv_count,
            "denominator": 0,
            "value": None,
            "status": "not_available",
            "reason": "No bounding boxes (M=0)",
        }

    return {
        "metric_id": "DQ06",
        "scope": "dataset",
        "unit": "object",
        "numerator": inv_count,
        "denominator": m,
        "value": inv_count / m,
        "status": "available",
        "reason": None,
    }


# ---------------------------------------------------------------------------
# 9. Data Quality Metric: DQ09
# ---------------------------------------------------------------------------

def dq09_scene_tag_conflict_rate(
    images: list[ImageRecord],
) -> dict[str, Any]:
    """DQ09 — Scene Tag Conflict Rate.

    Formula: count(images with conflicting scene_info tags) / N.
    Denominator: N. If N == 0: value=None, status="not_available", reason="Empty dataset (N=0)".
    """
    n = len(images)
    if n == 0:
        return {
            "metric_id": "DQ09",
            "scope": "dataset",
            "unit": "image",
            "numerator": 0,
            "denominator": 0,
            "value": None,
            "status": "not_available",
            "reason": "Empty dataset (N=0)",
        }

    conflict_count = sum(1 for img in images if img.has_scene_conflict)
    return {
        "metric_id": "DQ09",
        "scope": "dataset",
        "unit": "image",
        "numerator": conflict_count,
        "denominator": n,
        "value": conflict_count / n,
        "status": "available",
        "reason": None,
    }


# ---------------------------------------------------------------------------
# Helper: Descriptive Statistics (Core tier)
# ---------------------------------------------------------------------------

def _percentile(sorted_data: list[float], p: float) -> float:
    """Calculate the p-th percentile (0.0 <= p <= 1.0) of sorted data."""
    if not sorted_data:
        return 0.0
    k = (len(sorted_data) - 1) * p
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_data[int(k)]
    d0 = sorted_data[int(f)] * (c - k)
    d1 = sorted_data[int(c)] * (k - f)
    return d0 + d1


def calculate_bbox_area_ratio(
    obj: ObjectRecord,
    image_width: int,
    image_height: int,
) -> float | None:
    """Calculate relative bounding box area ratio for a single object.

    Formula: (x_max - x_min) * (y_max - y_min) / (image_width * image_height).
    Only valid for bounding boxes with valid geometry and positive image dimensions.

    CRITICAL SEMANTICS:
    A small bbox area_ratio reflects 2D projected size on the image,
    NOT proof of physical distance in 3D world space.
    """
    if image_width <= 0 or image_height <= 0:
        return None
    val_res = validate_bbox(obj, image_width=image_width, image_height=image_height)
    if not val_res.valid:
        return None
    return ((obj.x_max - obj.x_min) * (obj.y_max - obj.y_min)) / (image_width * image_height)


# ---------------------------------------------------------------------------
# 10. DP05 — Relative BBox Area
# ---------------------------------------------------------------------------

def dp05_relative_bbox_area(
    images: list[ImageRecord],
    objects: list[ObjectRecord],
    valid_objects: list[ObjectRecord] | None = None,
    class_name: str | None = None,
) -> dict[str, Any]:
    """DP05 — Relative BBox Area.

    Formula: area_ratio = (x_max - x_min) * (y_max - y_min) / (width * height).
    Only valid bounding boxes with positive image dimensions are included.
    Invalid geometry is excluded from area statistics and reported in ``excluded_count``.

    CRITICAL SEMANTICS:
    A small bounding box area (small area_ratio) is strictly a 2D image-space
    geometric measurement and MUST NOT be interpreted as proof that an object
    is far away in 3D physical space.

    Denominator: M_valid (count of valid bounding boxes with valid image dimensions).
    If denominator == 0: value=None, status="not_available". Never invent 0%.
    """
    images_by_key = {img.image_key: img for img in images}
    images_by_id: dict[str, list[ImageRecord]] = {}
    for img in images:
        images_by_id.setdefault(img.image_id, []).append(img)

    valid_obj_set = set(id(o) for o in valid_objects) if valid_objects is not None else None

    target_objects = [o for o in objects if o.class_name == class_name] if class_name is not None else objects

    ratios: list[float] = []
    excluded_count = 0

    for obj in target_objects:
        if valid_obj_set is not None and id(obj) not in valid_obj_set:
            excluded_count += 1
            continue

        resolved_key = resolve_obj_image_key(obj, images_by_key, images_by_id)
        parent_img = images_by_key.get(resolved_key)
        if parent_img is None or parent_img.width <= 0 or parent_img.height <= 0:
            excluded_count += 1
            continue

        ratio = calculate_bbox_area_ratio(obj, parent_img.width, parent_img.height)
        if ratio is None:
            excluded_count += 1
            continue

        ratios.append(ratio)

    m_valid = len(ratios)
    if m_valid == 0:
        return {
            "metric_id": "DP05",
            "scope": "class" if class_name else "dataset",
            "field": "area_ratio",
            "class_name": class_name,
            "unit": "object",
            "numerator": 0,
            "denominator": 0,
            "value": None,
            "status": "not_available",
            "reason": "No valid bounding boxes with positive image dimensions (M_valid=0)",
            "excluded_count": excluded_count,
            "summary": None,
            "area_ratios": [],
            "definition_version": "1.0",
            "config_version": "1",
        }

    sorted_ratios = sorted(ratios)
    mean_val = sum(sorted_ratios) / m_valid
    median_val = _percentile(sorted_ratios, 0.5)
    summary = {
        "count": m_valid,
        "min": sorted_ratios[0],
        "max": sorted_ratios[-1],
        "mean": mean_val,
        "median": median_val,
        "p25": _percentile(sorted_ratios, 0.25),
        "p75": _percentile(sorted_ratios, 0.75),
    }

    return {
        "metric_id": "DP05",
        "scope": "class" if class_name else "dataset",
        "field": "area_ratio",
        "class_name": class_name,
        "unit": "object",
        "numerator": sum(sorted_ratios),
        "denominator": m_valid,
        "value": mean_val,
        "status": "available",
        "reason": None,
        "excluded_count": excluded_count,
        "summary": summary,
        "area_ratios": sorted_ratios,
        "definition_version": "1.0",
        "config_version": "1",
    }


# ---------------------------------------------------------------------------
# 11. DP06 — Occlusion Rate
# ---------------------------------------------------------------------------

def dp06_occlusion_rate(
    objects: list[ObjectRecord],
    class_name: str | None = None,
) -> dict[str, Any]:
    """DP06 — Occlusion Rate.

    Formula: count(object class c with occluded=True) / count(object class c with valid occluded value).
    Valid occluded values: boolean (True/False) or integer (1/0).
    Non-boolean/None occluded values are excluded from the denominator.

    Denominator: count of objects with valid occluded values.
    If denominator == 0: value=None, status="not_available". Never invent 0%.
    """
    def _is_valid_occluded(val: Any) -> bool:
        return isinstance(val, (bool, int)) and val in (True, False, 1, 0)

    def _is_occluded_true(val: Any) -> bool:
        return val is True or val == 1

    target_objects = [o for o in objects if o.class_name == class_name] if class_name is not None else objects

    valid_occluded_count = sum(1 for o in target_objects if _is_valid_occluded(o.occluded))
    occluded_true_count = sum(1 for o in target_objects if _is_valid_occluded(o.occluded) and _is_occluded_true(o.occluded))
    excluded_count = len(target_objects) - valid_occluded_count

    # Breakdown by class
    classes = sorted({o.class_name for o in objects})
    by_class: list[dict[str, Any]] = []
    for c in classes:
        c_objs = [o for o in objects if o.class_name == c]
        c_valid = sum(1 for o in c_objs if _is_valid_occluded(o.occluded))
        c_occ = sum(1 for o in c_objs if _is_valid_occluded(o.occluded) and _is_occluded_true(o.occluded))
        c_ratio = (c_occ / c_valid) if c_valid > 0 else None
        by_class.append({
            "class_name": c,
            "numerator": c_occ,
            "denominator": c_valid,
            "value": c_ratio,
            "percentage": (c_ratio * 100.0) if c_ratio is not None else None,
            "status": "available" if c_valid > 0 else "not_available",
            "excluded_count": len(c_objs) - c_valid,
        })

    if valid_occluded_count == 0:
        return {
            "metric_id": "DP06",
            "scope": "class" if class_name else "dataset",
            "class_name": class_name,
            "unit": "object",
            "numerator": 0,
            "denominator": 0,
            "value": None,
            "percentage": None,
            "status": "not_available",
            "reason": "No objects with valid occlusion values (denominator=0)",
            "excluded_count": excluded_count,
            "by_class": by_class,
            "definition_version": "1.0",
            "config_version": "1",
        }

    rate = occluded_true_count / valid_occluded_count
    return {
        "metric_id": "DP06",
        "scope": "class" if class_name else "dataset",
        "class_name": class_name,
        "unit": "object",
        "numerator": occluded_true_count,
        "denominator": valid_occluded_count,
        "value": rate,
        "percentage": rate * 100.0,
        "status": "available",
        "reason": None,
        "excluded_count": excluded_count,
        "by_class": by_class,
        "definition_version": "1.0",
        "config_version": "1",
    }


# ---------------------------------------------------------------------------
# 12. DP07 — Attribute Availability
# ---------------------------------------------------------------------------

def dp07_attribute_availability(
    objects: list[ObjectRecord],
    attribute_name: str | None = None,
    class_name: str | None = None,
) -> dict[str, Any]:
    """DP07 — Attribute Availability.

    Formula: count(objects with attribute info) / count(objects in scope).
    Unit: "object".
    Denominator: count of objects in scope.
    If denominator == 0: value=None, status="not_available". Never invent 0%.
    """
    target_objects = [o for o in objects if o.class_name == class_name] if class_name is not None else objects
    total_in_scope = len(target_objects)

    if total_in_scope == 0:
        return {
            "metric_id": "DP07",
            "scope": "class" if class_name else "dataset",
            "class_name": class_name,
            "attribute_name": attribute_name,
            "unit": "object",
            "numerator": 0,
            "denominator": 0,
            "value": None,
            "percentage": None,
            "status": "not_available",
            "reason": "No objects in scope (denominator=0)",
            "excluded_count": 0,
            "definition_version": "1.0",
            "config_version": "1",
        }

    def _has_attr_info(obj: ObjectRecord) -> bool:
        if not getattr(obj, "attributes", None):
            return False
        if attribute_name is not None:
            val = obj.attributes.get(attribute_name)
            return val is not None and str(val).strip() != ""
        return any(v is not None and str(v).strip() != "" for v in obj.attributes.values())

    available_count = sum(1 for o in target_objects if _has_attr_info(o))
    avail_rate = available_count / total_in_scope

    # Discover attribute breakdown if attribute_name is None
    all_attr_names = sorted({k for o in target_objects for k in getattr(o, "attributes", {})})
    by_attribute: dict[str, dict[str, Any]] = {}
    for attr in all_attr_names:
        c_count = sum(1 for o in target_objects if o.attributes.get(attr) is not None and str(o.attributes.get(attr)).strip() != "")
        by_attribute[attr] = {
            "numerator": c_count,
            "denominator": total_in_scope,
            "value": c_count / total_in_scope,
        }

    return {
        "metric_id": "DP07",
        "scope": "class" if class_name else "dataset",
        "class_name": class_name,
        "attribute_name": attribute_name,
        "unit": "object",
        "numerator": available_count,
        "denominator": total_in_scope,
        "value": avail_rate,
        "percentage": avail_rate * 100.0,
        "status": "available",
        "reason": None,
        "excluded_count": 0,
        "by_attribute": by_attribute,
        "definition_version": "1.0",
        "config_version": "1",
    }


# ---------------------------------------------------------------------------
# 13. DQ01 — Schema Validity Rate (Images, Objects, Tags separately)
# ---------------------------------------------------------------------------

def dq01_schema_validity_images(
    images: list[ImageRecord],
) -> dict[str, Any]:
    """DQ01 — Schema Validity Rate for Images.

    Formula: count(images passing all applicable schema rules) / N.
    Unit: "image".
    Applicable rules:
    - Positive finite integer width and height
    - Non-empty image_id and image_path
    - No scene conflict (has_scene_conflict is False)
    - Metadata values are not invalid (timeofday, weather != INVALID)

    Denominator: N. If N == 0: value=None, status="not_available". Never invent 0%.
    """
    n = len(images)
    if n == 0:
        return {
            "metric_id": "DQ01",
            "scope": "dataset",
            "entity_type": "images",
            "unit": "image",
            "numerator": 0,
            "denominator": 0,
            "value": None,
            "status": "not_available",
            "reason": "Empty dataset (N=0)",
            "excluded_count": 0,
            "definition_version": "1.0",
            "config_version": "1",
        }

    def _is_image_valid(img: ImageRecord) -> bool:
        if not (isinstance(img.width, int) and isinstance(img.height, int) and img.width > 0 and img.height > 0):
            return False
        if not (img.image_id and str(img.image_id).strip() and img.image_path and str(img.image_path).strip()):
            return False
        if img.has_scene_conflict:
            return False
        if classify_field(img, "timeofday").state == MetadataState.INVALID:
            return False
        if classify_field(img, "weather").state == MetadataState.INVALID:
            return False
        return True

    valid_count = sum(1 for img in images if _is_image_valid(img))
    rate = valid_count / n
    return {
        "metric_id": "DQ01",
        "scope": "dataset",
        "entity_type": "images",
        "unit": "image",
        "numerator": valid_count,
        "denominator": n,
        "value": rate,
        "percentage": rate * 100.0,
        "status": "available",
        "reason": None,
        "excluded_count": 0,
        "definition_version": "1.0",
        "config_version": "1",
    }


def dq01_schema_validity_objects(
    objects: list[ObjectRecord],
    images: list[ImageRecord] | None = None,
) -> dict[str, Any]:
    """DQ01 — Schema Validity Rate for Objects.

    Formula: count(objects passing all geometric and schema rules) / M.
    Unit: "object".
    Applicable rules:
    - Non-empty object_id and class_name
    - Finite coordinates
    - x_max > x_min, y_max > y_min, x_min >= 0, y_min >= 0
    - If parent image is known: x_max <= image.width, y_max <= image.height

    Denominator: M. If M == 0: value=None, status="not_available". Never invent 0%.
    """
    m = len(objects)
    if m == 0:
        return {
            "metric_id": "DQ01",
            "scope": "dataset",
            "entity_type": "objects",
            "unit": "object",
            "numerator": 0,
            "denominator": 0,
            "value": None,
            "status": "not_available",
            "reason": "No objects (M=0)",
            "excluded_count": 0,
            "definition_version": "1.0",
            "config_version": "1",
        }

    images_by_key = {img.image_key: img for img in images} if images is not None else {}
    images_by_id: dict[str, list[ImageRecord]] = {}
    if images is not None:
        for img in images:
            images_by_id.setdefault(img.image_id, []).append(img)

    def _is_object_valid(obj: ObjectRecord) -> bool:
        if not (obj.object_id and str(obj.object_id).strip() and obj.class_name and str(obj.class_name).strip()):
            return False
        if images is not None:
            resolved_key = resolve_obj_image_key(obj, images_by_key, images_by_id)
            parent_img = images_by_key.get(resolved_key)
            if parent_img is not None:
                return validate_bbox(obj, parent_img.width, parent_img.height).valid
        coords = (obj.x_min, obj.y_min, obj.x_max, obj.y_max)
        if not all(isinstance(c, (int, float)) and math.isfinite(c) for c in coords):
            return False
        if obj.x_min < 0 or obj.y_min < 0 or obj.x_max <= obj.x_min or obj.y_max <= obj.y_min:
            return False
        return True

    valid_count = sum(1 for obj in objects if _is_object_valid(obj))
    rate = valid_count / m
    return {
        "metric_id": "DQ01",
        "scope": "dataset",
        "entity_type": "objects",
        "unit": "object",
        "numerator": valid_count,
        "denominator": m,
        "value": rate,
        "percentage": rate * 100.0,
        "status": "available",
        "reason": None,
        "excluded_count": 0,
        "definition_version": "1.0",
        "config_version": "1",
    }


def dq01_schema_validity_tags(
    tags: list[dict[str, Any]] | None = None,
    images: list[ImageRecord] | None = None,
) -> dict[str, Any]:
    """DQ01 — Schema Validity Rate for Tags.

    Formula: count(tags passing all applicable schema rules) / count(tags checked).
    Unit: "tag".
    Applicable rules:
    - timeofday attribute (if present) is not invalid in the metadata taxonomy
    - weather attribute (if present) is not invalid in the metadata taxonomy

    Denominator: count of tags. If count == 0: value=None, status="not_available".
    """
    effective_tags: list[dict[str, Any]] = []
    if tags is not None:
        effective_tags = list(tags)
    elif images is not None:
        for img in images:
            effective_tags.extend(img.scene_tags)

    total_tags = len(effective_tags)
    if total_tags == 0:
        return {
            "metric_id": "DQ01",
            "scope": "dataset",
            "entity_type": "tags",
            "unit": "tag",
            "numerator": 0,
            "denominator": 0,
            "value": None,
            "status": "not_available",
            "reason": "No tags to evaluate (denominator=0)",
            "excluded_count": 0,
            "definition_version": "1.0",
            "config_version": "1",
        }

    def _is_tag_valid(tag: dict[str, Any]) -> bool:
        tod = tag.get("timeofday")
        if tod is not None and str(tod).strip():
            if validate_timeofday(tod).state == MetadataState.INVALID:
                return False
        wth = tag.get("weather")
        if wth is not None and str(wth).strip():
            if validate_weather(wth).state == MetadataState.INVALID:
                return False
        return True

    valid_count = sum(1 for t in effective_tags if _is_tag_valid(t))
    rate = valid_count / total_tags
    return {
        "metric_id": "DQ01",
        "scope": "dataset",
        "entity_type": "tags",
        "unit": "tag",
        "numerator": valid_count,
        "denominator": total_tags,
        "value": rate,
        "percentage": rate * 100.0,
        "status": "available",
        "reason": None,
        "excluded_count": 0,
        "definition_version": "1.0",
        "config_version": "1",
    }


def dq01_schema_validity_rate(
    images: list[ImageRecord] | None = None,
    objects: list[ObjectRecord] | None = None,
    tags: list[dict[str, Any]] | None = None,
    entity_type: str | None = None,
) -> dict[str, Any]:
    """DQ01 — Schema Validity Rate dispatcher.

    Calculates separate schema validity rates for Images, Objects, and Tags.
    Does NOT combine different denominators into an aggregate rate.
    """
    if entity_type == "images":
        return dq01_schema_validity_images(images or [])
    if entity_type == "objects":
        return dq01_schema_validity_objects(objects or [], images)
    if entity_type == "tags":
        return dq01_schema_validity_tags(tags, images)

    return {
        "images": dq01_schema_validity_images(images or []),
        "objects": dq01_schema_validity_objects(objects or [], images),
        "tags": dq01_schema_validity_tags(tags, images),
    }


# ---------------------------------------------------------------------------
# 14. DQ07 — Duplicate Record Rate
# ---------------------------------------------------------------------------

def dq07_duplicate_record_rate(
    records: list[Any],
    key: str | callable = "image_key",
    unit: str = "record",
    duplicate_groups: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """DQ07 — Duplicate Record Rate.

    Formula: (total_records - unique_records_by_key) / total_records.
    Công bố khóa; tọa độ giống nhau chỉ là nghi trùng nếu chưa xác nhận.

    Denominator: count of records.
    If denominator == 0: value=None, status="not_available". Never invent 0%.
    """
    total_records = len(records)
    key_str = key if isinstance(key, str) else getattr(key, "__name__", "custom_key")

    if total_records == 0:
        return {
            "metric_id": "DQ07",
            "scope": "dataset",
            "key": key_str,
            "unit": unit,
            "numerator": 0,
            "denominator": 0,
            "value": None,
            "status": "not_available",
            "reason": "No records to evaluate (denominator=0)",
            "duplicate_count": 0,
            "unique_count": 0,
            "definition_version": "1.0",
            "config_version": "1",
        }

    if duplicate_groups is not None:
        # Group membership is evidence only for records in this measurement.
        # Repeated members of one group count once; overlapping distinct groups
        # are unresolved evidence, not an implicit transitive duplicate class.
        scoped_keys = set()
        for record in records:
            member = key(record) if callable(key) else (
                record.get(key) if isinstance(record, dict) else getattr(record, key, None)
            )
            if isinstance(member, str) and member.strip():
                scoped_keys.add(member)
        groups: dict[str, set[str]] = {}
        invalid_reason = None
        excluded_members = set()
        if len(scoped_keys) == 0:
            invalid_reason = "Measurement scope has no usable record keys."
        for index, row in enumerate(duplicate_groups):
            if not isinstance(row, dict):
                invalid_reason = "Malformed duplicate group record."
                break
            if row.get("confirmed") not in (True, 1):
                continue
            group_id = str(row.get("group_id", f"group-{index}"))
            members = row.get("image_keys") if "image_keys" in row else [row.get("image_key")]
            if not isinstance(members, list) or any(not isinstance(m, str) or not m.strip() for m in members):
                invalid_reason = "Confirmed duplicate group has invalid member keys."
                break
            excluded_members.update(set(members) - scoped_keys)
            groups.setdefault(group_id, set()).update(set(members) & scoped_keys)
        seen = set()
        for members in groups.values():
            if seen & members:
                invalid_reason = "Overlapping confirmed duplicate groups in measurement scope; resolve memberships before measuring."
                break
            seen.update(members)
        redundant_count = sum(max(0, len(members) - 1) for members in groups.values())
        available = invalid_reason is None
        return {
            "metric_id": "DQ07",
            "scope": "dataset",
            "key": "confirmed_duplicate_group",
            "unit": unit,
            "numerator": redundant_count if available else None,
            "denominator": total_records,
            "value": redundant_count / total_records if available else None,
            "status": "available" if available else "not_available",
            "reason": invalid_reason or ("Group members outside measurement scope were excluded." if excluded_members else None),
            "duplicate_count": redundant_count if available else None,
            "unique_count": total_records - redundant_count if available else None,
            "definition_version": "1.0",
            "config_version": "1",
        }

    extracted_keys: list[Any] = []
    for r in records:
        if callable(key):
            extracted_keys.append(key(r))
        elif isinstance(r, dict):
            extracted_keys.append(r.get(key))
        else:
            extracted_keys.append(getattr(r, key, None))

    unique_count = len(set(extracted_keys))
    duplicate_count = total_records - unique_count
    rate = duplicate_count / total_records

    return {
        "metric_id": "DQ07",
        "scope": "dataset",
        "key": key_str,
        "unit": unit,
        "numerator": duplicate_count,
        "denominator": total_records,
        "value": rate,
        "status": "available",
        "reason": None,
        "duplicate_count": duplicate_count,
        "unique_count": unique_count,
        "definition_version": "1.0",
        "config_version": "1",
    }


# ---------------------------------------------------------------------------
# 15. DQ08 — Audited Error Rate
# ---------------------------------------------------------------------------

def dq08_audited_error_rate(
    review_log: list[dict[str, Any]] | None = None,
    unit: str = "image",
    reviewer: str | None = None,
    reference: str | None = None,
) -> dict[str, Any]:
    """DQ08 — Audited Error Rate.

    Formula: confirmed_error_units / reviewed_units.
    Tách ảnh và object; cần reviewer/reference.

    CRITICAL SEMANTICS:
    - NEVER fabricate review-log data. When review log is absent (None or empty),
      returns value=None, status="not_available" with explicit reason.
    - Only verified/approved and explicit error statuses count as valid reviews.
    - Count unique image/object units separately. Contradictory clean/error
      reviews leave the unit unresolved and excluded from the denominator.
    - Zero denominator must produce None / not_available, never 0%.
    """
    if review_log is None or len(review_log) == 0:
        return {
            "metric_id": "DQ08",
            "scope": "dataset",
            "unit": unit,
            "numerator": 0,
            "denominator": 0,
            "value": None,
            "status": "not_available",
            "reason": "No review log available (review data absent)",
            "reviewer": reviewer,
            "reference": reference,
            "reviewed_count": 0,
            "error_count": 0,
            "unresolved_count": 0,
            "definition_version": "1.0",
            "config_version": "1",
        }

    clean_statuses = {"verified", "approved"}
    error_statuses = {"error", "rejected", "label_error", "metadata_error"}
    outcomes: dict[str, set[bool]] = {}
    excluded_reviews = 0
    for entry in review_log:
        if not isinstance(entry, dict):
            excluded_reviews += 1
            continue
        # Object reviews may carry an image_key identifying their parent. They
        # are still object units and must not enter the image denominator.
        entry_unit = entry.get("unit")
        if entry_unit is None:
            entry_unit = "object" if "object_key" in entry else "image"
        if unit not in ("image", "object") or entry_unit != unit:
            continue
        if unit == "image" and "object_key" in entry:
            excluded_reviews += 1
            continue
        identity = entry.get(f"{unit}_key")
        status = entry.get("review_status")
        status = status.strip().lower() if isinstance(status, str) else None
        if (not isinstance(identity, str) or not identity.strip()
                or status not in clean_statuses | error_statuses):
            excluded_reviews += 1
            continue
        is_error = (status in error_statuses or entry.get("has_error") is True
                    or entry.get("confirmed_error") is True)
        outcomes.setdefault(identity, set()).add(is_error)

    unresolved_count = sum(len(values) > 1 for values in outcomes.values())
    eligible = [values for values in outcomes.values() if len(values) == 1]
    reviewed_count = len(eligible)
    error_count = sum(True in values for values in eligible)
    reasons = []
    if unresolved_count:
        reasons.append(
            f"Excluded {unresolved_count} unresolved audit unit(s) with contradictory "
            "valid clean/error reviews."
        )
    if excluded_reviews:
        reasons.append(
            f"Excluded {excluded_reviews} review record(s) with invalid status, "
            "missing identity, or inconsistent unit."
        )
    if reviewed_count == 0:
        reasons.insert(0, "No eligible consistently reviewed units (denominator=0).")
    if unit not in ("image", "object"):
        reasons.insert(0, "Unsupported audit unit; use image or object.")

    return {
        "metric_id": "DQ08",
        "scope": "dataset",
        "unit": unit,
        "numerator": error_count,
        "denominator": reviewed_count,
        "value": error_count / reviewed_count if reviewed_count else None,
        "status": "available" if reviewed_count else "not_available",
        "reason": " ".join(reasons) or None,
        "reviewer": reviewer,
        "reference": reference,
        "reviewed_count": reviewed_count,
        "error_count": error_count,
        "unresolved_count": unresolved_count,
        "definition_version": "1.0",
        "config_version": "1",
    }
