"""Recommendation engine for N2-05B Data Quality & Coverage.

Strictly follows:
- FEEDBACK/Recommended-solution_DAT/Coverage_Recommendation_Engine_Coding_Spec_N2-05B.md §6, §7, §8, §10, §11
- FEEDBACK/Recommended-solution_DAT/Co_so_ly_thuyet_Data_Quality_Coverage_N2-05B.md §6, §7, §12
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from core.coverage_config import CoverageConfig, MetadataPolicy, SliceDefinition
from core.schema import ImageRecord
from core.slice_engine import SliceEvaluationResult


# ---------------------------------------------------------------------------
# Constants and Enums
# ---------------------------------------------------------------------------

SEVERITY_ORDER: dict[str, int] = {
    "blocker": 4,
    "review_required": 3,
    "planning": 2,
    "info": 1,
}

VALID_SEVERITIES: frozenset[str] = frozenset(SEVERITY_ORDER.keys())

VALID_CATEGORIES: frozenset[str] = frozenset(
    {
        "collection_gap",
        "metadata_quality",
        "review_handoff",
        "diversity_gap",
        "redundancy_issue",
        "efficiency_issue",
    }
)

VALID_EVIDENCE_STATUSES: frozenset[str] = frozenset(
    {
        "observed_annotation",
        "provisional",
        "unresolved_metadata",
        "audited_quality",
        "not_available",
    }
)


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class Recommendation:
    """Standard recommendation output conforming strictly to Coding Spec §8 contract."""

    recommendation_id: str
    slice_id: str
    rule_ids: list[str]
    category: str
    severity: str  # 'blocker', 'review_required', 'planning', 'info'
    evidence_status: str  # 'observed_annotation', 'provisional', 'unresolved_metadata', 'audited_quality'
    support: int
    target: int
    gap: int
    attainment: float
    priority: float
    unit: str  # 'image' or 'object'
    title: str
    actions: list[str]
    remeasure: list[str]
    limitations: list[str]
    affected_image_keys: list[str] = field(default_factory=list)
    config_version: str = "1"
    dataset_version: str = ""
    target_reason: str = ""
    status: str = "active"  # 'active', 'skipped', 'not_available'
    skip_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert recommendation to JSON-compatible dictionary per Specification §8."""
        data: dict[str, Any] = {
            "recommendation_id": self.recommendation_id,
            "slice_id": self.slice_id,
            "rule_ids": list(self.rule_ids),
            "category": self.category,
            "severity": self.severity,
            "evidence_status": self.evidence_status,
            "support": self.support,
            "target": self.target,
            "gap": self.gap,
            "attainment": round(float(self.attainment), 4),
            "priority": round(float(self.priority), 4),
            "unit": self.unit,
            "title": self.title,
            "actions": list(self.actions),
            "remeasure": list(self.remeasure),
            "limitations": list(self.limitations),
            "affected_image_keys": list(self.affected_image_keys),
            "config_version": self.config_version,
            "dataset_version": self.dataset_version,
        }
        if self.target_reason:
            data["target_reason"] = self.target_reason
        if self.status != "active":
            data["status"] = self.status
            data["skip_reason"] = self.skip_reason
        return data


@dataclass
class SkippedRuleResult:
    """Explicit report for a rule that was skipped due to missing or unavailable inputs."""

    rule_id: str
    rule_name: str
    status: str = "not_available"  # 'not_available' or 'skipped'
    reason: str = ""
    slice_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "status": self.status,
            "reason": self.reason,
            "slice_id": self.slice_id,
        }


@dataclass
class RuleTrigger:
    """Internal representation of a triggered rule before per-slice deduplication/merging."""

    rule_id: str
    slice_id: str
    category: str
    severity: str
    evidence_status: str
    title: str
    actions: list[str]
    remeasure: list[str]
    limitations: list[str]
    affected_image_keys: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Individual Deterministic Rule Evaluators
# ---------------------------------------------------------------------------

