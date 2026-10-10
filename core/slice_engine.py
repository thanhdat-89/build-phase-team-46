"""Slice matching and evaluation engine for N2-05B.

Strictly follows:
- FEEDBACK/Recommended-solution_DAT/Coverage_Recommendation_Engine_Coding_Spec_N2-05B.md §4, §5, §11
- FEEDBACK/Recommended-solution_DAT/Co_so_ly_thuyet_Data_Quality_Coverage_N2-05B.md §6
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from core.coverage_config import CoverageConfig, SliceDefinition
from core.schema import ImageRecord, ObjectRecord
from core.statistics import resolve_obj_image_key
from core.validation import (
    MetadataState,
    validate_bbox,
    validate_scene_tags,
    validate_timeofday,
    validate_weather,
)


@dataclass
class SliceEvaluationResult:
    """Detailed evaluation result for a single slice."""

    slice_id: str
    slice_name: str
    unit: str  # 'image' or 'object'
    support: int  # Confirmed matching unique keys
    target_count: int
    weight: float
    gap: int
    attainment: float
    priority: float
    matched_keys: list[str] = field(default_factory=list)
    unresolved_count: int = 0
    unresolved_keys: list[str] = field(default_factory=list)
    source_support: int | None = None
    source_support_status: str = "not_available"  # 'available' or 'not_available'
    metadata_availability: dict[str, float] = field(default_factory=dict)
    excluded_invalid_geometry_count: int = 0
    status: str = "below_target"  # 'met', 'below_target', 'zero_support', 'unresolved'


def get_image_metadata_info(
    img: ImageRecord,
    field_name: str,
) -> tuple[MetadataState, str | None, bool]:
    """Retrieve metadata state, normalized value, and conflict status for an image field."""
    # Check scene tags conflict first
    is_conflict = False
    if getattr(img, "has_scene_conflict", False) and getattr(img, "scene_tags", None):
        tag_val = validate_scene_tags(img.scene_tags)
        if field_name in tag_val.conflicting_fields:
            is_conflict = True
            return MetadataState.INVALID, None, True

    raw_val = getattr(img, field_name, None)
    if field_name == "timeofday":
        val_res = validate_timeofday(raw_val)
    elif field_name == "weather":
        val_res = validate_weather(raw_val)
    else:
        # Fallback for generic metadata
        if raw_val is None or str(raw_val).strip() == "":
            return MetadataState.MISSING, None, False
        if str(raw_val).strip().lower() == "unknown":
            return MetadataState.UNKNOWN, "unknown", False
        return MetadataState.KNOWN, str(raw_val).strip(), False

    return val_res.state, val_res.value, is_conflict


def evaluate_slice(
    slice_def: SliceDefinition,
    images: list[ImageRecord],
    objects: list[ObjectRecord],
    sources: dict[str, str] | list[dict[str, Any]] | None = None,
) -> SliceEvaluationResult:
    """Evaluate a single slice definition against images and objects.

    Follows specification:
    - Image slice: AND image metadata conditions with object existence conditions.
      Count unique image_key.
      Enforces same-object co-occurrence for class and area_ratio conditions.
    - Object slice: AND class, geometry/size, and parent image metadata.
      Count unique object_key.
    - Geometry validity: invalid bboxes excluded from area_ratio filters.
    - Metadata uncertainty: missing/unknown/invalid/conflict metadata in fields
      required by the slice makes a candidate unresolved, not confirmed false.
    - Source support: counts unique source_id if available; returns None if not.
    """
    # Build fast lookups
    images_by_key: dict[str, ImageRecord] = {img.image_key: img for img in images}
    images_by_id: dict[str, list[ImageRecord]] = {}
    for img in images:
        images_by_id.setdefault(img.image_id, []).append(img)

    objects_by_img_key: dict[str, list[ObjectRecord]] = {}
    for obj in objects:
        parent_k = resolve_obj_image_key(obj, images_by_key, images_by_id)
        objects_by_img_key.setdefault(parent_k, []).append(obj)

    # Build sources lookup (image_key -> source_id)
    sources_by_img_key: dict[str, str] = {}
    has_any_source_data = False
    if sources is not None:
        if isinstance(sources, dict):
            for k, s_id in sources.items():
                if s_id is not None and str(s_id).strip():
                    sources_by_img_key[str(k)] = str(s_id).strip()
                    has_any_source_data = True
        elif isinstance(sources, list):
            for row in sources:
                if isinstance(row, dict):
                    k = row.get("image_key")
                    s_id = row.get("source_id")
                    if k is not None and s_id is not None and str(s_id).strip():
                        sources_by_img_key[str(k)] = str(s_id).strip()
                        has_any_source_data = True

    # Also inspect image records for source_id attribute if not yet found
    for img in images:
        s_id = getattr(img, "source_id", None)
        if s_id is not None and str(s_id).strip():
            sources_by_img_key[img.image_key] = str(s_id).strip()
            has_any_source_data = True

    filters = slice_def.filters
    unit = slice_def.unit

    matched_keys: list[str] = []
    unresolved_keys: list[str] = []
    excluded_geom_count = 0

    # Track metadata availability for fields required by this slice
    required_metadata_fields = [f for f in ("timeofday", "weather") if f in filters]
    field_known_counts: dict[str, int] = {f: 0 for f in required_metadata_fields}
    total_evaluated_units = 0

    if unit == "image":
        total_evaluated_units = len(images)
        # Compute metadata availability across images
        for f in required_metadata_fields:
            for img in images:
                state, _, is_conflict = get_image_metadata_info(img, f)
                if state == MetadataState.KNOWN and not is_conflict:
                    field_known_counts[f] += 1

        for img in images:
            img_k = img.image_key
            img_objs = objects_by_img_key.get(img_k, [])

            # 1. Image metadata checks
            metadata_failed = False
            metadata_unresolved = False

            for f in required_metadata_fields:
                state, val, is_conflict = get_image_metadata_info(img, f)
                req_val = str(filters[f]).strip().lower()
                if is_conflict or state in (
                    MetadataState.MISSING,
                    MetadataState.UNKNOWN,
                    MetadataState.INVALID,
                ):
                    metadata_unresolved = True
                else:
                    if val != req_val:
                        metadata_failed = True
                        break

            if metadata_failed:
                # Definitive failure from image metadata
                continue

            # 2. Object condition checks
            has_obj_filters = any(
                k in filters
                for k in (
                    "contains_class",
                    "area_ratio_min",
                    "area_ratio_max",
                    "occluded",
                )
            )

            if not has_obj_filters:
                # No object requirements; image-level decision
                if metadata_unresolved:
                    unresolved_keys.append(img_k)
                else:
                    matched_keys.append(img_k)
                continue

            # Co-occurrence constraint: does there exist AT LEAST ONE object
            # satisfying ALL object conditions simultaneously?
            req_cls = filters.get("contains_class")
            min_area = filters.get("area_ratio_min")
            max_area = filters.get("area_ratio_max")
            req_occ = filters.get("occluded")
            needs_area = min_area is not None or max_area is not None

            found_matching_obj = False
            for obj in img_objs:
                # Class filter
                if req_cls is not None and obj.class_name != req_cls:
                    continue

                # Occluded filter
                if req_occ is not None and obj.occluded != req_occ:
                    continue

                # Area ratio filter
                if needs_area:
                    geom_val = validate_bbox(obj, img.width, img.height)
                    if not geom_val.valid:
                        excluded_geom_count += 1
                        continue
                    if img.width <= 0 or img.height <= 0:
                        continue
                    area_ratio = (
                        (obj.x_max - obj.x_min)
                        * (obj.y_max - obj.y_min)
                        / (img.width * img.height)
                    )
                    if min_area is not None and area_ratio < min_area:
                        continue
                    if max_area is not None and area_ratio > max_area:
                        continue

                # If we get here, this single object satisfies all object conditions!
                found_matching_obj = True
                break

            if not found_matching_obj:
                # Definitive failure: no object in this image matches all object conditions
                continue

            # Object conditions are satisfied!
            if metadata_unresolved:
                unresolved_keys.append(img_k)
            else:
                matched_keys.append(img_k)

    elif unit == "object":
        total_evaluated_units = len(objects)
        # Compute metadata availability across objects (from parent images)
        for f in required_metadata_fields:
            for obj in objects:
                parent_k = resolve_obj_image_key(obj, images_by_key, images_by_id)
                parent_img = images_by_key.get(parent_k)
                if parent_img:
                    state, _, is_conflict = get_image_metadata_info(parent_img, f)
                    if state == MetadataState.KNOWN and not is_conflict:
                        field_known_counts[f] += 1

        for obj in objects:
            obj_k = obj.object_key
            parent_k = resolve_obj_image_key(obj, images_by_key, images_by_id)
            parent_img = images_by_key.get(parent_k)

            # Class check
            req_cls = filters.get("class_name")
            if req_cls is not None and obj.class_name != req_cls:
                continue

            # Occluded check
            req_occ = filters.get("occluded")
            if req_occ is not None and obj.occluded != req_occ:
                continue

            # Area ratio check
            min_area = filters.get("area_ratio_min")
            max_area = filters.get("area_ratio_max")
            if min_area is not None or max_area is not None:
                img_w = parent_img.width if parent_img else 0
                img_h = parent_img.height if parent_img else 0
                geom_val = validate_bbox(obj, img_w, img_h)
                if not geom_val.valid:
                    excluded_geom_count += 1
                    continue
                if img_w <= 0 or img_h <= 0:
                    continue
                area_ratio = (
                    (obj.x_max - obj.x_min)
                    * (obj.y_max - obj.y_min)
                    / (img_w * img_h)
                )
                if min_area is not None and area_ratio < min_area:
                    continue
                if max_area is not None and area_ratio > max_area:
                    continue

            # Parent metadata check
            if not required_metadata_fields:
                matched_keys.append(obj_k)
                continue

            if parent_img is None:
                unresolved_keys.append(obj_k)
                continue

            metadata_failed = False
            metadata_unresolved = False

            for f in required_metadata_fields:
                state, val, is_conflict = get_image_metadata_info(parent_img, f)
                req_val = str(filters[f]).strip().lower()
                if is_conflict or state in (
                    MetadataState.MISSING,
                    MetadataState.UNKNOWN,
                    MetadataState.INVALID,
                ):
                    metadata_unresolved = True
                else:
                    if val != req_val:
                        metadata_failed = True
                        break

            if metadata_failed:
                continue

            if metadata_unresolved:
                unresolved_keys.append(obj_k)
            else:
                matched_keys.append(obj_k)

    unique_matched = list(dict.fromkeys(matched_keys))
    unique_unresolved = list(dict.fromkeys(unresolved_keys))

    support = len(unique_matched)
    unresolved_count = len(unique_unresolved)
    t_count = slice_def.target_count
    weight = slice_def.weight

    # Formulas from Coding Spec §5 & Co so ly thuyet §6.2
    gap = max(0, t_count - support)
    attainment = min(support / t_count, 1.0) if t_count > 0 else 1.0
    priority = weight * (1.0 - attainment)

    # Independent source support (Coding Spec §5 line 109, Criterion 6)
    if has_any_source_data:
        # Collect source IDs of supporting units
        matched_source_ids: set[str] = set()
        for k in unique_matched:
            # For objects, resolve to image key
            if unit == "object":
                # Find matching object
                # Parent key is stored or mapped
                img_k = k.split(":")[0] + ":" + k.split(":")[1] if ":" in k else k
                # Lookup by image_key from images_by_key if possible
                # In ObjectRecord, obj.object_key is {dataset_id}:{object_id}
                # Parent image_key is resolved from obj
                for obj in objects:
                    if obj.object_key == k:
                        parent_img_k = resolve_obj_image_key(obj, images_by_key, images_by_id)
                        s_id = sources_by_img_key.get(parent_img_k)
                        if s_id:
                            matched_source_ids.add(s_id)
                        break
            else:
                s_id = sources_by_img_key.get(k)
                if s_id:
                    matched_source_ids.add(s_id)

        source_support = len(matched_source_ids)
        source_support_status = "available"
    else:
        source_support = None
        source_support_status = "not_available"

    # Metadata availability
    avail_dict: dict[str, float] = {}
    for f in required_metadata_fields:
        avail_dict[f] = (
            field_known_counts[f] / total_evaluated_units
            if total_evaluated_units > 0
            else 0.0
        )

    # Determine status
    if support >= t_count:
        status_str = "met"
    elif support == 0 and unresolved_count > 0:
        status_str = "unresolved"
    elif support == 0:
        status_str = "zero_support"
    else:
        status_str = "below_target"

    return SliceEvaluationResult(
        slice_id=slice_def.id,
        slice_name=slice_def.name,
        unit=unit,
        support=support,
        target_count=t_count,
        weight=weight,
        gap=gap,
        attainment=attainment,
        priority=priority,
        matched_keys=unique_matched,
        unresolved_count=unresolved_count,
        unresolved_keys=unique_unresolved,
        source_support=source_support,
        source_support_status=source_support_status,
        metadata_availability=avail_dict,
        excluded_invalid_geometry_count=excluded_geom_count,
        status=status_str,
    )


def measure_slices(
    images: list[ImageRecord],
    objects: list[ObjectRecord],
    config: CoverageConfig,
    sources: dict[str, str] | list[dict[str, Any]] | None = None,
) -> dict[str, SliceEvaluationResult]:
    """Measure all enabled slices in a configuration."""
    results: dict[str, SliceEvaluationResult] = {}
    for s_def in config.slices:
        if s_def.enabled:
            results[s_def.id] = evaluate_slice(s_def, images, objects, sources=sources)
    return results
