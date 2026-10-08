"""Minimal statistics layer for the CVAT annotation dashboard demo.

All functions accept lists of ``ImageRecord`` and/or ``ObjectRecord``
instances and return plain dicts / lists-of-dicts that are easy to
convert into pandas DataFrames or feed directly into Streamlit widgets.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any

from core.schema import ImageRecord, ObjectRecord
from core.validation import validate_bbox


# ---------------------------------------------------------------------------
# 1. DP01 — Inventory / Dataset summary
# ---------------------------------------------------------------------------

def dp01_inventory(
    images: list[ImageRecord],
    valid_objects: list[ObjectRecord],
) -> dict[str, int]:
    """DP01 — Inventory.

    Parameters
    ----------
    images : list[ImageRecord]
        All imported image records (N), including unannotated images.
    valid_objects : list[ObjectRecord]
        Valid bounding boxes (M_valid). Invalid objects must be excluded.

    Returns
    -------
    dict[str, int]
        Dictionary with:
        - ``total_images`` (N)
        - ``total_objects`` (M_valid)
        - ``total_classes``
        - ``annotated_image_count``
        - ``unannotated_image_count``
        - ``annotated_images`` (alias for backward compatibility)
        - ``unannotated_images`` (alias for backward compatibility)
    """
    total_images = len(images)
    total_objects = len(valid_objects)

    annotated_image_ids = {obj.image_id for obj in valid_objects}
    annotated_images = len(annotated_image_ids)

    all_image_ids = {img.image_id for img in images}
    unannotated_images = len(all_image_ids - annotated_image_ids)

    total_classes = len({obj.class_name for obj in valid_objects})

    return {
        "total_images": total_images,
        "total_objects": total_objects,
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
        Optional explicit list of classes. If None, unique classes are discovered
        from valid_objects.

    Returns
    -------
    list[dict[str, Any]]
        List of dicts for each class, sorted by image count descending, then class_name.
        Each dict contains:
        - ``class_name``: str
        - ``class_image_count``: int
        - ``class_image_ratio``: float | None (None when N == 0)
        - ``status``: str ("available" or "not_available")
        - ``percentage``: float | None (ratio * 100 or None)
    """
    n = len(images)

    image_sets: dict[str, set[str]] = {}
    for obj in valid_objects:
        image_sets.setdefault(obj.class_name, set()).add(obj.image_id)

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

    Parameters
    ----------
    objects : list[ObjectRecord]
        All parsed bounding boxes (M), including potentially invalid ones.
    images : list[ImageRecord] | None
        All imported image records (N).
    valid_objects : list[ObjectRecord] | None
        Optional pre-filtered list of valid bounding boxes (M_valid).
        If None, valid objects are resolved so that DP02 and DP03 metrics
        never treat invalid bounding boxes as valid profiling objects.

    Returns
    -------
    list[dict[str, Any]]
        List of dicts containing:
        - ``class_name``
        - ``object_count``        -- legacy count of all parsed boxes (M)
        - ``image_count``         -- legacy count of images with any box (M)
        - ``percentage``          -- legacy object_count / M * 100
        - ``class_object_count``  -- DP02 valid instance count (M_valid)
        - ``class_object_ratio``  -- DP02 valid ratio: class_object_count / M_valid
        - ``class_image_count``   -- DP03 valid unique image count
        - ``class_image_ratio``   -- DP03 valid prevalence: class_image_count / N
        - ``status``              -- "available" or "not_available"
    """
    total_objects = len(objects)
    n = len(images) if images is not None else None

    # Resolve valid_objects for DP02/DP03 profiling metrics
    if valid_objects is not None:
        effective_valid = valid_objects
    elif images is not None:
        images_by_id = {img.image_id: img for img in images}
        effective_valid = [
            obj for obj in objects
            if obj.image_id in images_by_id and validate_bbox(
                obj,
                image_width=images_by_id[obj.image_id].width,
                image_height=images_by_id[obj.image_id].height,
            ).valid
        ]
    else:
        # Without images, filter objects that violate intrinsic geometry
        # (non-finite, reversed x/y, zero/negative dimensions, negative coords)
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
        legacy_image_sets.setdefault(obj.class_name, set()).add(obj.image_id)

    # Profiling counts over valid objects (M_valid)
    valid_counts: Counter[str] = Counter()
    valid_image_sets: dict[str, set[str]] = {}
    for obj in effective_valid:
        valid_counts[obj.class_name] += 1
        valid_image_sets.setdefault(obj.class_name, set()).add(obj.image_id)

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
            "percentage": (obj_count / total_objects * 100.0) if total_objects > 0 else 0.0,
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
# 3. Time-of-day distribution
# ---------------------------------------------------------------------------

def timeofday_distribution(
    images: list[ImageRecord],
) -> dict[str, int]:
    """Image-level distribution of the ``timeofday`` metadata field.

    Returns a dict with keys:
    - ``day``, ``night``, ``dawn_dusk``, ``unknown`` -- counts of images
      whose ``timeofday`` field equals that value.
    - ``missing`` -- count of images where ``timeofday is None``
      (metadata tag absent).

    ``unknown`` and ``missing`` are intentionally kept separate.
    """
    counts: dict[str, int] = {
        "day": 0,
        "night": 0,
        "dawn_dusk": 0,
        "unknown": 0,
        "missing": 0,
    }

    for img in images:
        if img.timeofday is None:
            counts["missing"] += 1
        else:
            counts[img.timeofday] = counts.get(img.timeofday, 0) + 1

    return counts


# ---------------------------------------------------------------------------
# 4. Weather distribution
# ---------------------------------------------------------------------------

def weather_distribution(
    images: list[ImageRecord],
) -> dict[str, int]:
    """Image-level distribution of the ``weather`` metadata field.

    Returns a dict with keys:
    - ``clear``, ``rain``, ``fog``, ``overcast``, ``unknown`` -- counts of
      images whose ``weather`` field equals that value.
    - ``missing`` -- count of images where ``weather is None``
      (metadata tag absent).

    ``unknown`` and ``missing`` are intentionally kept separate.
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
        if img.weather is None:
            counts["missing"] += 1
        else:
            counts[img.weather] = counts.get(img.weather, 0) + 1

    return counts


# ---------------------------------------------------------------------------
# 5. Class-image distribution
# ---------------------------------------------------------------------------

def class_image_distribution(
    objects: list[ObjectRecord],
) -> list[dict[str, Any]]:
    """Per-class object count and image count, for dashboard reuse.

    Returns a list of dicts, each containing:
    - ``class_name``
    - ``object_count``  -- total bounding boxes of this class
    - ``image_count``   -- unique images containing this class

    Similar to ``class_distribution`` but without the percentage field,
    providing a reusable building block for different dashboard views.
    """
    object_counts: Counter[str] = Counter()
    image_sets: dict[str, set[str]] = {}

    for obj in objects:
        object_counts[obj.class_name] += 1
        image_sets.setdefault(obj.class_name, set()).add(obj.image_id)

    result: list[dict[str, Any]] = []
    for class_name, obj_count in object_counts.most_common():
        result.append({
            "class_name": class_name,
            "object_count": obj_count,
            "image_count": len(image_sets[class_name]),
        })

    return result