def evaluate_r01_zero_support(
    slice_def: SliceDefinition,
    eval_result: SliceEvaluationResult,
) -> RuleTrigger | None:
    """Rule R01 ZERO_SUPPORT: support is zero and target is positive.

    Coding Spec §6:
    - Condition: support=0, target>0
    - Action: Kiểm tra metadata, schema/class và tính khả thi; thiếu thật mới thu thập chuyên biệt.
    - Remeasure: Support, gap
    - Severity: planning
    """
    if not slice_def.enabled or slice_def.feasibility == "infeasible":
        return None

    if eval_result.support == 0 and eval_result.target_count > 0:
        is_provisional = eval_result.unresolved_count > 0
        evidence_status = "provisional" if is_provisional else "observed_annotation"

        actions = [
            "Kiểm tra metadata, schema/class và tính khả thi của slice",
            "Nếu xác nhận thiếu thật, tiến hành thu thập và gán nhãn chuyên biệt",
        ]
        remeasure = ["support", "gap"]
        limitations = [
            "Support dựa trên annotation đã ghi nhận, có thể còn nhãn sót",
            "Cần kiểm tra metadata trước khi kết luận thiếu ảnh thật",
        ]

        title = f"Chưa có mẫu nào cho slice '{eval_result.slice_name}' (support=0/{eval_result.target_count})"

        # Spec §8: Nếu zero support, affected_image_keys có thể rỗng; không dựng ảnh giả
        return RuleTrigger(
            rule_id="R01",
            slice_id=slice_def.id,
            category="collection_gap",
            severity="planning",
            evidence_status=evidence_status,
            title=title,
            actions=actions,
            remeasure=remeasure,
            limitations=limitations,
            affected_image_keys=[],
        )
    return None


def evaluate_r02_below_target(
    slice_def: SliceDefinition,
    eval_result: SliceEvaluationResult,
) -> RuleTrigger | None:
    """Rule R02 BELOW_TARGET: support is above zero but below target.

    Coding Spec §6:
    - Condition: 0 < support < target
    - Action: Review mẫu; bổ sung slice thiếu theo ưu tiên.
    - Remeasure: Attainment, coverage
    - Severity: planning
    """
    if not slice_def.enabled or slice_def.feasibility == "infeasible":
        return None

    if 0 < eval_result.support < eval_result.target_count:
        is_provisional = eval_result.unresolved_count > 0
        evidence_status = "provisional" if is_provisional else "observed_annotation"

        actions = [
            "Review các mẫu hiện có để đánh giá chất lượng nhãn",
            "Bổ sung mẫu cho slice theo thứ tự ưu tiên",
        ]
        remeasure = ["attainment", "coverage", "support", "gap"]
        limitations = [
            "Support dựa trên annotation đã ghi nhận, có thể còn nhãn sót",
        ]

        title = (
            f"Độ bao phủ chưa đạt mục tiêu cho slice '{eval_result.slice_name}' "
            f"(support={eval_result.support}/{eval_result.target_count})"
        )

        # Extract parent image keys for matched units
        affected_keys = _extract_image_keys(eval_result.matched_keys, eval_result.unit)

        return RuleTrigger(
            rule_id="R02",
            slice_id=slice_def.id,
            category="collection_gap",
            severity="planning",
            evidence_status=evidence_status,
            title=title,
            actions=actions,
            remeasure=remeasure,
            limitations=limitations,
            affected_image_keys=affected_keys,
        )
    return None


