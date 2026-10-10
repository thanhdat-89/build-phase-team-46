"""Coverage configuration schema and validation for N2-05B.

Strictly follows:
- FEEDBACK/Recommended-solution_DAT/Coverage_Recommendation_Engine_Coding_Spec_N2-05B.md §3
- FEEDBACK/Recommended-solution_DAT/Co_so_ly_thuyet_Data_Quality_Coverage_N2-05B.md §6
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


ALLOWED_IMAGE_FILTERS: frozenset[str] = frozenset(
    {
        "contains_class",
        "timeofday",
        "weather",
        "area_ratio_min",
        "area_ratio_max",
        "occluded",
    }
)

ALLOWED_OBJECT_FILTERS: frozenset[str] = frozenset(
    {
        "class_name",
        "timeofday",
        "weather",
        "area_ratio_min",
        "area_ratio_max",
        "occluded",
    }
)

VALID_UNITS: frozenset[str] = frozenset({"image", "object"})


@dataclass
class MetadataPolicy:
    """Policy thresholds for missing and unknown metadata."""

    missing_warning_rate: float = 0.05
    unknown_warning_rate: float = 0.10


@dataclass
class SliceDefinition:
    """Definition of a single data slice."""

    id: str
    name: str
    unit: str  # 'image' or 'object'
    filters: dict[str, Any]
    target_count: int
    weight: float = 1.0
    min_independent_sources: int | None = None
    enabled: bool = True
    feasibility: str = "confirmed"  # 'confirmed', 'unverified', 'infeasible'
    target_reason: str = ""


@dataclass
class CoverageConfig:
    """Top-level configuration for coverage evaluation."""

    definition_version: str = "1.0"
    config_version: str = "1"
    metadata_policy: MetadataPolicy = field(default_factory=MetadataPolicy)
    slices: list[SliceDefinition] = field(default_factory=list)


@dataclass
class ConfigValidationResult:
    """Result of validating a coverage configuration."""

    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    config: CoverageConfig | None = None


def validate_coverage_config(
    raw_config: dict[str, Any] | CoverageConfig,
    known_classes: set[str] | list[str] | None = None,
) -> ConfigValidationResult:
    """Validate a coverage configuration strictly against specification requirements.

    Requirements:
    - Unique slice IDs.
    - Unit in {'image', 'object'}.
    - target_count is positive integer.
    - weight is finite positive float/int.
    - metadata_policy rates within [0, 1].
    - Filter keys belong strictly to allowlist (no eval, no unsupported filters).
    - Unknown classes generate configuration warnings if known_classes schema provided.
    """
    errors: list[str] = []
    warnings: list[str] = []

    if isinstance(raw_config, CoverageConfig):
        # Convert to dict for uniform structural validation
        raw_dict = {
            "definition_version": raw_config.definition_version,
            "config_version": raw_config.config_version,
            "metadata_policy": {
                "missing_warning_rate": raw_config.metadata_policy.missing_warning_rate,
                "unknown_warning_rate": raw_config.metadata_policy.unknown_warning_rate,
            },
            "slices": [
                {
                    "id": s.id,
                    "name": s.name,
                    "unit": s.unit,
                    "filters": s.filters,
                    "target_count": s.target_count,
                    "weight": s.weight,
                    "min_independent_sources": s.min_independent_sources,
                    "enabled": s.enabled,
                    "feasibility": s.feasibility,
                    "target_reason": s.target_reason,
                }
                for s in raw_config.slices
            ],
        }
    elif isinstance(raw_config, dict):
        raw_dict = raw_config
    else:
        return ConfigValidationResult(
            valid=False,
            errors=["Configuration must be a dictionary or CoverageConfig instance."],
        )

    # 1. Metadata policy
    policy_data = raw_dict.get("metadata_policy", {})
    if not isinstance(policy_data, dict):
        errors.append("metadata_policy must be a dictionary.")
        missing_rate = 0.05
        unknown_rate = 0.10
    else:
        missing_rate = policy_data.get("missing_warning_rate", 0.05)
        unknown_rate = policy_data.get("unknown_warning_rate", 0.10)

        for rate_name, rate_val in [
            ("missing_warning_rate", missing_rate),
            ("unknown_warning_rate", unknown_rate),
        ]:
            if isinstance(rate_val, bool) or not isinstance(rate_val, (int, float)):
                errors.append(f"metadata_policy.{rate_name} must be a numeric rate in [0, 1].")
            elif rate_val < 0.0 or rate_val > 1.0 or math.isnan(rate_val):
                errors.append(f"metadata_policy.{rate_name} must be within [0.0, 1.0].")

    metadata_policy = MetadataPolicy(
        missing_warning_rate=float(missing_rate) if isinstance(missing_rate, (int, float)) and not isinstance(missing_rate, bool) else 0.05,
        unknown_warning_rate=float(unknown_rate) if isinstance(unknown_rate, (int, float)) and not isinstance(unknown_rate, bool) else 0.10,
    )

    # 2. Slices list
    raw_slices = raw_dict.get("slices")
    if raw_slices is None:
        errors.append("Configuration missing 'slices' list.")
        return ConfigValidationResult(valid=False, errors=errors, warnings=warnings)
    if not isinstance(raw_slices, list):
        errors.append("'slices' must be a list.")
        return ConfigValidationResult(valid=False, errors=errors, warnings=warnings)

    seen_ids: set[str] = set()
    validated_slices: list[SliceDefinition] = []

    known_classes_set = set(known_classes) if known_classes is not None else None

    for idx, s in enumerate(raw_slices):
        if not isinstance(s, dict):
            errors.append(f"Slice at index {idx} must be a dictionary.")
            continue

        s_id = s.get("id")
        if not s_id or not isinstance(s_id, str):
            errors.append(f"Slice at index {idx} must have a non-empty string 'id'.")
            continue

        if s_id in seen_ids:
            errors.append(f"Duplicate slice id: '{s_id}'. Slice IDs must be unique.")
        seen_ids.add(s_id)

        # Unit validation
        s_unit = s.get("unit")
        if s_unit not in VALID_UNITS:
            errors.append(
                f"Slice '{s_id}': unit '{s_unit}' is invalid. Must be one of {sorted(VALID_UNITS)}."
            )

        # target_count validation
        t_count = s.get("target_count")
        if isinstance(t_count, bool) or not isinstance(t_count, int) or t_count <= 0:
            errors.append(
                f"Slice '{s_id}': target_count must be a positive integer, got {t_count}."
            )

        # weight validation
        s_weight = s.get("weight", 1.0)
        if (
            isinstance(s_weight, bool)
            or not isinstance(s_weight, (int, float))
            or math.isnan(s_weight)
            or math.isinf(s_weight)
            or s_weight <= 0
        ):
            errors.append(
                f"Slice '{s_id}': weight must be a finite positive number, got {s_weight}."
            )

        # min_independent_sources validation
        min_sources = s.get("min_independent_sources")
        if min_sources is not None:
            if isinstance(min_sources, bool) or not isinstance(min_sources, int) or min_sources <= 0:
                errors.append(
                    f"Slice '{s_id}': min_independent_sources must be a positive integer if specified."
                )

        # filters validation
        filters = s.get("filters")
        if not isinstance(filters, dict):
            errors.append(f"Slice '{s_id}': filters must be a dictionary.")
            filters = {}
        else:
            allowlist = ALLOWED_IMAGE_FILTERS if s_unit == "image" else ALLOWED_OBJECT_FILTERS
            for f_key, f_val in filters.items():
                if f_key not in allowlist:
                    errors.append(
                        f"Slice '{s_id}': unsupported filter '{f_key}' for unit '{s_unit}'. "
                        f"Allowed keys: {sorted(allowlist)}."
                    )
                else:
                    # Validate individual filter types and ranges
                    if f_key in ("area_ratio_min", "area_ratio_max"):
                        if isinstance(f_val, bool) or not isinstance(f_val, (int, float)) or math.isnan(f_val) or f_val < 0.0 or f_val > 1.0:
                            errors.append(
                                f"Slice '{s_id}': {f_key} must be a number in [0.0, 1.0]."
                            )
                    elif f_key == "occluded":
                        if not isinstance(f_val, bool):
                            errors.append(f"Slice '{s_id}': occluded must be a boolean.")
                    elif f_key in ("contains_class", "class_name", "timeofday", "weather"):
                        if not isinstance(f_val, str) or not f_val.strip():
                            errors.append(
                                f"Slice '{s_id}': {f_key} must be a non-empty string."
                            )

            # Check area ratio bounds consistency
            min_area = filters.get("area_ratio_min")
            max_area = filters.get("area_ratio_max")
            if (
                isinstance(min_area, (int, float))
                and isinstance(max_area, (int, float))
                and not isinstance(min_area, bool)
                and not isinstance(max_area, bool)
                and min_area > max_area
            ):
                errors.append(
                    f"Slice '{s_id}': area_ratio_min ({min_area}) cannot be greater than area_ratio_max ({max_area})."
                )

            # Check class against known schema if provided (Coding Spec §3 & Criterion 8)
            target_class = filters.get("contains_class") or filters.get("class_name")
            if (
                target_class
                and known_classes_set is not None
                and target_class not in known_classes_set
            ):
                warnings.append(
                    f"Slice '{s_id}': class '{target_class}' is not in known class schema {sorted(known_classes_set)}."
                )

        validated_slices.append(
            SliceDefinition(
                id=s_id,
                name=str(s.get("name", s_id)),
                unit=str(s_unit),
                filters=filters,
                target_count=int(t_count) if isinstance(t_count, int) and not isinstance(t_count, bool) and t_count > 0 else 1,
                weight=float(s_weight) if isinstance(s_weight, (int, float)) and not isinstance(s_weight, bool) and s_weight > 0 else 1.0,
                min_independent_sources=min_sources if isinstance(min_sources, int) and not isinstance(min_sources, bool) else None,
                enabled=bool(s.get("enabled", True)),
                feasibility=str(s.get("feasibility", "confirmed")),
                target_reason=str(s.get("target_reason", "")),
            )
        )

    if errors:
        return ConfigValidationResult(
            valid=False,
            errors=errors,
            warnings=warnings,
            config=None,
        )

    config_obj = CoverageConfig(
        definition_version=str(raw_dict.get("definition_version", "1.0")),
        config_version=str(raw_dict.get("config_version", "1")),
        metadata_policy=metadata_policy,
        slices=validated_slices,
    )

    return ConfigValidationResult(
        valid=True,
        errors=[],
        warnings=warnings,
        config=config_obj,
    )
