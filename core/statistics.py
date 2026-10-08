"""Statistics and metric calculation layer for N2-05B CVAT Dashboard.

Implements Data Profiling (DP01ΓÇôDP04) and Data Quality (DQ02ΓÇôDQ06, DQ09) metrics
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

def classify_field(img: ImageRecord, field_name: str) -> MetadataValidationResult:
    """Classify a metadata field of an image into one of 4 mutually exclusive states:
    known, unknown, missing, invalid.
    """
    if field_name == "timeofday":
        return validate_timeofday(img.timeofday)
    elif field_name == "weather":
        return validate_weather(img.weather)
    else:
        val = getattr(img, field_name, None)
        return validate_metadata_value(field_name, val, frozenset())


def resolve_obj_image_key(
    obj: ObjectRecord,
    images_by_key: dict[str, ImageRecord],
    images_by_id: dict[str, list[ImageRecord]],
) -> str:
    """Resolve an ObjectRecord's parent image key reliably across datasets."""
    key = obj.image_key
    if key in images_by_key:
        return key

    # If dataset_id was defaulted or unspecified, check if obj.image_id
    # unambiguously matches an image in images
    matching_imgs = images_by_id.get(obj.image_id, [])
    if len(matching_imgs) == 1:
        return matching_imgs[0].image_key

    return key


# ---------------------------------------------------------------------------
# 1. DP01 ΓÇö Inventory
# ---------------------------------------------------------------------------

def dp01_inventory(
    images: list[ImageRecord],
    valid_objects: list[ObjectRecord],
    all_objects: list[ObjectRecord] | None = None,
) -> dict[str, int]:
    """DP01 ΓÇö Inventory.

    Parameters
    ----------
    images : list[ImageRecord]
        All imported image records (N), including unannotated images.
    valid_objects : list[ObjectRecord]
        Valid bounding boxes (M_valid). Invalid objects must be excluded.
    all_objects : list[ObjectRecord] | None
        All parsed bounding boxes (M), including invalid objects.
        If None, defaults to len(valid_objects) for backward compatibility.

    Returns
    -------
    dict[str, int]
        Dictionary with:
        - ``total_images`` (N)
        - ``total_objects`` (M)
        - ``total_valid_objects`` (M_valid)
        - ``total_classes``
        - ``annotated_image_count``
        - ``unannotated_image_count``
        - ``annotated_images`` (alias for backward compatibility)
        - ``unannotated_images`` (alias for backward compatibility)
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
    valid_annotated_keys = annotated_image_keys & images_by_key.keys()
    annotated_images = len(valid_annotated_keys)

    all_image_keys = set(images_by_key.keys())
    unannotated_images = len(all_image_keys - valid_annotated_keys)

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
    """Return high-level inventory counts for the dataset.

    Backward-compatible alias for existing tests and UI expecting exact keys:
    total_images, total_objects, total_classes, annotated_images, unannotated_images.
    """
    inv = dp01_inventory(images, objects)
    return {
        "total_images": inv["total_images"],
        "total_objects": inv["total_objects"],
        "total_classes": inv["total_classes"],
        "annotated_images": inv["annotated_images"],
        "unannotated_images": inv["unannotated_images"],
    }


# ---------------------------------------------------------------------------
# 2. DP02 ΓÇö Class Instance Share
# ---------------------------------------------------------------------------

def dp02_class_instance_share(
    valid_objects: list[ObjectRecord],
    classes: list[str] | None = None,
) -> list[dict[str, Any]]:
    """DP02 ΓÇö Class Instance Share.

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
# 3. DP03 ΓÇö Class Image Prevalence
# ---------------------------------------------------------------------------

def dp03_class_image_prevalence(
    images: list[ImageRecord],
    valid_objects: list[ObjectRecord],
    classes: list[str] | None = None,
) -> list[dict[str, Any]]:
    """DP03 ΓÇö Class Image Prevalence.

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
# 5. DP04 ΓÇö Attribute Distribution
# ---------------------------------------------------------------------------

def dp04_attribute_distribution(
    images: list[ImageRecord],
    field_name: str,
) -> dict[str, Any]:
    """DP04 ΓÇö Attribute Distribution(f, v).

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
    """DQ02 ΓÇö Metadata Missing Rate(f).

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
    """DQ03 ΓÇö Unknown Metadata Rate(f).

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
    """DQ04 ΓÇö Invalid Metadata Rate(f).

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
    """DQ05 ΓÇö Known Metadata Rate(f).

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
    """DQ06 ΓÇö BBox Invalid Rate.

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
    """DQ09 ΓÇö Scene Tag Conflict Rate.

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