def evaluate_r06_metadata_insufficient(
    slice_def: SliceDefinition,
    eval_result: SliceEvaluationResult,
    metadata_policy: MetadataPolicy,
    images: list[ImageRecord] | None = None,
) -> RuleTrigger | None:
    """Rule R06 METADATA_INSUFFICIENT.

    Required metadata missing, unknown, invalid, or conflicting exceeds policy threshold.

    Coding Spec §6:
    - Condition: missing/unknown/invalid/conflict ở trường cần cho slice vượt policy
    - Action: Bổ sung tags/CSV hoặc review; không kết luận thiếu ảnh thật
    - Remeasure: Availability và support
    - Severity: review_required
    """
    if not slice_def.enabled or slice_def.feasibility == "infeasible":
        return None

    filters = slice_def.filters
    required_metadata_fields = [f for f in ("timeofday", "weather") if f in filters]
    if not required_metadata_fields:
        return None

    missing_threshold = metadata_policy.missing_warning_rate
    unknown_threshold = metadata_policy.unknown_warning_rate

    is_exceeded = False
    reasons: list[str] = []

    # 1. If images are provided, perform field-level analysis
    if images is not None and len(images) > 0:
        from core.slice_engine import get_image_metadata_info
        from core.validation import MetadataState

        total_imgs = len(images)
        for f in required_metadata_fields:
            missing_count = 0
            unknown_count = 0
            invalid_or_conflict = 0

            for img in images:
                state, _, is_conflict = get_image_metadata_info(img, f)
                if is_conflict:
                    invalid_or_conflict += 1
                elif state == MetadataState.MISSING:
                    missing_count += 1
                elif state == MetadataState.UNKNOWN:
                    unknown_count += 1
                elif state == MetadataState.INVALID:
                    invalid_or_conflict += 1

            miss_rate = missing_count / total_imgs
            unk_rate = unknown_count / total_imgs

            if miss_rate > missing_threshold:
                is_exceeded = True
                reasons.append(
                    f"Trường '{f}' có tỷ lệ thiếu ({miss_rate:.1%}) vượt ngưỡng policy ({missing_threshold:.1%})"
                )
            if unk_rate > unknown_threshold:
                is_exceeded = True
                reasons.append(
                    f"Trường '{f}' có tỷ lệ unknown ({unk_rate:.1%}) vượt ngưỡng policy ({unknown_threshold:.1%})"
                )
            if invalid_or_conflict > 0:
                inv_rate = invalid_or_conflict / total_imgs
                if inv_rate > missing_threshold:
                    is_exceeded = True
                    reasons.append(
                        f"Trường '{f}' có tỷ lệ không hợp lệ/xung đột ({inv_rate:.1%}) vượt ngưỡng policy"
                    )

    # 2. If images not available or not exceeded from images, check eval_result.metadata_availability
    if not is_exceeded:
        for f in required_metadata_fields:
            avail = eval_result.metadata_availability.get(f)
            if avail is not None:
                unavail_rate = 1.0 - avail
                # Compare against configured thresholds
                if unavail_rate > missing_threshold or unavail_rate > unknown_threshold:
                    is_exceeded = True
                    reasons.append(
                        f"Độ khả dụng trường '{f}' ({avail:.1%}) dưới ngưỡng cho phép; "
                        f"tỷ lệ chưa xác định ({unavail_rate:.1%}) vượt ngưỡng"
                    )

    # 3. Check unresolved count relative to evaluated candidates
    if not is_exceeded and eval_result.unresolved_count > 0:
        total_eval = eval_result.support + eval_result.unresolved_count
        if total_eval > 0:
            unresolved_rate = eval_result.unresolved_count / total_eval
            if unresolved_rate > missing_threshold or unresolved_rate > unknown_threshold:
                is_exceeded = True
                reasons.append(
                    f"Tỷ lệ mẫu chưa xác định ({unresolved_rate:.1%}, {eval_result.unresolved_count} mẫu) vượt ngưỡng policy"
                )

    if is_exceeded:
        actions = [
            "Bổ sung tags/CSV metadata hoặc tiến hành review xác minh metadata",
            "Không kết luận thiếu ảnh thật khi chưa xác minh metadata đầy đủ",
        ]
        remeasure = ["availability", "support"]
        limitations = [
            "Metadata thiếu hoặc chưa rõ không được xem là chứng minh thiếu dữ liệu thật",
            "Không tự suy đoán tỷ lệ phân bố sang các ảnh chưa xác định",
        ]

        title = f"Metadata chưa đầy đủ hoặc có xung đột cho slice '{eval_result.slice_name}'"

        # Affected images are the unresolved candidates needing metadata completion
        affected_keys = _extract_image_keys(eval_result.unresolved_keys, eval_result.unit)

        return RuleTrigger(
            rule_id="R06",
            slice_id=slice_def.id,
            category="metadata_quality",
            severity="review_required",
            evidence_status="unresolved_metadata",
            title=title,
            actions=actions,
            remeasure=remeasure,
            limitations=limitations,
            affected_image_keys=affected_keys,
        )

    return None


