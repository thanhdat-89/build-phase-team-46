"""Coverage export layer for N2-05B Data Quality & Coverage.

Implements Phase 4.1: Pure-Python export layer generating four standardized artifacts:
- metrics.csv: Slice-level coverage metrics
- recommendations.csv: Actionable triage recommendations
- affected_images.csv: Concrete affected images with CVAT links or path fallback
- config.json: Active slice configuration snapshot

Strictly follows:
- FEEDBACK/Recommended-solution_DAT/Coverage_Recommendation_Engine_Coding_Spec_N2-05B.md §8, §9
- FEEDBACK/Recommended-solution_DAT/Co_so_ly_thuyet_Data_Quality_Coverage_N2-05B.md §6, §12
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from core.coverage_config import CoverageConfig, MetadataPolicy, SliceDefinition
from core.coverage_metrics import (
    DatasetCoverageResult,
    calculate_slice_metrics,
)
from core.recommendations import Recommendation, recommend
from core.schema import ImageRecord
from core.slice_engine import SliceEvaluationResult


# ---------------------------------------------------------------------------
# Canonical CSV Headers
# ---------------------------------------------------------------------------

METRICS_CSV_HEADERS: list[str] = [
    "slice_id",
    "slice_name",
    "unit",
    "support",
    "target_count",
    "weight",
    "gap",
    "attainment",
    "priority",
    "unresolved_count",
    "source_support",
    "source_support_status",
    "metadata_availability",
    "excluded_invalid_geometry_count",
    "status",
    "config_version",
    "dataset_version",
]

RECOMMENDATIONS_CSV_HEADERS: list[str] = [
    "recommendation_id",
    "slice_id",
    "rule_ids",
    "category",
    "severity",
    "evidence_status",
    "support",
    "target",
    "gap",
    "attainment",
    "priority",
    "unit",
    "title",
    "actions",
    "remeasure",
    "limitations",
    "affected_image_keys",
    "config_version",
    "dataset_version",
]

AFFECTED_IMAGES_CSV_HEADERS: list[str] = [
    "recommendation_id",
    "slice_id",
    "image_key",
    "image_path",
    "cvat_url",
    "unit",
    "config_version",
    "dataset_version",
]


# ---------------------------------------------------------------------------
# CVAT URL Resolution
# ---------------------------------------------------------------------------

def resolve_cvat_url(
    image_key: str,
    image_path: str = "",
    cvat_mapping: dict[str, Any] | Callable[..., str | None] | None = None,
    base_url: str = "",
) -> str:
    """Resolve a valid CVAT web link for an image using task/job/frame mappings.

    Never fabricates a CVAT link. If mappings are missing, invalid, or unconfirmed,
    returns an empty string "" so callers fall back to actual image_path or image_key.

    Supported mapping formats:
    - Direct URL string: "https://cvat.org/tasks/1/jobs/2?frame=3"
    - Dict with task/job/frame: {"task_id": 1, "job_id": 2, "frame": 3, "base_url": ...}
    - Dict with task/frame: {"task_id": 1, "frame": 3, "base_url": ...}
    - Callable: mapping_fn(image_key) -> str | None
    """
    if cvat_mapping is None:
        return ""

    entry: Any = None
    if callable(cvat_mapping):
        try:
            entry = cvat_mapping(image_key)
        except Exception:
            return ""
    elif isinstance(cvat_mapping, dict):
        if image_key in cvat_mapping:
            entry = cvat_mapping[image_key]
        elif image_path and image_path in cvat_mapping:
            entry = cvat_mapping[image_path]
        elif ":" in image_key:
            short_id = image_key.split(":", 1)[1]
            if short_id in cvat_mapping:
                entry = cvat_mapping[short_id]

    if entry is None:
        return ""

    if isinstance(entry, str):
        cleaned = entry.strip()
        if cleaned.startswith("http://") or cleaned.startswith("https://"):
            return cleaned
        return ""

    if isinstance(entry, dict):
        if "url" in entry and isinstance(entry["url"], str):
            cleaned = entry["url"].strip()
            if cleaned.startswith("http://") or cleaned.startswith("https://"):
                return cleaned
            return ""

        task_id = entry.get("task_id")
        job_id = entry.get("job_id")
        frame = entry.get("frame")
        raw_base_url = entry.get("base_url") or base_url

        # Require explicit base URL for on-premise/local deployment safety; never default to cloud
        if not raw_base_url or not isinstance(raw_base_url, str) or not raw_base_url.strip():
            return ""

        b_url = raw_base_url.strip().rstrip("/")
        if not (b_url.startswith("http://") or b_url.startswith("https://")):
            return ""

        if frame is None or task_id is None:
            return ""

        if job_id is not None:
            return f"{b_url}/tasks/{task_id}/jobs/{job_id}?frame={frame}"
        return f"{b_url}/tasks/{task_id}?frame={frame}"

    return ""


def _build_image_lookup(
    images: list[ImageRecord] | dict[str, ImageRecord] | None,
) -> dict[str, ImageRecord]:
    """Index ImageRecords by image_key, image_id, and image_path for resilient retrieval."""
    if not images:
        return {}
    if isinstance(images, dict):
        return images
    lookup: dict[str, ImageRecord] = {}
    for img in images:
        lookup[img.image_key] = img
        if img.image_id not in lookup:
            lookup[img.image_id] = img
        if img.image_path and img.image_path not in lookup:
            lookup[img.image_path] = img
    return lookup


# ---------------------------------------------------------------------------
# Individual Exporters
# ---------------------------------------------------------------------------

def export_config_json(
    config: CoverageConfig | dict[str, Any] | None,
    indent: int = 2,
) -> str:
    """Export slice configuration as a standardized JSON string."""
    if config is None:
        raw_dict = {
            "definition_version": "1.0",
            "config_version": "1",
            "metadata_policy": {
                "missing_warning_rate": 0.05,
                "unknown_warning_rate": 0.10,
            },
            "slices": [],
        }
    elif isinstance(config, CoverageConfig):
        raw_dict = {
            "definition_version": config.definition_version,
            "config_version": config.config_version,
            "metadata_policy": {
                "missing_warning_rate": config.metadata_policy.missing_warning_rate,
                "unknown_warning_rate": config.metadata_policy.unknown_warning_rate,
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
                for s in config.slices
            ],
        }
    elif isinstance(config, dict):
        raw_dict = config
    else:
        raise ValueError(f"Unsupported config type: {type(config)}")

    return json.dumps(raw_dict, indent=indent, ensure_ascii=False)


def export_metrics_csv(
    slice_results: dict[str, SliceEvaluationResult | dict[str, Any]]
    | list[SliceEvaluationResult | dict[str, Any]]
    | DatasetCoverageResult
    | None = None,
    config: CoverageConfig | None = None,
    dataset_version: str = "",
    config_version: str | None = None,
) -> str:
    """Export slice coverage metrics to CSV format.

    Guarantees:
    - Exact headers conforming to METRICS_CSV_HEADERS.
    - Deterministic ordering sorted by slice_id.
    - Never sums overlapping slice gaps.
    - Handles empty data and missing optional inputs safely.
    - Supports SliceEvaluationResult objects as well as preformatted metric dictionaries.
    """
    resolved_config_version = (
        config_version
        if config_version is not None
        else (config.config_version if config is not None else "1")
    )

    records: list[dict[str, Any]] = []

    if slice_results is not None:
        if isinstance(slice_results, DatasetCoverageResult):
            raw_metrics = list(slice_results.slice_metrics.values())
            for item in raw_metrics:
                records.append(dict(item))
        elif isinstance(slice_results, dict):
            for eval_res in slice_results.values():
                if isinstance(eval_res, dict):
                    records.append(dict(eval_res))
                elif isinstance(eval_res, SliceEvaluationResult):
                    records.append(calculate_slice_metrics(eval_res))
        elif isinstance(slice_results, list):
            for eval_res in slice_results:
                if isinstance(eval_res, dict):
                    records.append(dict(eval_res))
                elif isinstance(eval_res, SliceEvaluationResult):
                    records.append(calculate_slice_metrics(eval_res))

    # Sort deterministically by slice_id
    records.sort(key=lambda r: str(r.get("slice_id", "")))

    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(METRICS_CSV_HEADERS)

    for r in records:
        meta_avail = r.get("metadata_availability")
        if isinstance(meta_avail, dict) and meta_avail:
            meta_str = json.dumps(meta_avail, sort_keys=True)
        else:
            meta_str = ""

        src_support = r.get("source_support")
        src_support_str = "" if src_support is None else str(src_support)

        row = [
            str(r.get("slice_id", "")),
            str(r.get("slice_name", "")),
            str(r.get("unit", "")),
            r.get("support", 0),
            r.get("target_count", 0),
            r.get("weight", 1.0),
            r.get("gap", 0),
            round(float(r.get("attainment", 0.0)), 4),
            round(float(r.get("priority", 0.0)), 4),
            r.get("unresolved_count", 0),
            src_support_str,
            str(r.get("source_support_status", "not_available")),
            meta_str,
            r.get("excluded_invalid_geometry_count", 0),
            str(r.get("status", "")),
            resolved_config_version,
            dataset_version,
        ]
        writer.writerow(row)

    return output.getvalue()


def export_recommendations_csv(
    recommendations: list[Recommendation] | None = None,
    dataset_version: str = "",
    config_version: str | None = None,
) -> str:
    """Export actionable recommendations to CSV format.

    Guarantees:
    - Exact headers conforming to RECOMMENDATIONS_CSV_HEADERS.
    - Preserves deterministic triage priority order.
    - Handles empty data and missing optional inputs safely.
    """
    recs = recommendations or []

    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(RECOMMENDATIONS_CSV_HEADERS)

    for rec in recs:
        cfg_v = config_version if config_version is not None else rec.config_version
        ds_v = dataset_version if dataset_version else rec.dataset_version

        row = [
            rec.recommendation_id,
            rec.slice_id,
            ";".join(rec.rule_ids),
            rec.category,
            rec.severity,
            rec.evidence_status,
            rec.support,
            rec.target,
            rec.gap,
            round(float(rec.attainment), 4),
            round(float(rec.priority), 4),
            rec.unit,
            rec.title,
            "; ".join(rec.actions),
            "; ".join(rec.remeasure),
            "; ".join(rec.limitations),
            ";".join(rec.affected_image_keys),
            cfg_v,
            ds_v,
        ]
        writer.writerow(row)

    return output.getvalue()


def export_affected_images_csv(
    recommendations: list[Recommendation] | None = None,
    images: list[ImageRecord] | dict[str, ImageRecord] | None = None,
    cvat_mapping: dict[str, Any] | Callable[..., str | None] | None = None,
    dataset_version: str = "",
    config_version: str = "1",
    base_url: str = "",
) -> str:
    """Export affected images list to CSV format.

    Guarantees:
    - Never fabricates image records for recommendations with zero affected images.
    - Resolves valid CVAT links when confirmed task/job/frame mappings exist.
    - Falls back to actual image_path or image_key when CVAT link is unavailable.
    - Output is deterministic and sorted by recommendation_id, slice_id, image_key.
    """
    img_lookup = _build_image_lookup(images)
    recs = recommendations or []

    rows: list[list[Any]] = []

    for rec in recs:
        # Never fabricate image records if zero affected keys
        if not rec.affected_image_keys:
            continue

        cfg_v = rec.config_version or config_version
        ds_v = dataset_version or rec.dataset_version

        # Deduplicate keys while maintaining deterministic ordering
        unique_keys = sorted(set(rec.affected_image_keys))

        for key in unique_keys:
            img_rec = img_lookup.get(key)
            if img_rec is not None and img_rec.image_path:
                image_path = img_rec.image_path
            else:
                image_path = key

            cvat_url = resolve_cvat_url(
                image_key=key,
                image_path=image_path,
                cvat_mapping=cvat_mapping,
                base_url=base_url,
            )

            rows.append(
                [
                    rec.recommendation_id,
                    rec.slice_id,
                    key,
                    image_path,
                    cvat_url,
                    rec.unit,
                    cfg_v,
                    ds_v,
                ]
            )

    # Sort deterministically
    rows.sort(key=lambda r: (str(r[0]), str(r[1]), str(r[2])))

    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(AFFECTED_IMAGES_CSV_HEADERS)

    for row in rows:
        writer.writerow(row)

    return output.getvalue()


# ---------------------------------------------------------------------------
# Bundle Container and Top-Level Export
# ---------------------------------------------------------------------------

@dataclass
class CoverageExportBundle:
    """Container holding all four standardized Phase 4.1 export artifacts."""

    metrics_csv: str
    recommendations_csv: str
    affected_images_csv: str
    config_json: str

    def to_dict(self) -> dict[str, str]:
        """Return a mapping from canonical artifact filename to content string."""
        return {
            "metrics.csv": self.metrics_csv,
            "recommendations.csv": self.recommendations_csv,
            "affected_images.csv": self.affected_images_csv,
            "config.json": self.config_json,
        }

    def write_to_directory(self, output_dir: str | Path) -> dict[str, Path]:
        """Write all four artifacts to the specified directory."""
        target_dir = Path(output_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        written: dict[str, Path] = {}
        for filename, content in self.to_dict().items():
            dest = target_dir / filename
            dest.write_text(content, encoding="utf-8")
            written[filename] = dest
        return written


def export_coverage_bundle(
    slice_results: dict[str, SliceEvaluationResult]
    | list[SliceEvaluationResult]
    | DatasetCoverageResult
    | None = None,
    recommendations: list[Recommendation] | None = None,
    config: CoverageConfig | dict[str, Any] | None = None,
    images: list[ImageRecord] | dict[str, ImageRecord] | None = None,
    cvat_mapping: dict[str, Any] | Callable[..., str | None] | None = None,
    dataset_version: str = "",
    config_version: str | None = None,
    base_url: str = "",
    output_dir: str | Path | None = None,
) -> CoverageExportBundle:
    """Primary entry point for exporting all four coverage and recommendation artifacts.

    Generates:
    1. metrics.csv
    2. recommendations.csv
    3. affected_images.csv
    4. config.json

    If recommendations is None, config is a valid CoverageConfig, and slice_results
    is provided, recommendations are automatically generated via Phase 3 engine.
    """
    # 1. Resolve configuration
    actual_config: CoverageConfig | None = None
    if isinstance(config, CoverageConfig):
        actual_config = config
    elif isinstance(config, dict):
        try:
            from core.coverage_config import validate_coverage_config

            val_res = validate_coverage_config(config)
            if val_res.valid and val_res.config is not None:
                actual_config = val_res.config
        except Exception:
            actual_config = None

    resolved_config_version = (
        config_version
        if config_version is not None
        else (actual_config.config_version if actual_config is not None else "1")
    )

    # 2. Automatically generate recommendations if needed
    active_recs = recommendations
    if (
        active_recs is None
        and actual_config is not None
        and slice_results is not None
    ):
        if isinstance(slice_results, DatasetCoverageResult):
            active_recs = []
        else:
            img_list = list(images.values()) if isinstance(images, dict) else images
            active_recs = recommend(
                slice_results=slice_results,
                config=actual_config,
                dataset_version=dataset_version,
                images=img_list,
            )

    # 3. Export artifacts
    metrics_str = export_metrics_csv(
        slice_results=slice_results,
        config=actual_config,
        dataset_version=dataset_version,
        config_version=resolved_config_version,
    )

    recs_str = export_recommendations_csv(
        recommendations=active_recs,
        dataset_version=dataset_version,
        config_version=resolved_config_version,
    )

    affected_str = export_affected_images_csv(
        recommendations=active_recs,
        images=images,
        cvat_mapping=cvat_mapping,
        dataset_version=dataset_version,
        config_version=resolved_config_version,
        base_url=base_url,
    )

    config_str = export_config_json(config=config or actual_config)

    bundle = CoverageExportBundle(
        metrics_csv=metrics_str,
        recommendations_csv=recs_str,
        affected_images_csv=affected_str,
        config_json=config_str,
    )

    if output_dir is not None:
        bundle.write_to_directory(output_dir)

    return bundle
