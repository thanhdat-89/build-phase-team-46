"""Coverage Dashboard UI view for N2-05B Data Quality & Coverage.

Implements Phase 4.2:
1. KPI Summary:
   - Observed coverage, weighted coverage, weighted attainment, unresolved slices count.
   - Clear provisional / quality gate status banner.
2. Per-Slice Coverage Table:
   - Slice name/ID, actual support and target support, gap, priority.
   - Metadata availability and unresolved metadata status.
   - Unit and denominator clarity (image vs object).
   - Clear provisional indicators when metadata is incomplete.
   - Interactive Plotly visualization comparing Support vs Target.
3. Configuration Editing:
   - Interactive editing of target_count and weight per slice.
   - Strict validation via core.coverage_config.validate_coverage_config.
   - Deterministic config_version increment upon valid modification.
   - Automatic recalculation of metrics and recommendations.
   - Streamlit session state persistence across reruns.
4. Correctness & Guardrails:
   - Explicit disclaimer that overlapping slice gaps are never summed into a collection total.
   - No fabrication of support, evidence, or CVAT links.

Strictly follows:
- FEEDBACK/Recommended-solution_DAT/Coverage_Recommendation_Engine_Coding_Spec_N2-05B.md §5, §9
- FEEDBACK/Recommended-solution_DAT/Co_so_ly_thuyet_Data_Quality_Coverage_N2-05B.md §6, §10.2
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from core.coverage_config import (
    CoverageConfig,
    MetadataPolicy,
    SliceDefinition,
    validate_coverage_config,
)
from core.coverage_metrics import (
    DatasetCoverageResult,
    calculate_dataset_coverage,
    calculate_slice_metrics,
)
from core.recommendations import Recommendation, recommend
from core.schema import ImageRecord, ObjectRecord
from core.slice_engine import SliceEvaluationResult, measure_slices


# ---------------------------------------------------------------------------
# Default Configuration
# ---------------------------------------------------------------------------

def get_default_coverage_config() -> CoverageConfig:
    """Return a baseline coverage configuration adhering strictly to Specification §3 and §10.2."""
    return CoverageConfig(
        definition_version="1.0",
        config_version="1",
        metadata_policy=MetadataPolicy(
            missing_warning_rate=0.05,
            unknown_warning_rate=0.10,
        ),
        slices=[
            SliceDefinition(
                id="person_night_rain",
                name="Người đi bộ ban đêm trời mưa",
                unit="image",
                filters={
                    "contains_class": "person",
                    "timeofday": "night",
                    "weather": "rain",
                },
                target_count=50,
                weight=3.0,
                min_independent_sources=3,
                enabled=True,
                feasibility="confirmed",
                target_reason="Ví dụ cấu hình (§3); Lead phải duyệt",
            ),
            SliceDefinition(
                id="person_night",
                name="Người đi bộ ban đêm",
                unit="image",
                filters={
                    "contains_class": "person",
                    "timeofday": "night",
                },
                target_count=100,
                weight=2.0,
                enabled=True,
                feasibility="confirmed",
                target_reason="Ví dụ cấu hình (§10.2); Lead phải duyệt",
            ),
            SliceDefinition(
                id="small_person_night",
                name="BBox người đi bộ nhỏ ban đêm",
                unit="object",
                filters={
                    "class_name": "person",
                    "timeofday": "night",
                    "area_ratio_max": 0.01,
                },
                target_count=100,
                weight=2.0,
                enabled=True,
                feasibility="unverified",
                target_reason="Ví dụ cấu hình (§3); chưa phải chuẩn",
            ),
        ],
    )


# ---------------------------------------------------------------------------
# Version Management & Configuration Editing Helpers
# ---------------------------------------------------------------------------

def increment_config_version(current_version: str) -> str:
    """Increment config version deterministically (e.g., '1' -> '2', 'v1' -> 'v2')."""
    raw = current_version.strip()
    if raw.isdigit():
        return str(int(raw) + 1)
    if raw.startswith("v") and raw[1:].isdigit():
        return f"v{int(raw[1:]) + 1}"
    if "." in raw:
        parts = raw.split(".")
        if parts[-1].isdigit():
            parts[-1] = str(int(parts[-1]) + 1)
            return ".".join(parts)
    return f"{raw}.1"


def apply_slice_config_edit(
    current_config: CoverageConfig,
    slice_id: str,
    new_target: int,
    new_weight: float,
    enabled: bool = True,
    known_classes: set[str] | list[str] | None = None,
) -> tuple[bool, CoverageConfig | None, list[str]]:
    """Validate and apply modifications to a slice definition within a configuration.

    Guarantees:
    - target_count is positive integer.
    - weight is positive finite float.
    - If target, weight, and enabled status are identical, preserves original config and version without incrementing.
    - Validates entire candidate configuration using validate_coverage_config.
    - On success: increments config_version (if changed) and returns (True, new_config, warnings).
    - On failure: preserves current_config and returns (False, None, errors).
    """
    target_slice = next((s for s in current_config.slices if s.id == slice_id), None)
    if target_slice is None:
        return False, None, [f"Slice ID '{slice_id}' không tồn tại trong cấu hình hiện tại."]

    # Check for no-op edit (no changes)
    is_same_target = int(new_target) == int(target_slice.target_count)
    is_same_weight = math.isclose(float(new_weight), float(target_slice.weight), rel_tol=1e-9, abs_tol=1e-9)
    is_same_enabled = bool(enabled) == bool(target_slice.enabled)

    if is_same_target and is_same_weight and is_same_enabled:
        return True, current_config, ["Không có thay đổi nào đối với cấu hình slice."]

    updated_slices: list[SliceDefinition] = []
    for s in current_config.slices:
        if s.id == slice_id:
            updated_s = SliceDefinition(
                id=s.id,
                name=s.name,
                unit=s.unit,
                filters=dict(s.filters),
                target_count=new_target,
                weight=float(new_weight),
                min_independent_sources=s.min_independent_sources,
                enabled=enabled,
                feasibility=s.feasibility,
                target_reason=s.target_reason,
            )
            updated_slices.append(updated_s)
        else:
            updated_slices.append(s)

    candidate_version = increment_config_version(current_config.config_version)
    candidate_config = CoverageConfig(
        definition_version=current_config.definition_version,
        config_version=candidate_version,
        metadata_policy=current_config.metadata_policy,
        slices=updated_slices,
    )

    val_res = validate_coverage_config(candidate_config, known_classes=known_classes)
    if not val_res.valid:
        return False, None, val_res.errors

    return True, val_res.config, val_res.warnings


# ---------------------------------------------------------------------------
# Cache Fingerprinting
# ---------------------------------------------------------------------------

def compute_coverage_cache_key(
    images: list[ImageRecord],
    objects: list[ObjectRecord],
    config: CoverageConfig,
    dataset_version: str = "",
    sources: dict[str, str] | list[dict[str, Any]] | None = None,
) -> str:
    """Compute a reliable, deterministic hash fingerprint for dataset and configuration state.

    Guarantees:
    - Fingerprints all images and objects without partial sampling omissions.
    - Captures image dimensions, scene metadata (timeofday, weather, conflicts, tags), and source attribution.
    - Captures object bounding boxes, class names, occlusion flags, and attributes.
    - Captures full slice configurations (filters, targets, weights, flags) and metadata policies,
      not relying solely on config_version.
    - Deterministically serializes source mappings and dataset versions.
    - Unambiguous canonical JSON encoding prevents collision from ad-hoc delimiter concatenation.
    """
    hasher = hashlib.sha256()

    # 1. Dataset version and collection counts
    meta_header = [
        dataset_version,
        config.config_version,
        config.definition_version,
        len(images),
        len(objects),
    ]
    hasher.update(json.dumps(meta_header, separators=(",", ":")).encode("utf-8"))

    # 2. Metadata policy
    policy_data = [
        config.metadata_policy.missing_warning_rate,
        config.metadata_policy.unknown_warning_rate,
    ]
    hasher.update(json.dumps(policy_data, separators=(",", ":")).encode("utf-8"))

    # 3. Slice definitions
    slice_data = []
    for s in config.slices:
        slice_data.append(
            [
                s.id,
                s.name,
                s.unit,
                s.filters,
                s.target_count,
                float(s.weight),
                s.min_independent_sources,
                s.enabled,
                s.feasibility,
                s.target_reason,
            ]
        )
    hasher.update(json.dumps(slice_data, sort_keys=True, separators=(",", ":")).encode("utf-8"))

    # 4. Images
    for img in images:
        img_payload = [
            img.dataset_id,
            img.image_id,
            img.width,
            img.height,
            img.timeofday,
            img.weather,
            img.metadata_source,
            bool(getattr(img, "has_scene_conflict", False)),
            getattr(img, "scene_tags", None) or [],
            getattr(img, "source_id", None),
        ]
        hasher.update(json.dumps(img_payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))

    # 5. Objects
    for obj in objects:
        obj_payload = [
            obj.dataset_id,
            obj.object_id,
            obj.image_id,
            obj.class_name,
            obj.x_min,
            obj.y_min,
            obj.x_max,
            obj.y_max,
            bool(obj.occluded),
            obj.attributes or {},
        ]
        hasher.update(json.dumps(obj_payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))

    # 6. Sources
    if sources is not None:
        hasher.update(json.dumps(sources, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    else:
        hasher.update(b"null")

    return hasher.hexdigest()[:16]


# ---------------------------------------------------------------------------
# Recalculation Engine
# ---------------------------------------------------------------------------

def recalculate_coverage(
    images: list[ImageRecord],
    objects: list[ObjectRecord],
    config: CoverageConfig,
    sources: dict[str, str] | list[dict[str, Any]] | None = None,
    dataset_version: str = "",
) -> tuple[dict[str, SliceEvaluationResult], DatasetCoverageResult, list[Recommendation]]:
    """Deterministically recalculate slice evaluations, dataset coverage metrics, and recommendations."""
    slice_results = measure_slices(
        images=images,
        objects=objects,
        config=config,
        sources=sources,
    )

    dataset_coverage = calculate_dataset_coverage(
        slice_results=slice_results,
        config=config,
    )

    recommendations = recommend(
        slice_results=slice_results,
        config=config,
        images=images,
        dataset_version=dataset_version,
    )

    return slice_results, dataset_coverage, recommendations


# ---------------------------------------------------------------------------
# Table Data Preparation
# ---------------------------------------------------------------------------

def prepare_slice_table_data(
    slice_results: dict[str, SliceEvaluationResult],
    config: CoverageConfig,
) -> list[dict[str, Any]]:
    """Format per-slice metrics for clean tabular display in the UI.

    Guarantees:
    - Never sums overlapping gaps.
    - Explicit denominator clarity (support / target_count).
    - Clear distinction between confirmed results and provisional (unresolved metadata) states.
    """
    rows: list[dict[str, Any]] = []

    for s_def in config.slices:
        eval_res = slice_results.get(s_def.id)

        support = eval_res.support if eval_res is not None else 0
        target = s_def.target_count
        gap = eval_res.gap if eval_res is not None else target
        attainment = eval_res.attainment if eval_res is not None else 0.0
        priority = eval_res.priority if eval_res is not None else float(s_def.weight)
        unres_count = eval_res.unresolved_count if eval_res is not None else 0
        is_prov = unres_count > 0

        # Format metadata availability details
        if eval_res is not None and eval_res.metadata_availability:
            avail_parts = [
                f"{k}: {v * 100:.0f}%" for k, v in eval_res.metadata_availability.items()
            ]
            meta_status = ", ".join(avail_parts)
        elif is_prov:
            meta_status = f"Thiếu metadata ({unres_count} bản ghi chưa rõ)"
        else:
            meta_status = "Đầy đủ"

        # Format source support
        if eval_res is not None and eval_res.source_support is not None:
            source_display = str(eval_res.source_support)
        else:
            source_display = "N/A"

        # Status text
        if not s_def.enabled:
            status_text = "Đã tắt (Disabled)"
        elif eval_res is None:
            status_text = "Chưa đánh giá"
        elif eval_res.support >= eval_res.target_count:
            status_text = "Đạt mục tiêu (Met)"
        elif eval_res.support == 0:
            status_text = "Không có mẫu (Zero Support)"
        else:
            status_text = "Dưới mục tiêu (Below Target)"

        rows.append(
            {
                "slice_id": s_def.id,
                "slice_name": s_def.name,
                "unit": s_def.unit,
                "support": support,
                "target_count": target,
                "gap": gap,
                "attainment_pct": round(attainment * 100, 1),
                "weight": s_def.weight,
                "priority": round(priority, 2),
                "unresolved_count": unres_count,
                "provisional_status": "⚠️ Tạm thời (Provisional)" if is_prov else "✅ Đã xác nhận (Confirmed)",
                "metadata_availability": meta_status,
                "source_support": source_display,
                "status": status_text,
                "enabled": s_def.enabled,
                "feasibility": s_def.feasibility,
            }
        )

    return rows


# ---------------------------------------------------------------------------
# Streamlit Rendering
# ---------------------------------------------------------------------------

def render_coverage(
    images: list[ImageRecord],
    valid_objects: list[ObjectRecord] | None = None,
    objects: list[ObjectRecord] | None = None,
    config: CoverageConfig | None = None,
    sources: dict[str, str] | list[dict[str, Any]] | None = None,
    dataset_version: str = "",
) -> None:
    """Render the full Coverage Dashboard UI tab in Streamlit."""
    target_objects = valid_objects if valid_objects is not None else (objects or [])

    # 0. Render and clear flash messages from previous rerun
    flash_messages: list[tuple[str, str]] = st.session_state.pop("coverage_flash_messages", [])
    if flash_messages:
        for msg_type, msg_text in flash_messages:
            if msg_type == "success":
                st.success(msg_text)
            elif msg_type == "warning":
                st.warning(msg_text)
            elif msg_type == "info":
                st.info(msg_text)
            elif msg_type == "error":
                st.error(msg_text)

    # 1. Initialize session state
    if "coverage_config" not in st.session_state:
        st.session_state["coverage_config"] = config or get_default_coverage_config()

    active_config: CoverageConfig = st.session_state["coverage_config"]

    # 2. Compute reliable dataset/config cache key
    current_cache_key = compute_coverage_cache_key(
        images=images,
        objects=target_objects,
        config=active_config,
        dataset_version=dataset_version,
        sources=sources,
    )
    cached_key = st.session_state.get("coverage_cache_key")

    # Recalculate if cache key changed or results not yet stored
    if (
        cached_key != current_cache_key
        or "coverage_slice_results" not in st.session_state
        or "coverage_dataset_result" not in st.session_state
    ):
        s_res, d_cov, recs = recalculate_coverage(
            images=images,
            objects=target_objects,
            config=active_config,
            sources=sources,
            dataset_version=dataset_version,
        )
        st.session_state["coverage_slice_results"] = s_res
        st.session_state["coverage_dataset_result"] = d_cov
        st.session_state["coverage_recommendations"] = recs
        st.session_state["coverage_cache_key"] = current_cache_key

    slice_results: dict[str, SliceEvaluationResult] = st.session_state["coverage_slice_results"]
    dataset_cov: DatasetCoverageResult = st.session_state["coverage_dataset_result"]

    # -----------------------------------------------------------------------
    # Section A: Header & Version Metadata
    # -----------------------------------------------------------------------
    st.header("🎯 Đo lường Độ bao phủ Dữ liệu (Coverage Measurement)")
    st.caption(
        "Theo dõi mức độ đáp ứng các tình huống nghiệp vụ quan trọng (slices) "
        "dựa trên nhãn đối tượng và thuộc tính bối cảnh từ CVAT export."
    )

    ver_c1, ver_c2 = st.columns([1, 1])
    ver_c1.info(f"📌 **Phiên bản cấu hình (Config Version):** `{active_config.config_version}`")
    ver_c2.info(f"🏷️ **Phiên bản dữ liệu (Dataset Version):** `{dataset_version or 'Hiện tại (Active Import)'}`")

    st.divider()

    # -----------------------------------------------------------------------
    # Section B: KPI Summary
    # -----------------------------------------------------------------------
    st.subheader("1. Tổng quan Chỉ số Độ bao phủ (KPI Summary)")

    kpi1, kpi2, kpi3, kpi4 = st.columns(4)

    obs_cov_str = (
        f"{dataset_cov.coverage * 100:.1f}%"
        if dataset_cov.coverage is not None
        else "N/A"
    )
    kpi1.metric(
        label="Độ bao phủ quan sát",
        value=obs_cov_str,
        help="Tỷ lệ slice đạt mục tiêu: sum(support_s >= target_s) / |S|",
    )

    weight_cov_str = (
        f"{dataset_cov.weighted_coverage * 100:.1f}%"
        if dataset_cov.weighted_coverage is not None
        else "N/A"
    )
    kpi2.metric(
        label="Độ bao phủ có trọng số",
        value=weight_cov_str,
        help="Ưu tiên slice quan trọng: sum(w_s * [support_s >= target_s]) / sum(w_s)",
    )

    weight_att_str = (
        f"{dataset_cov.weighted_attainment * 100:.1f}%"
        if dataset_cov.weighted_attainment is not None
        else "N/A"
    )
    kpi3.metric(
        label="Mức tiến gần mục tiêu",
        value=weight_att_str,
        help="Attainment trung bình có trọng số: sum(w_s * min(support_s / target_s, 1)) / sum(w_s)",
    )

    kpi4.metric(
        label="Slice chưa rõ metadata",
        value=dataset_cov.unresolved_slices_count,
        delta=f"-{dataset_cov.unresolved_slices_count} slice provisional" if dataset_cov.unresolved_slices_count > 0 else "0",
        delta_color="inverse",
        help="Số slice còn ảnh/đối tượng thiếu hoặc xung đột metadata cần xác minh",
    )

    # Quality Gate Banner
    if dataset_cov.eligible_slices_count == 0:
        st.info(
            "ℹ️ **Không có slice hợp lệ để đánh giá (|S| = 0):** "
            "Cấu hình chưa có slice nào được kích hoạt hoặc khả thi. "
            "Vui lòng kích hoạt ít nhất một slice để tiến hành đánh giá độ bao phủ."
        )
    elif dataset_cov.targets_met:
        st.success(
            "✅ **Đạt toàn bộ mục tiêu (Targets Met):** Tất cả các slice hợp lệ đã đạt chỉ tiêu số lượng "
            "và không còn rào cản metadata. Đủ điều kiện chuyển sang bước review chất lượng kiểm toán."
        )
    elif dataset_cov.is_provisional:
        st.warning(
            f"⚠️ **Đánh dấu tạm thời (Provisional):** Tất cả mục tiêu quan sát có thể đã đạt, "
            f"nhưng vẫn còn **{dataset_cov.unresolved_slices_count} slice** tồn tại bản ghi chưa xác định metadata. "
            "Quyết định nghiệm thu bàn giao phải được bảo lưu cho đến khi hoàn thành xác minh metadata."
        )
    else:
        unmet_count = dataset_cov.eligible_slices_count - dataset_cov.met_slices_count
        st.info(
            f"ℹ️ **Chưa đạt kế hoạch (Below Target):** Còn **{unmet_count}/{dataset_cov.eligible_slices_count} slice** "
            "chưa đạt số lượng mẫu mục tiêu. Cần xem bảng chi tiết và danh sách khuyến nghị bên dưới."
        )

    if dataset_cov.reasons:
        for r in dataset_cov.reasons:
            st.caption(f"• *{r}*")

    st.divider()

    # -----------------------------------------------------------------------
    # Section C: Per-Slice Coverage Table & Visualization
    # -----------------------------------------------------------------------
    st.subheader("2. Chi tiết Độ bao phủ theo Slice (Per-Slice Coverage)")

    # Crucial specification guardrail against gap summation
    st.warning(
        "⚠️ **Lưu ý nguyên tắc thống kê (Coding Spec §9 & Criterion 9):** "
        "Các slice có thể chồng lấn (overlap) — ví dụ một ảnh có thể vừa thuộc slice người đi bộ ban đêm "
        "vừa thuộc slice người đi bộ trời mưa. **Tuyệt đối không cộng dồn khoảng thiếu (gap) giữa các slice** "
        "thành tổng số ảnh cần thu thập."
    )

    table_data = prepare_slice_table_data(slice_results=slice_results, config=active_config)
    df_slices = pd.DataFrame(table_data)

    if not df_slices.empty:
        # Chart: Actual Support vs Target Count with conditional provisional styling
        support_colors = [
            "#adb5bd"
            if not row["enabled"]
            else ("#e67700" if row["unresolved_count"] > 0 else "#2b8a3e")
            for _, row in df_slices.iterrows()
        ]
        status_labels = [
            "Đã tắt (Disabled)"
            if not row["enabled"]
            else (
                f"⚠️ Tạm thời (Provisional: {row['unresolved_count']} bản ghi chưa rõ)"
                if row["unresolved_count"] > 0
                else "✅ Đã xác nhận (Confirmed)"
            )
            for _, row in df_slices.iterrows()
        ]

        fig = go.Figure()
        fig.add_trace(
            go.Bar(
                name="Mẫu thực tế (Support)",
                x=df_slices["slice_name"],
                y=df_slices["support"],
                marker_color=support_colors,
                text=df_slices["support"],
                textposition="auto",
                customdata=status_labels,
                hovertemplate="<b>%{x}</b><br>Support: %{y}<br>Trạng thái: %{customdata}<extra></extra>",
            )
        )
        fig.add_trace(
            go.Bar(
                name="Mục tiêu kế hoạch (Target)",
                x=df_slices["slice_name"],
                y=df_slices["target_count"],
                marker_color="#868e96",
                text=df_slices["target_count"],
                textposition="auto",
                hovertemplate="<b>%{x}</b><br>Target: %{y}<extra></extra>",
            )
        )
        fig.update_layout(
            barmode="group",
            title="So sánh Mẫu thực tế (Support) và Mục tiêu (Target) từng Slice",
            xaxis_title="Tình huống (Slice)",
            yaxis_title="Số lượng đơn vị",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            margin=dict(l=20, r=20, t=60, b=40),
        )
        st.plotly_chart(fig, use_container_width=True)
        st.caption(
            "🎨 **Chú giải màu sắc:** "
            "🟢 Xanh lá (`#2b8a3e`): Mẫu thực tế đã xác nhận | "
            "🟠 Cam hổ phách (`#e67700`): Mẫu tạm thời do còn metadata chưa rõ | "
            "⚪ Xám (`#868e96`): Mục tiêu kế hoạch."
        )

        # Tabular View
        st.dataframe(
            df_slices,
            column_config={
                "slice_id": "Mã Slice",
                "slice_name": "Tên tình huống",
                "unit": st.column_config.TextColumn("Đơn vị", help="image: đếm số ảnh duy nhất; object: đếm số bounding box"),
                "support": st.column_config.NumberColumn("Thực tế (Support)", format="%d"),
                "target_count": st.column_config.NumberColumn("Mục tiêu (Target)", format="%d"),
                "gap": st.column_config.NumberColumn("Còn thiếu (Gap)", format="%d"),
                "attainment_pct": st.column_config.NumberColumn("Tiến độ (%)", format="%.1f%%"),
                "weight": st.column_config.NumberColumn("Trọng số (w)", format="%.1f"),
                "priority": st.column_config.NumberColumn("Ưu tiên (P)", format="%.2f", help="Priority = weight * (1 - attainment)"),
                "provisional_status": "Trạng thái đánh giá",
                "unresolved_count": st.column_config.NumberColumn("Bản ghi chưa rõ", format="%d"),
                "metadata_availability": "Độ sẵn sàng metadata",
                "source_support": "Nguồn độc lập",
                "status": "Kết quả",
                "enabled": "Kích hoạt",
                "feasibility": "Tính khả thi",
            },
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("Không có slice nào trong cấu hình.")

    st.divider()

    # -----------------------------------------------------------------------
    # Section D: Configuration Editing
    # -----------------------------------------------------------------------
    st.subheader("3. Tinh chỉnh Cấu hình & Mục tiêu (Configuration Editing)")
    st.caption(
        "Data Lead có thể cập nhật số lượng mẫu yêu cầu (target_count) và trọng số ưu tiên (weight) "
        "cho từng slice. Khi lưu thay đổi hợp lệ, hệ thống sẽ tự động tăng phiên bản `config_version` "
        "và tính toán lại toàn bộ chỉ số độ bao phủ."
    )

    with st.expander("🛠️ Mở bảng chỉnh sửa tham số Slice", expanded=False):
        slice_options = {s.id: f"{s.name} ({s.id}) [Đơn vị: {s.unit}]" for s in active_config.slices}

        selected_slice_id = st.selectbox(
            "Chọn tình huống (Slice) cần chỉnh sửa:",
            options=list(slice_options.keys()),
            format_func=lambda s_id: slice_options.get(s_id, s_id),
            key="cov_edit_slice_select",
        )

        selected_slice_def = next(
            (s for s in active_config.slices if s.id == selected_slice_id), None
        )

        if selected_slice_def is not None:
            c_target, c_weight, c_enabled = st.columns(3)

            with c_target:
                new_target_val = st.number_input(
                    "Mục tiêu số lượng (target_count):",
                    min_value=1,
                    max_value=100000,
                    value=int(selected_slice_def.target_count),
                    step=1,
                    key=f"target_input_{selected_slice_id}",
                    help="Số nguyên dương > 0 biểu thị số mẫu yêu cầu của slice.",
                )

            with c_weight:
                new_weight_val = st.number_input(
                    "Trọng số ưu tiên (weight):",
                    min_value=0.1,
                    max_value=100.0,
                    value=float(selected_slice_def.weight),
                    step=0.5,
                    key=f"weight_input_{selected_slice_id}",
                    help="Số thực dương hữu hạn biểu thị tầm quan trọng nghiệp vụ.",
                )

            with c_enabled:
                new_enabled_val = st.checkbox(
                    "Kích hoạt đánh giá slice này",
                    value=selected_slice_def.enabled,
                    key=f"enabled_input_{selected_slice_id}",
                )

            st.caption(f"Lý do đặt mục tiêu hiện tại: *{selected_slice_def.target_reason or 'Chưa ghi chú'}*")

            if st.button("💾 Áp dụng thay đổi & Tính lại chỉ số", type="primary", key="btn_apply_config"):
                known_classes = {obj.class_name for obj in target_objects} if target_objects else None
                success, updated_config, msgs = apply_slice_config_edit(
                    current_config=active_config,
                    slice_id=selected_slice_id,
                    new_target=new_target_val,
                    new_weight=new_weight_val,
                    enabled=new_enabled_val,
                    known_classes=known_classes,
                )

                if success and updated_config is not None:
                    # Check if it was a no-op edit
                    if updated_config.config_version == active_config.config_version:
                        st.info("ℹ️ Không có thay đổi nào đối với cấu hình. Giữ nguyên phiên bản hiện tại.")
                    else:
                        # Update session state and recalculate
                        st.session_state["coverage_config"] = updated_config
                        s_res, d_cov, recs = recalculate_coverage(
                            images=images,
                            objects=target_objects,
                            config=updated_config,
                            sources=sources,
                            dataset_version=dataset_version,
                        )
                        st.session_state["coverage_slice_results"] = s_res
                        st.session_state["coverage_dataset_result"] = d_cov
                        st.session_state["coverage_recommendations"] = recs
                        st.session_state["coverage_cache_key"] = compute_coverage_cache_key(
                            images=images,
                            objects=target_objects,
                            config=updated_config,
                            dataset_version=dataset_version,
                            sources=sources,
                        )

                        # Store flash messages to display after rerun
                        flash_msgs = [
                            (
                                "success",
                                f"✅ Đã cập nhật thành công! Phiên bản cấu hình mới: `{updated_config.config_version}`. "
                                "Toàn bộ chỉ số đã được tự động tính toán lại.",
                            )
                        ]
                        if msgs:
                            for w in msgs:
                                if "Không có thay đổi" not in w:
                                    flash_msgs.append(("warning", f"Cảnh báo: {w}"))
                        st.session_state["coverage_flash_messages"] = flash_msgs
                        st.rerun()
                else:
                    for err in msgs:
                        st.error(f"❌ Lỗi cấu hình: {err}")