def evaluate_r11_critical_rare_gap(
    slice_def: SliceDefinition,
    eval_result: SliceEvaluationResult,
    critical_weight: float = 3.0,
) -> RuleTrigger | None:
    """Rule R11 CRITICAL_RARE_GAP.

    Support is below target and weight meets the configured critical-weight threshold.

    Coding Spec §6:
    - Condition: support < target và weight >= critical_weight
    - Action: Ưu tiên thu thập chuyên biệt; ghi giới hạn nếu chưa đạt
    - Remeasure: Weighted coverage
    - Severity: planning
    """
    if not slice_def.enabled or slice_def.feasibility == "infeasible":
        return None

    if eval_result.support < eval_result.target_count and eval_result.weight >= critical_weight:
        is_provisional = eval_result.unresolved_count > 0
        evidence_status = "provisional" if is_provisional else "observed_annotation"

        actions = [
            "Ưu tiên thu thập chuyên biệt cho ca hiếm có trọng số quan trọng",
            "Đảm bảo nguồn thu thập đa dạng, tránh chỉ lấy thêm frame cùng cảnh",
            "Ghi nhận giới hạn nếu chưa đạt mục tiêu sau thu thập",
        ]
        remeasure = ["weighted_coverage", "support", "gap", "independent_source_support"]
        limitations = [
            "Ca hiếm có rủi ro cao nếu thiếu mẫu; không thay thế bằng frame gần trùng",
            "Support dựa trên annotation đã ghi nhận",
        ]

        title = (
            f"Khoảng thiếu nghiêm trọng ở ca hiếm trọng số cao cho slice '{eval_result.slice_name}' "
            f"(weight={eval_result.weight}, gap={eval_result.gap})"
        )

        affected_keys = _extract_image_keys(eval_result.matched_keys, eval_result.unit)

        return RuleTrigger(
            rule_id="R11",
            slice_id=slice_def.id,
            category="collection_gap",
            severity="planning",
            evidence_status=evidence_status,
            title=title,
            actions=actions,
            remeasure=remeasure,
            limitations=limitations,
            affected_image_keys=affected_keys,
        )
    return None


def evaluate_r12_targets_met(
    slice_def: SliceDefinition,
    eval_result: SliceEvaluationResult,
    has_mandatory_blockers: bool = False,
) -> RuleTrigger | None:
    """Rule R12 TARGETS_MET.

    Required slices meet target and have no unresolved metadata or blockers.

    Coding Spec §6:
    - Condition: slice bắt buộc đạt target, không unresolved/blocker
    - Action: Chuyển review/bàn giao; vẫn kiểm tra chất lượng và đa dạng nguồn
    - Remeasure: Audited quality
    - Severity: info
    """
    # R12 applies only to required (confirmed, enabled) slices
    if not slice_def.enabled or slice_def.feasibility != "confirmed":
        return None

    # Never emit a handoff recommendation while mandatory blockers remain
    if has_mandatory_blockers:
        return None

    # Slice must meet target
    if eval_result.support < eval_result.target_count:
        return None

    # Slice must have no unresolved metadata
    if eval_result.unresolved_count > 0:
        return None

    actions = [
        "Chuyển sang quy trình review chất lượng nhãn và kiểm tra tính đa dạng nguồn",
        "Kiểm tra chất lượng kiểm toán (audited error rate) trước khi nghiệm thu bàn giao",
    ]
    remeasure = ["audited_quality", "independent_source_support"]
    limitations = [
        "Đạt mục tiêu số lượng theo kế hoạch chưa đảm bảo độ chính xác của mô hình",
        "Cần tiếp tục kiểm tra chất lượng nhãn và tính độc lập của các nguồn",
    ]

    title = (
        f"Slice '{eval_result.slice_name}' đã đạt mục tiêu độ bao phủ "
        f"({eval_result.support}/{eval_result.target_count}); sẵn sàng chuyển bước review/bàn giao"
    )

    affected_keys = _extract_image_keys(eval_result.matched_keys, eval_result.unit)

    return RuleTrigger(
        rule_id="R12",
        slice_id=slice_def.id,
        category="review_handoff",
        severity="info",
        evidence_status="audited_quality",
        title=title,
        actions=actions,
        remeasure=remeasure,
        limitations=limitations,
        affected_image_keys=affected_keys,
    )


