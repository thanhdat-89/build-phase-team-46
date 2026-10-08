"""Minimal statistics layer for the CVAT annotation dashboard demo.

All functions accept lists of ``ImageRecord`` and/or ``ObjectRecord``
instances and return plain dicts / lists-of-dicts that are easy to
convert into pandas DataFrames or feed directly into Streamlit widgets.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from core.schema import ImageRecord, ObjectRecord


# ---------------------------------------------------------------------------
# 1. Dataset summary
# ---------------------------------------------------------------------------

def dataset_summary(
    images: list[ImageRecord],
    objects: list[ObjectRecord],
) -> dict[str, int]:
    """Return high-level counts for the entire dataset.

    Returns a dict with keys:
    - ``total_images``
    - ``total_objects``
    - ``total_classes``
    - ``annotated_images``   (images with >= 1 object)
    - ``unannotated_images`` (images with 0 objects)
    """
    total_images = len(images)
    total_objects = len(objects)

    annotated_image_ids = {obj.image_id for obj in objects}
    annotated_images = len(annotated_image_ids)

    all_image_ids = {img.image_id for img in images}
    unannotated_images = len(all_image_ids - annotated_image_ids)

    total_classes = len({obj.class_name for obj in objects})

    return {
        "total_images": total_images,
        "total_objects": total_objects,
        "total_classes": total_classes,
        "annotated_images": annotated_images,
        "unannotated_images": unannotated_images,
    }


# ---------------------------------------------------------------------------
# 2. Class distribution
# ---------------------------------------------------------------------------

def class_distribution(
    objects: list[ObjectRecord],
) -> list[dict[str, Any]]:
    """Per-class breakdown of object count, image count, and percentage.

    Returns a list of dicts, each containing:
    - ``class_name``
    - ``object_count``  -- number of bounding boxes of this class
    - ``image_count``   -- number of unique images containing this class
    - ``percentage``    -- object_count / total_objects * 100 (0.0 when empty)
    """
    total_objects = len(objects)

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
            "percentage": (obj_count / total_objects * 100)
                          if total_objects > 0 else 0.0,
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
