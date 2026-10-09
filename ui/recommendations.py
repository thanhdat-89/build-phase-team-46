"""Read-only Phase 4.3 panel; Coding Spec §§6–9 and Theory §§6,12.

The caller supplies one consistent dataset/configuration snapshot. CVAT mapping
entries must be explicitly caller-confirmed: {"confirmed": True, "url": ...}
or {"confirmed": True, "base_url": ..., "task_id": ..., "frame": ...,
"job_id": ...}. Only exact composite image keys are accepted. No short-ID or
filename guessing is performed. This module does not run recommendation rules.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import parse_qs, urlsplit

import streamlit as st

from core.coverage_config import CoverageConfig
from core.coverage_export import resolve_cvat_url
from core.recommendations import Recommendation, SEVERITY_ORDER
from core.schema import ImageRecord, ObjectRecord
from core.slice_engine import SliceEvaluationResult


EVIDENCE_TEXT = {
    "observed_annotation": "Quan sát từ annotation; không phải ground truth đã kiểm toán.",
    "provisional": "Tạm thời: cần xác minh dữ liệu chưa rõ trước khi kết luận thiếu ảnh thật.",
    "unresolved_metadata": "Metadata chưa xác định: cần bổ sung hoặc xác minh metadata.",
    "audited_quality": "Trạng thái do engine cung cấp; không chứng minh đã hoàn thành kiểm toán. Cần kết quả review riêng.",
    "not_available": "Chưa đủ đầu vào để đánh giá; không phải kết quả bằng không.",
}

REMEASURE_TEXT = {
    "support": "Sau khi cập nhật annotation/metadata, đếm lại đơn vị thỏa slice (image hoặc object).",
    "gap": "Tính lại khoảng thiếu so với target của slice sau khi có support mới.",
    "attainment": "Đo lại mức đạt target của slice sau cập nhật dữ liệu.",
    "coverage": "Tính lại tỷ lệ slice đủ target trên tập slice đủ điều kiện; giữ trạng thái provisional nếu còn unresolved.",
    "weighted_coverage": "Tính lại coverage theo trọng số đã cấu hình trên cùng phạm vi đánh giá.",
    "availability": "Sau bổ sung tags/CSV và review, đo lại độ khả dụng metadata cần cho slice và support.",
    "independent_source_support": "Chỉ đếm lại nguồn độc lập khi có mapping nguồn đã xác nhận theo quy ước dự án; nếu thiếu: N/A.",
    "audited_quality": "Thực hiện review chất lượng nhãn và ghi nhận kết quả kiểm toán riêng; XML và coverage không chứng minh accuracy.",
}


def display_value(value: Any, *, percent: bool = False) -> str:
    """Preserve unknown values rather than displaying a fabricated zero."""
    if value is None or value == "":
        return "N/A"
    if isinstance(value, int) and not percent:
        return f"{value:,}"
    if isinstance(value, (int, float)):
        if not math.isfinite(value):
            return "N/A"
        if isinstance(value, float) and value.is_integer() and not percent:
            return f"{value:,.0f}"
        return f"{value:.1%}" if percent else f"{value:g}"
    return str(value)


def ordered_recommendations(recommendations: Sequence[Recommendation]) -> list[Recommendation]:
    """Mirror engine ordering, adding an ID tie-break without changing inputs."""
    return sorted(recommendations, key=lambda r: (
        -SEVERITY_ORDER.get(r.severity, 0),
        -r.priority if r.priority is not None and math.isfinite(r.priority) else math.inf,
        r.slice_id, r.recommendation_id,
    ))


def validated_cvat_url(image_key: str, mappings: Mapping[str, Any] | None) -> str:
    """Validate caller confirmation and a task[/job]/frame URL before linking."""
    entry = mappings.get(image_key) if isinstance(mappings, Mapping) else None
    if not isinstance(entry, dict) or entry.get("confirmed") is not True:
        return ""
    if "url" not in entry:
        for name in ("task_id", "frame", "job_id"):
            value = entry.get(name)
            if name == "job_id" and value is None:
                continue
            if type(value) is not int or value < (0 if name == "frame" else 1):
                return ""
    url = resolve_cvat_url(image_key, cvat_mapping={image_key: entry})
    try:
        parts = urlsplit(url)
        _ = parts.port
        query = parse_qs(parts.query, keep_blank_values=True)
        if (parts.scheme not in {"http", "https"} or not parts.hostname
                or parts.username or parts.password or parts.fragment
                or any(c.isspace() or ord(c) < 32 for c in url)
                or "\\" in url
                or not re.fullmatch(r"/tasks/[1-9][0-9]*(?:/jobs/[1-9][0-9]*)?/?", parts.path)
                or set(query) != {"frame"} or len(query["frame"]) != 1
                or not re.fullmatch(r"[0-9]+", query["frame"][0])):
            return ""
    except (ValueError, TypeError):
        return ""
    return url


def affected_image_rows(
    recommendation: Recommendation,
    images: Sequence[ImageRecord] = (),
    objects: Sequence[ObjectRecord] = (),
    slice_result: SliceEvaluationResult | None = None,
    cvat_mapping: Mapping[str, Any] | None = None,
) -> list[dict[str, str]]:
    """Resolve real records, preserving role and reporting missing/ambiguous keys.

    Original slice object keys avoid the engine's lossy object-key extraction.
    Object parents are taken exclusively from ObjectRecord.image_key.
    """
    image_index: dict[str, list[ImageRecord]] = defaultdict(list)
    object_index: dict[str, list[ObjectRecord]] = defaultdict(list)
    for img in images:
        image_index[img.image_key].append(img)
    for obj in objects:
        object_index[obj.object_key].append(obj)
    # True/False identifies original slice object/image keys. None identifies
    # recommendation affected keys, whose canonical image identity takes
    # precedence over an object-key collision when an image record exists.
    evidence: list[tuple[str, str, bool | None]] = []
    if slice_result is not None and slice_result.slice_id == recommendation.slice_id:
        if "R06" in recommendation.rule_ids:
            evidence.extend((k, "metadata_correction", slice_result.unit == "object") for k in slice_result.unresolved_keys)
        if set(recommendation.rule_ids) & {"R02", "R11", "R12"}:
            evidence.extend((k, "existing_support", slice_result.unit == "object") for k in slice_result.matched_keys)
    else:
        # Without slice provenance, merged affected keys cannot be assigned a role.
        evidence.extend((k, "affected_unspecified", None) for k in recommendation.affected_image_keys)
    rows = []
    for key, role, is_object in evidence:
        image_key = key
        issue = ""
        if is_object is None:
            is_object = key not in image_index and (
                key in object_index or recommendation.unit == "object"
            )
        if is_object:
            parents = {obj.image_key for obj in object_index.get(key, [])}
            if len(parents) == 1:
                image_key = next(iter(parents))
            elif len(parents) > 1:
                issue = "ambiguous_object_mapping"
            else:
                issue = "missing_object_mapping"
        candidates = image_index.get(image_key, []) if not issue else []
        if not issue and len(candidates) > 1:
            issue = "ambiguous_image_mapping"
        elif not issue and not candidates:
            issue = "missing_image_record"
        path = candidates[0].image_path if not issue else ""
        rows.append({"image_key": image_key, "image_path": path or "",
                     "display": path or image_key, "role": role,
                     "mapping_status": issue or "resolved",
                     "cvat_url": validated_cvat_url(image_key, cvat_mapping) if not issue else ""})
    unique = {(r["role"], r["image_key"], r["mapping_status"]): r for r in rows}
    return [unique[k] for k in sorted(unique)]


def recommendation_evidence(rec: Recommendation) -> dict[str, str]:
    unavailable = rec.status in {"skipped", "not_available"} or rec.evidence_status == "not_available"
    return {name: display_value(None if unavailable else getattr(rec, name), percent=name == "attainment")
            for name in ("support", "target", "gap", "attainment", "priority")}


def render_recommendations(
    recommendations: Sequence[Recommendation], *,
    images: Sequence[ImageRecord] | None = None,
    objects: Sequence[ObjectRecord] | None = None,
    slice_results: Mapping[str, SliceEvaluationResult] | None = None,
    config: CoverageConfig | None = None,
    cvat_mapping: Mapping[str, Any] | None = None,
) -> None:
    """Render supplied results without recalculation, writes, or session state.

    Integration must pass context from the same measurement snapshot. Audit
    results are not part of this interface, so audit completion is never asserted.
    Supply the complete image/object sequences used by measure_slices to make
    availability interpretable. Omitted sequences have unknown denominators.
    """
    st.header("Khuyến nghị hành động")
    st.caption("Khoảng thiếu dựa trên annotation đã ghi nhận. Không cộng gap giữa các slice thành tổng ảnh cần lấy.")
    if not recommendations:
        st.info("Chưa có khuyến nghị được cung cấp. Điều này không xác nhận dữ liệu đã đạt yêu cầu hoặc không còn vấn đề.")
        return
    definitions = {s.id: s for s in config.slices} if config else {}
    for rec in ordered_recommendations(recommendations):
        with st.container(border=True):
            st.subheader(f"{rec.severity} · {rec.slice_id}")
            st.text(rec.title)
            st.text(f"Rules: {', '.join(rec.rule_ids)} | Category: {rec.category} | Unit: {rec.unit}")
            st.text(f"Evidence: {rec.evidence_status} — {EVIDENCE_TEXT.get(rec.evidence_status, 'Trạng thái chưa được nhận diện; cần xác minh.')} ")
            st.text(f"Status: {rec.status} | Dataset: {display_value(rec.dataset_version)} | Config: {display_value(rec.config_version)}")
            if rec.skip_reason:
                st.warning(rec.skip_reason)
            st.text("Bằng chứng: " + " | ".join(f"{k}: {v}" for k, v in recommendation_evidence(rec).items()))
            st.text(f"Lý do target: {display_value(rec.target_reason)}")
            result = (slice_results or {}).get(rec.slice_id)
            definition = definitions.get(rec.slice_id)
            if config and config.config_version != rec.config_version:
                st.warning("Phiên bản cấu hình không khớp; không dùng cấu hình hoặc slice context để bổ sung bằng chứng.")
                definition, result = None, None
            if result:
                st.text(f"Unresolved: {display_value(result.unresolved_count)} | Weight: {display_value(result.weight)} | Excluded geometry: {display_value(result.excluded_invalid_geometry_count)}")
                # slice_engine measures availability over all supplied images
                # (image unit) or objects (object unit), before slice filters.
                # It stores 0.0 for an empty denominator. Do not recompute a
                # rate or guess a denominator from support/unresolved counts.
                evaluated_records = images if result.unit == "image" else objects if result.unit == "object" else None
                has_denominator = evaluated_records is not None and len(evaluated_records) > 0
                st.text("Metadata availability: " + (", ".join(
                    f"{k}: {display_value(v if has_denominator else None, percent=True)}"
                    for k, v in result.metadata_availability.items()
                ) or "N/A"))
                st.caption("Mẫu số availability và giải thích chi tiết ngưỡng R06 không được cung cấp trong kết quả này.")
                st.text("Independent source support: " + display_value(result.source_support if result.source_support_status == "available" else None))
            if definition and (rec.category == "collection_gap" or set(rec.rule_ids) & {"R01", "R02", "R11"}):
                st.text("Điều kiện tìm mẫu mới (không phải ảnh đã có): " + str(definition.filters))
            st.markdown("**Xác minh và hành động đề xuất**")
            for index, action in enumerate(rec.actions, 1):
                st.text(f"{index}. {action}")
            for limitation in rec.limitations:
                st.text(f"Giới hạn: {limitation}")
            if "R12" in rec.rule_ids:
                st.warning("R12 là bước chuyển sang review cho slice; không xác nhận kiểm toán đã hoàn thành hay toàn dataset đủ điều kiện bàn giao.")
            st.markdown("**Đo lại / đánh giá lại sau hành động**")
            st.caption("Hướng dẫn cho lần đánh giá tiếp theo, chưa phải kết quả đo mới. Sau sửa dữ liệu, export/import lại và tính lại với cấu hình, đơn vị và phạm vi phù hợp. Chỉ so coverage gain khi cấu hình/phạm vi tương thích; nếu thay đổi, tính lại cả hai snapshot theo cấu hình chung hoặc không so sánh.")
            for metric in rec.remeasure:
                st.text(f"{metric}: {REMEASURE_TEXT.get(metric, 'Cần đầu vào và định nghĩa đo phù hợp trước khi đánh giá; chưa có kết quả mới.')} ")
            if not rec.remeasure:
                st.text("Chỉ số đo lại: N/A — chưa có chỉ số được cung cấp.")
            st.markdown("**Ảnh liên quan**")
            rows = affected_image_rows(rec, images or (), objects or (), result, cvat_mapping)
            if not rows:
                st.info("Không có ảnh liên quan được cung cấp; zero support có thể có danh sách rỗng.")
            roles = {"metadata_correction": "Metadata cần xác minh/bổ sung", "existing_support": "Ảnh hỗ trợ hiện có", "affected_unspecified": "Ảnh liên quan — chưa có phân loại vai trò"}
            for row in rows:
                st.text(f"{roles[row['role']]} | {row['display']} | {row['image_key']} | {row['mapping_status']}")
                if row["cvat_url"]:
                    st.link_button("Mở ảnh trên CVAT", row["cvat_url"])