# ---------------------------------------------------------------------------
# Deduplication and Merging per Slice
# ---------------------------------------------------------------------------

def merge_slice_triggers(
    triggers: list[RuleTrigger],
    slice_def: SliceDefinition,
    eval_result: SliceEvaluationResult,
    dataset_id: str = "dataset",
    config_version: str = "1",
    dataset_version: str = "",
) -> Recommendation:
    """Merge multiple applicable rules for the same slice into one recommendation.

    Specification requirements:
    - Preserve all applicable rule_ids or reason codes.
    - Highest severity takes precedence (blocker > review_required > planning > info).
    - Combine actions, remeasure metrics, and limitations without duplication.
    - Title synthesizes the most urgent triage aspect.
    """
    rule_ids = sorted([t.rule_id for t in triggers])

    # Determine highest severity
    severities = [t.severity for t in triggers]
    highest_severity = max(severities, key=lambda s: SEVERITY_ORDER.get(s, 0))

    # Determine category
    # If metadata issue present, primary immediate category is metadata_quality
    # Otherwise collection_gap or review_handoff
    if any(t.rule_id == "R06" for t in triggers):
        category = "metadata_quality"
    elif any(t.rule_id == "R12" for t in triggers):
        category = "review_handoff"
    else:
        category = "collection_gap"

    # Determine evidence status
    if any(t.evidence_status == "unresolved_metadata" for t in triggers):
        evidence_status = "unresolved_metadata"
    elif any(t.evidence_status == "provisional" for t in triggers):
        evidence_status = "provisional"
    elif any(t.evidence_status == "audited_quality" for t in triggers):
        evidence_status = "audited_quality"
    else:
        evidence_status = "observed_annotation"

    # Merge actions preserving order
    combined_actions: list[str] = []
    seen_actions: set[str] = set()
    for t in triggers:
        for a in t.actions:
            if a not in seen_actions:
                seen_actions.add(a)
                combined_actions.append(a)

    # Merge remeasure metrics
    combined_remeasure: list[str] = []
    seen_remeasure: set[str] = set()
    for t in triggers:
        for m in t.remeasure:
            if m not in seen_remeasure:
                seen_remeasure.add(m)
                combined_remeasure.append(m)

    # Merge limitations
    combined_limitations: list[str] = []
    seen_limitations: set[str] = set()
    for t in triggers:
        for lim in t.limitations:
            if lim not in seen_limitations:
                seen_limitations.add(lim)
                combined_limitations.append(lim)

    # Merge affected keys
    combined_affected: list[str] = []
    seen_affected: set[str] = set()
    for t in triggers:
        for k in t.affected_image_keys:
            if k not in seen_affected:
                seen_affected.add(k)
                combined_affected.append(k)

    # Construct synthesized title
    if "R06" in rule_ids and ("R01" in rule_ids or "R02" in rule_ids or "R11" in rule_ids):
        title = (
            f"Ưu tiên xác minh metadata và đánh giá khoảng thiếu cho slice '{eval_result.slice_name}' "
            f"(unresolved={eval_result.unresolved_count}, support={eval_result.support}/{eval_result.target_count})"
        )
    elif "R11" in rule_ids and "R01" in rule_ids:
        title = (
            f"Ưu tiên kiểm tra và thu thập chuyên biệt cho ca hiếm '{eval_result.slice_name}' "
            f"(support=0/{eval_result.target_count}, weight={eval_result.weight})"
        )
    elif "R11" in rule_ids and "R02" in rule_ids:
        title = (
            f"Ưu tiên kiểm tra và bổ sung {eval_result.slice_name} "
            f"(ca hiếm trọng số cao, weight={eval_result.weight}, gap={eval_result.gap})"
        )
    elif "R12" in rule_ids:
        title = (
            f"Slice '{eval_result.slice_name}' đã đạt mục tiêu độ bao phủ "
            f"({eval_result.support}/{eval_result.target_count}); sẵn sàng chuyển bước review/bàn giao"
        )
    elif triggers:
        title = triggers[0].title
    else:
        title = f"Đề xuất cho slice '{eval_result.slice_name}'"

    clean_dataset_id = dataset_id.replace(":", "_").replace("/", "_")
    rec_id = f"{clean_dataset_id}_{slice_def.id}_v{config_version}"

    return Recommendation(
        recommendation_id=rec_id,
        slice_id=slice_def.id,
        rule_ids=rule_ids,
        category=category,
        severity=highest_severity,
        evidence_status=evidence_status,
        support=eval_result.support,
        target=eval_result.target_count,
        gap=eval_result.gap,
        attainment=eval_result.attainment,
        priority=eval_result.priority,
        unit=eval_result.unit,
        title=title,
        actions=combined_actions,
        remeasure=combined_remeasure,
        limitations=combined_limitations,
        affected_image_keys=combined_affected,
        config_version=config_version,
        dataset_version=dataset_version,
        target_reason=slice_def.target_reason,
    )


