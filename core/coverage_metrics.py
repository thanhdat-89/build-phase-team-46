"""Coverage metrics calculation layer for N2-05B.

Strictly follows:
- FEEDBACK/Recommended-solution_DAT/Coverage_Recommendation_Engine_Coding_Spec_N2-05B.md §5, §11
- FEEDBACK/Recommended-solution_DAT/Co_so_ly_thuyet_Data_Quality_Coverage_N2-05B.md §6
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from core.coverage_config import CoverageConfig, SliceDefinition
from core.slice_engine import SliceEvaluationResult


@dataclass
class DatasetCoverageResult:
    """Dataset-level coverage summary across all eligible slices."""

    total_slices: int
    eligible_slices_count: int
    met_slices_count: int
    unresolved_slices_count: int
    coverage: float | None
    weighted_coverage: float | None
    weighted_attainment: float | None
    status: str  # 'available' or 'not_available'
    is_provisional: bool
    targets_met: bool
    reasons: list[str] = field(default_factory=list)
    slice_metrics: dict[str, dict[str, Any]] = field(default_factory=dict)


def calculate_slice_metrics(
    eval_result: SliceEvaluationResult,
) -> dict[str, Any]:
    """Extract and format per-slice metrics conforming to specification contracts."""
    return {
        "slice_id": eval_result.slice_id,
        "slice_name": eval_result.slice_name,
        "unit": eval_result.unit,
        "support": eval_result.support,
        "target_count": eval_result.target_count,
        "weight": eval_result.weight,
        "gap": eval_result.gap,
        "attainment": eval_result.attainment,
        "priority": eval_result.priority,
        "unresolved_count": eval_result.unresolved_count,
        "source_support": eval_result.source_support,
        "source_support_status": eval_result.source_support_status,
        "metadata_availability": eval_result.metadata_availability,
        "excluded_invalid_geometry_count": eval_result.excluded_invalid_geometry_count,
        "status": eval_result.status,
    }


def calculate_dataset_coverage(
    slice_results: dict[str, SliceEvaluationResult] | list[SliceEvaluationResult],
    config: CoverageConfig | None = None,
) -> DatasetCoverageResult:
    """Calculate dataset-level coverage metrics for eligible slices S.

    Formulas (Coding Spec §5):
    - coverage = sum(support_s >= target_s) / |S|
    - weighted_coverage = sum(weight_s * (support_s >= target_s)) / sum(weight_s)
    - weighted_attainment = sum(weight_s * attainment_s) / sum(weight_s)

    Guards:
    - If |S| == 0: return None / not_available (Criterion 15).
    - If sum(weight_s) == 0: weighted values return None.
    - If unresolved metadata blockers exist: do not declare targets_met=True (Criterion 16).
    - Never sum slice gaps across overlapping slices (Criterion 9).
    """
    if isinstance(slice_results, dict):
        results_list = list(slice_results.values())
    else:
        results_list = list(slice_results)

    total_slices = len(results_list)

    # Determine eligible set S: enabled and not 'infeasible'
    infeasible_ids: set[str] = set()
    if config is not None:
        for s_def in config.slices:
            if not s_def.enabled or s_def.feasibility == "infeasible":
                infeasible_ids.add(s_def.id)

    eligible_results = [r for r in results_list if r.slice_id not in infeasible_ids]
    eligible_count = len(eligible_results)

    per_slice_dict: dict[str, dict[str, Any]] = {}
    for r in results_list:
        per_slice_dict[r.slice_id] = calculate_slice_metrics(r)

    reasons: list[str] = []

    # Handle empty eligible slice set (Criterion 15)
    if eligible_count == 0:
        return DatasetCoverageResult(
            total_slices=total_slices,
            eligible_slices_count=0,
            met_slices_count=0,
            unresolved_slices_count=0,
            coverage=None,
            weighted_coverage=None,
            weighted_attainment=None,
            status="not_available",
            is_provisional=False,
            targets_met=False,
            reasons=["No eligible slices available for evaluation (|S| = 0)."],
            slice_metrics=per_slice_dict,
        )

    met_count = sum(1 for r in eligible_results if r.support >= r.target_count)
    unresolved_slices_count = sum(1 for r in eligible_results if r.unresolved_count > 0)

    # Unweighted coverage
    coverage = met_count / eligible_count

    # Weighted metrics
    total_weight = sum(r.weight for r in eligible_results)
    if total_weight > 0 and not math.isnan(total_weight) and not math.isinf(total_weight):
        weighted_cov_num = sum(
            r.weight for r in eligible_results if r.support >= r.target_count
        )
        weighted_coverage = weighted_cov_num / total_weight

        weighted_att_num = sum(r.weight * r.attainment for r in eligible_results)
        weighted_attainment = weighted_att_num / total_weight
    else:
        weighted_coverage = None
        weighted_attainment = None

    is_provisional = unresolved_slices_count > 0

    # Targets met decision (Criterion 16)
    if met_count == eligible_count:
        if is_provisional:
            targets_met = False
            reasons.append(
                "All observed targets met, but unresolved metadata blockers remain. Final sign-off withheld."
            )
        else:
            targets_met = True
    else:
        targets_met = False
        reasons.append(f"{eligible_count - met_count} of {eligible_count} slices remain below target.")

    return DatasetCoverageResult(
        total_slices=total_slices,
        eligible_slices_count=eligible_count,
        met_slices_count=met_count,
        unresolved_slices_count=unresolved_slices_count,
        coverage=coverage,
        weighted_coverage=weighted_coverage,
        weighted_attainment=weighted_attainment,
        status="available",
        is_provisional=is_provisional,
        targets_met=targets_met,
        reasons=reasons,
        slice_metrics=per_slice_dict,
    )