def _extract_image_keys(keys: list[str], unit: str) -> list[str]:
    """Helper to extract clean unique image_key identifiers from matched/unresolved keys."""
    res: list[str] = []
    seen: set[str] = set()
    for k in keys:
        if unit == "object" and ":" in k:
            # object_key might be dataset_id:object_id, but if resolve logic stored it,
            # we keep unique image keys
            parts = k.split(":")
            img_k = f"{parts[0]}:{parts[1]}" if len(parts) >= 2 else k
        else:
            img_k = k
        if img_k not in seen:
            seen.add(img_k)
            res.append(img_k)
    return res


# ---------------------------------------------------------------------------
# Unavailable Inputs and Skipped Rules Checker (R03-R10)
# ---------------------------------------------------------------------------

def get_skipped_rules(
    slice_results: dict[str, SliceEvaluationResult] | list[SliceEvaluationResult],
    config: CoverageConfig,
    collection_results: Any = None,
    sources: Any = None,
) -> list[SkippedRuleResult]:
    """Evaluate skipped/not-available rules due to missing inputs per Specification §6 & §10.

    Requirements:
    - Never fabricate unavailable evidence (sources, logs, efficiency).
    - Return explicit skipped/not-available result with clear justification.
    """
    skipped: list[SkippedRuleResult] = []

    if isinstance(slice_results, dict):
        results_list = list(slice_results.values())
    else:
        results_list = list(slice_results)

    # R03: LOW_SOURCE_DIVERSITY
    # Needs source tracking data (source_id)
    has_any_source_support = any(
        r.source_support_status == "available" for r in results_list
    )
    if not has_any_source_support and sources is None:
        skipped.append(
            SkippedRuleResult(
                rule_id="R03",
                rule_name="LOW_SOURCE_DIVERSITY",
                status="not_available",
                reason="Dữ liệu nguồn độc lập (source_id) không có sẵn; không thể đánh giá độ đa dạng nguồn.",
            )
        )

    # R04: REDUNDANCY_HIGH
    # Needs confirmed duplicate groups
    skipped.append(
        SkippedRuleResult(
            rule_id="R04",
            rule_name="REDUNDANCY_HIGH",
            status="not_available",
            reason="Dữ liệu nhóm ảnh trùng (duplicate_groups) chưa được cung cấp; không suy đoán ảnh trùng từ tên file.",
        )
    )

    # R05: JOINT_GAP
    # Needs explicit marginal slice configuration
    skipped.append(
        SkippedRuleResult(
            rule_id="R05",
            rule_name="JOINT_GAP",
            status="not_available",
            reason="Cấu hình marginal_slice_ids chưa được thiết lập; không tự suy đoán mục tiêu marginal.",
        )
    )

    # R07: LOW_USEFUL_YIELD
    # Needs collection_log
    if collection_results is None:
        skipped.append(
            SkippedRuleResult(
                rule_id="R07",
                rule_name="LOW_USEFUL_YIELD",
                status="not_available",
                reason="Nhật ký thu thập (collection_log) không có sẵn; không thể đo tỷ lệ mẫu hữu ích.",
            )
        )

    # R08: LOW_ACCEPTANCE
    if collection_results is None:
        skipped.append(
            SkippedRuleResult(
                rule_id="R08",
                rule_name="LOW_ACCEPTANCE",
                status="not_available",
                reason="Nhật ký ứng viên thu thập không có sẵn; không thể đo tỷ lệ chấp nhận (acceptance rate).",
            )
        )

    # R09: LOW_EFFICIENCY
    if collection_results is None:
        skipped.append(
            SkippedRuleResult(
                rule_id="R09",
                rule_name="LOW_EFFICIENCY",
                status="not_available",
                reason="Nhật ký chi phí/thời gian thu thập không có sẵn; không thể đo hiệu quả chi phí.",
            )
        )

    # R10: LOW_COVERAGE_GAIN
    skipped.append(
        SkippedRuleResult(
            rule_id="R10",
            rule_name="LOW_COVERAGE_GAIN",
            status="not_available",
            reason="Chưa có snapshot tham chiếu tương thích để so sánh mức tăng độ bao phủ (coverage gain).",
        )
    )

    return skipped


# ---------------------------------------------------------------------------
# Recommendation Engine Class & Top-Level API
# ---------------------------------------------------------------------------

class RecommendationEngine:
    """Deterministic, UI-independent recommendation engine for N2-05B."""

    def __init__(
        self,
        config: CoverageConfig,
        dataset_id: str = "dataset",
        dataset_version: str = "v1",
        critical_weight: float = 3.0,
    ) -> None:
        self.config = config
        self.dataset_id = dataset_id
        self.dataset_version = dataset_version
        self.critical_weight = getattr(config, "critical_weight", critical_weight)
        self.slices_by_id: dict[str, SliceDefinition] = {s.id: s for s in config.slices}

    def generate_recommendations(
        self,
        slice_results: dict[str, SliceEvaluationResult] | list[SliceEvaluationResult],
        collection_results: Any = None,
        images: list[ImageRecord] | None = None,
        mandatory_blockers: list[str] | None = None,
        include_skipped: bool = False,
    ) -> list[Recommendation]:
        """Generate deduplicated recommendations across all evaluated slices."""
        if isinstance(slice_results, dict):
            results_dict = slice_results
        else:
            results_dict = {r.slice_id: r for r in slice_results}

        # Step 1: Detect presence of any mandatory blocker across the evaluation
        has_mandatory_blockers = False
        if mandatory_blockers and len(mandatory_blockers) > 0:
            has_mandatory_blockers = True

        # Check if any required slice has unresolved metadata blockers
        for s_id, eval_res in results_dict.items():
            s_def = self.slices_by_id.get(s_id)
            if s_def and s_def.enabled and s_def.feasibility == "confirmed":
                if eval_res.unresolved_count > 0:
                    has_mandatory_blockers = True
                    break

        recommendations: list[Recommendation] = []

        # Step 2: Evaluate individual rules for each slice
        for s_id, eval_res in results_dict.items():
            s_def = self.slices_by_id.get(s_id)
            if s_def is None or not s_def.enabled:
                continue

            triggers: list[RuleTrigger] = []

            # Evaluate R06 (Metadata) first according to triage hierarchy
            t_r06 = evaluate_r06_metadata_insufficient(
                s_def,
                eval_res,
                self.config.metadata_policy,
                images=images,
            )
            if t_r06 is not None:
                triggers.append(t_r06)

            # Evaluate R01 (Zero support)
            t_r01 = evaluate_r01_zero_support(s_def, eval_res)
            if t_r01 is not None:
                triggers.append(t_r01)

            # Evaluate R02 (Below target)
            t_r02 = evaluate_r02_below_target(s_def, eval_res)
            if t_r02 is not None:
                triggers.append(t_r02)

            # Evaluate R11 (Critical rare gap)
            t_r11 = evaluate_r11_critical_rare_gap(
                s_def,
                eval_res,
                critical_weight=self.critical_weight,
            )
            if t_r11 is not None:
                triggers.append(t_r11)

            # Evaluate R12 (Targets met)
            t_r12 = evaluate_r12_targets_met(
                s_def,
                eval_res,
                has_mandatory_blockers=has_mandatory_blockers,
            )
            if t_r12 is not None:
                triggers.append(t_r12)

            # If any rule triggered for this slice, merge into exactly ONE recommendation
            if triggers:
                merged_rec = merge_slice_triggers(
                    triggers=triggers,
                    slice_def=s_def,
                    eval_result=eval_res,
                    dataset_id=self.dataset_id,
                    config_version=self.config.config_version,
                    dataset_version=self.dataset_version,
                )
                recommendations.append(merged_rec)

        # Step 3: Handle skipped rules if requested
        if include_skipped:
            skipped_list = get_skipped_rules(
                slice_results=results_dict,
                config=self.config,
                collection_results=collection_results,
            )
            for sk in skipped_list:
                skipped_rec = Recommendation(
                    recommendation_id=f"{self.dataset_id}_{sk.rule_id}_skipped",
                    slice_id=sk.slice_id or "__global__",
                    rule_ids=[sk.rule_id],
                    category="collection_gap",
                    severity="info",
                    evidence_status="not_available",
                    support=0,
                    target=0,
                    gap=0,
                    attainment=0.0,
                    priority=0.0,
                    unit="image",
                    title=f"Rule {sk.rule_id} ({sk.rule_name}) không khả dụng",
                    actions=["Cung cấp thêm dữ liệu đầu vào cần thiết để kích hoạt luật này"],
                    remeasure=[],
                    limitations=[sk.reason],
                    affected_image_keys=[],
                    config_version=self.config.config_version,
                    dataset_version=self.dataset_version,
                    status="not_available",
                    skip_reason=sk.reason,
                )
                recommendations.append(skipped_rec)

        # Step 4: Deterministic triage ordering
        # Hierarchy:
        # 1. Severity rank descending (blocker=4 > review_required=3 > planning=2 > info=1)
        # 2. Numerical priority descending
        # 3. slice_id ascending (stable deterministic tie-breaker)
        recommendations.sort(
            key=lambda r: (
                -SEVERITY_ORDER.get(r.severity, 0),
                -r.priority,
                r.slice_id,
            )
        )

        return recommendations


def recommend(
    slice_results: dict[str, SliceEvaluationResult] | list[SliceEvaluationResult],
    arg2: Any = None,
    arg3: Any = None,
    *,
    config: CoverageConfig | None = None,
    collection_results: Any = None,
    dataset_id: str = "dataset",
    dataset_version: str = "v1",
    critical_weight: float = 3.0,
    include_skipped: bool = False,
    images: list[ImageRecord] | None = None,
    mandatory_blockers: list[str] | None = None,
) -> list[Recommendation]:
    """Primary public interface for recommendation generation.

    Flexible signature accommodates:
    - recommend(slice_results, config)
    - recommend(slice_results, collection_results, config)
    - recommend(slice_results, config=config, ...)
    """
    actual_config: CoverageConfig | None = None
    actual_collection: Any = None

    if isinstance(arg2, CoverageConfig):
        actual_config = arg2
        actual_collection = arg3 if arg3 is not None else collection_results
    elif isinstance(arg3, CoverageConfig):
        actual_config = arg3
        actual_collection = arg2 if arg2 is not None else collection_results
    elif config is not None:
        actual_config = config
        actual_collection = collection_results if collection_results is not None else arg2
    else:
        raise ValueError("CoverageConfig instance must be provided to recommend().")

    engine = RecommendationEngine(
        config=actual_config,
        dataset_id=dataset_id,
        dataset_version=dataset_version,
        critical_weight=critical_weight,
    )

    return engine.generate_recommendations(
        slice_results=slice_results,
        collection_results=actual_collection,
        images=images,
        mandatory_blockers=mandatory_blockers,
        include_skipped=include_skipped,
    )
