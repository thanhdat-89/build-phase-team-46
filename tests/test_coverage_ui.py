"""Unit tests for Phase 4.2 Coverage Dashboard UI (ui/coverage.py).

Tests:
1. Default configuration generation and validity.
2. Config version deterministic incrementation ('1' -> '2', 'v1' -> 'v2', etc.).
3. Config editing: target_count and weight updates, validation pass/fail, error reporting.
4. Recalculation logic: deterministic recalculation of slice metrics and dataset coverage.
5. Table data preparation:
   - Proper fields: slice_id, slice_name, unit, support, target_count, gap, priority, etc.
   - Denominator clarity and unit accuracy.
   - Provisional status identification when unresolved_count > 0.
   - Overlapping slice gaps are never summed into a total missing count.
6. KPI calculation and summary presentation.
7. Streamlit rendering smoke test with simulated session state.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.coverage_config import (
    CoverageConfig,
    MetadataPolicy,
    SliceDefinition,
    validate_coverage_config,
)
from core.coverage_metrics import calculate_dataset_coverage
from core.schema import ImageRecord, ObjectRecord
from core.slice_engine import SliceEvaluationResult
from ui.coverage import (
    apply_slice_config_edit,
    compute_coverage_cache_key,
    get_default_coverage_config,
    increment_config_version,
    prepare_slice_table_data,
    recalculate_coverage,
    render_coverage,
)


# ---------------------------------------------------------------------------
# Test Fixture Helpers
# ---------------------------------------------------------------------------

def _img(
    img_id: str = "img1",
    dataset_id: str = "ds1",
    timeofday: str | None = "day",
    weather: str | None = "clear",
) -> ImageRecord:
    return ImageRecord(
        dataset_id=dataset_id,
        image_id=img_id,
        image_path=f"/path/{img_id}.jpg",
        width=1920,
        height=1080,
        timeofday=timeofday,
        weather=weather,
    )


def _obj(
    obj_id: str = "obj1",
    img_id: str = "img1",
    class_name: str = "person",
    dataset_id: str = "ds1",
    x_min: float = 10.0,
    y_min: float = 10.0,
    x_max: float = 50.0,
    y_max: float = 50.0,
) -> ObjectRecord:
    return ObjectRecord(
        object_id=obj_id,
        image_id=img_id,
        class_name=class_name,
        x_min=x_min,
        y_min=y_min,
        x_max=x_max,
        y_max=y_max,
        dataset_id=dataset_id,
    )


# ===========================================================================
# 1. Default Configuration & Version Increment Tests
# ===========================================================================

class TestDefaultConfigAndVersion:
    """Verifies baseline configuration validity and version increment logic."""

    def test_default_coverage_config_is_valid(self):
        cfg = get_default_coverage_config()
        assert isinstance(cfg, CoverageConfig)
        assert cfg.config_version == "1"
        assert len(cfg.slices) >= 3

        # Validate with existing configuration validation logic
        val_res = validate_coverage_config(cfg)
        assert val_res.valid is True
        assert len(val_res.errors) == 0

    def test_increment_config_version_deterministic(self):
        assert increment_config_version("1") == "2"
        assert increment_config_version("2") == "3"
        assert increment_config_version("99") == "100"
        assert increment_config_version("v1") == "v2"
        assert increment_config_version("v5") == "v6"
        assert increment_config_version("1.0") == "1.1"
        assert increment_config_version("draft") == "draft.1"


# ===========================================================================
# 2. Configuration Editing Tests
# ===========================================================================

class TestConfigurationEditing:
    """Tests UI editing of target_count and weight with validation and version increments."""

    def test_valid_edit_updates_target_weight_and_increments_version(self):
        cfg = get_default_coverage_config()
        assert cfg.config_version == "1"

        success, new_cfg, msgs = apply_slice_config_edit(
            current_config=cfg,
            slice_id="person_night_rain",
            new_target=75,
            new_weight=4.5,
            enabled=True,
        )

        assert success is True
        assert new_cfg is not None
        assert new_cfg.config_version == "2"

        # Check that person_night_rain was updated
        target_slice = next(s for s in new_cfg.slices if s.id == "person_night_rain")
        assert target_slice.target_count == 75
        assert target_slice.weight == 4.5
        assert target_slice.enabled is True

        # Check that other slices were preserved
        other_slice = next(s for s in new_cfg.slices if s.id == "person_night")
        assert other_slice.target_count == 100
        assert other_slice.weight == 2.0

    def test_invalid_target_count_fails_validation(self):
        cfg = get_default_coverage_config()

        # target_count must be > 0
        success, new_cfg, errors = apply_slice_config_edit(
            current_config=cfg,
            slice_id="person_night_rain",
            new_target=0,  # Invalid!
            new_weight=3.0,
        )

        assert success is False
        assert new_cfg is None
        assert any("target_count" in err for err in errors)

    def test_invalid_weight_fails_validation(self):
        cfg = get_default_coverage_config()

        # weight must be positive finite number
        success, new_cfg, errors = apply_slice_config_edit(
            current_config=cfg,
            slice_id="person_night_rain",
            new_target=50,
            new_weight=-1.0,  # Invalid!
        )

        assert success is False
        assert new_cfg is None
        assert any("weight" in err for err in errors)

    def test_nonexistent_slice_id_returns_error(self):
        cfg = get_default_coverage_config()
        success, new_cfg, errors = apply_slice_config_edit(
            current_config=cfg,
            slice_id="non_existent_slice_id",
            new_target=50,
            new_weight=3.0,
        )
        assert success is False
        assert new_cfg is None
        assert "không tồn tại" in errors[0]

    def test_no_op_edit_preserves_version(self):
        cfg = get_default_coverage_config()
        original_version = cfg.config_version
        target_slice = cfg.slices[0]

        # Call apply_slice_config_edit with exact same parameters
        success, new_cfg, msgs = apply_slice_config_edit(
            current_config=cfg,
            slice_id=target_slice.id,
            new_target=target_slice.target_count,
            new_weight=target_slice.weight,
            enabled=target_slice.enabled,
        )

        assert success is True
        assert new_cfg is not None
        assert new_cfg.config_version == original_version
        assert any("Không có thay đổi" in m for m in msgs)


# ===========================================================================
# 3. Recalculation Tests
# ===========================================================================

class TestRecalculationLogic:
    """Tests deterministic recalculation of slice metrics and dataset coverage."""

    def test_recalculate_coverage_pipeline(self):
        images = [
            _img("i1", timeofday="night", weather="rain"),
            _img("i2", timeofday="night", weather="clear"),
            _img("i3", timeofday="day", weather="rain"),
        ]
        objects = [
            _obj("o1", "i1", "person"),
            _obj("o2", "i2", "person"),
            _obj("o3", "i3", "person"),
        ]

        cfg = CoverageConfig(
            config_version="1",
            slices=[
                SliceDefinition(
                    id="person_night_rain",
                    name="Person Night Rain",
                    unit="image",
                    filters={"contains_class": "person", "timeofday": "night", "weather": "rain"},
                    target_count=2,
                    weight=3.0,
                )
            ],
        )

        s_res, d_cov, recs = recalculate_coverage(images, objects, cfg)

        # 1 image matches person_night_rain (i1)
        res = s_res["person_night_rain"]
        assert res.support == 1
        assert res.target_count == 2
        assert res.gap == 1
        assert res.attainment == 0.5
        assert res.priority == 1.5  # 3.0 * (1 - 0.5)

        assert d_cov.total_slices == 1
        assert d_cov.eligible_slices_count == 1
        assert d_cov.met_slices_count == 0
        assert d_cov.coverage == 0.0

        # Now edit target_count to 1 (which makes it met)
        success, new_cfg, _ = apply_slice_config_edit(cfg, "person_night_rain", new_target=1, new_weight=3.0)
        assert success is True

        s_res2, d_cov2, recs2 = recalculate_coverage(images, objects, new_cfg)
        res2 = s_res2["person_night_rain"]
        assert res2.support == 1
        assert res2.target_count == 1
        assert res2.gap == 0
        assert res2.attainment == 1.0
        assert res2.priority == 0.0
        assert d_cov2.met_slices_count == 1
        assert d_cov2.coverage == 1.0
        assert d_cov2.targets_met is True


# ===========================================================================
# 4. Table Data Preparation Tests
# ===========================================================================

class TestTableDataPreparation:
    """Verifies that the slice table formatting satisfies all specification requirements."""

    def test_prepare_slice_table_data_fields(self):
        s1 = SliceDefinition(
            id="s_img",
            name="Image Slice",
            unit="image",
            filters={"contains_class": "person"},
            target_count=50,
            weight=2.0,
        )
        s2 = SliceDefinition(
            id="s_obj",
            name="Object Slice",
            unit="object",
            filters={"class_name": "person"},
            target_count=100,
            weight=1.0,
        )
        cfg = CoverageConfig(slices=[s1, s2])

        eval_1 = SliceEvaluationResult(
            slice_id="s_img",
            slice_name="Image Slice",
            unit="image",
            support=20,
            target_count=50,
            weight=2.0,
            gap=30,
            attainment=0.4,
            priority=1.2,
            unresolved_count=0,
            status="below_target",
        )
        eval_2 = SliceEvaluationResult(
            slice_id="s_obj",
            slice_name="Object Slice",
            unit="object",
            support=100,
            target_count=100,
            weight=1.0,
            gap=0,
            attainment=1.0,
            priority=0.0,
            unresolved_count=5,  # Unresolved metadata!
            metadata_availability={"timeofday": 0.8},
            status="met",
        )

        rows = prepare_slice_table_data({"s_img": eval_1, "s_obj": eval_2}, cfg)
        assert len(rows) == 2

        row1 = rows[0]
        assert row1["slice_id"] == "s_img"
        assert row1["unit"] == "image"
        assert row1["support"] == 20
        assert row1["target_count"] == 50
        assert row1["gap"] == 30
        assert row1["attainment_pct"] == 40.0
        assert row1["priority"] == 1.2
        assert "Confirmed" in row1["provisional_status"]

        row2 = rows[1]
        assert row2["slice_id"] == "s_obj"
        assert row2["unit"] == "object"
        assert row2["support"] == 100
        assert row2["target_count"] == 100
        assert row2["gap"] == 0
        assert row2["unresolved_count"] == 5
        assert "Provisional" in row2["provisional_status"]  # Unresolved triggers provisional!
        assert "timeofday: 80%" in row2["metadata_availability"]

    def test_overlapping_slice_gaps_never_summed_in_table(self):
        """Criterion 9: Overlapping slice gaps are never presented as a combined missing count."""
        s1 = SliceDefinition(id="s1", name="S1", unit="image", filters={}, target_count=50)
        s2 = SliceDefinition(id="s2", name="S2", unit="image", filters={}, target_count=30)
        cfg = CoverageConfig(slices=[s1, s2])

        eval_1 = SliceEvaluationResult(
            slice_id="s1", slice_name="S1", unit="image", support=10, target_count=50, weight=1.0, gap=40, attainment=0.2, priority=0.8
        )
        eval_2 = SliceEvaluationResult(
            slice_id="s2", slice_name="S2", unit="image", support=10, target_count=30, weight=1.0, gap=20, attainment=0.33, priority=0.67
        )

        rows = prepare_slice_table_data({"s1": eval_1, "s2": eval_2}, cfg)
        assert len(rows) == 2
        # Individual rows have their own gap
        assert rows[0]["gap"] == 40
        assert rows[1]["gap"] == 20
        # No sum/aggregate row is produced in prepare_slice_table_data
        for r in rows:
            assert r["gap"] in (40, 20)

    def test_table_data_source_support_available_vs_na(self):
        """Source support shows actual count when present, 'N/A' when absent; never fabricates."""
        s1 = SliceDefinition(id="s1", name="S1", unit="image", filters={}, target_count=10)
        s2 = SliceDefinition(id="s2", name="S2", unit="image", filters={}, target_count=10)
        cfg = CoverageConfig(slices=[s1, s2])

        eval_1 = SliceEvaluationResult(
            slice_id="s1", slice_name="S1", unit="image", support=5, target_count=10, weight=1.0,
            gap=5, attainment=0.5, priority=0.5, source_support=3, source_support_status="available"
        )
        eval_2 = SliceEvaluationResult(
            slice_id="s2", slice_name="S2", unit="image", support=5, target_count=10, weight=1.0,
            gap=5, attainment=0.5, priority=0.5, source_support=None, source_support_status="not_available"
        )

        rows = prepare_slice_table_data({"s1": eval_1, "s2": eval_2}, cfg)
        assert rows[0]["source_support"] == "3"
        assert rows[1]["source_support"] == "N/A"

    def test_table_data_zero_support_status_and_disabled(self):
        """Slice with 0 support has 'Không có mẫu (Zero Support)'; disabled slice shows 'Đã tắt'."""
        s1 = SliceDefinition(id="s_zero", name="Zero", unit="image", filters={}, target_count=10, enabled=True)
        s2 = SliceDefinition(id="s_off", name="Off", unit="image", filters={}, target_count=10, enabled=False)
        cfg = CoverageConfig(slices=[s1, s2])

        eval_zero = SliceEvaluationResult(
            slice_id="s_zero", slice_name="Zero", unit="image", support=0, target_count=10, weight=1.0,
            gap=10, attainment=0.0, priority=1.0, status="zero_support"
        )

        rows = prepare_slice_table_data({"s_zero": eval_zero}, cfg)
        assert rows[0]["status"] == "Không có mẫu (Zero Support)"
        assert rows[1]["status"] == "Đã tắt (Disabled)"


# ===========================================================================
# 5. KPI Summary Presentation Tests
# ===========================================================================

class TestKPISummaryPresentation:
    """Verifies that KPI summary handling adheres to provisional and targets_met rules."""

    def test_provisional_kpi_summary_when_unresolved_metadata_present(self):
        """Criterion 16: targets met but unresolved metadata blockers present withheld sign-off."""
        s = SliceDefinition(id="s1", name="S1", unit="image", filters={}, target_count=5)
        cfg = CoverageConfig(slices=[s])

        # support meets target (5 >= 5), but unresolved_count > 0
        eval_res = SliceEvaluationResult(
            slice_id="s1", slice_name="S1", unit="image", support=5, target_count=5, weight=1.0,
            gap=0, attainment=1.0, priority=0.0, unresolved_count=2, status="met"
        )

        dataset_cov = calculate_dataset_coverage([eval_res], config=cfg)
        assert dataset_cov.met_slices_count == 1
        assert dataset_cov.is_provisional is True
        assert dataset_cov.targets_met is False  # Withheld!
        assert dataset_cov.unresolved_slices_count == 1
        assert any("unresolved metadata blockers remain" in r for r in dataset_cov.reasons)


# ===========================================================================
# 5. Streamlit Render Smoke Test
# ===========================================================================

class TestRenderCoverageSmoke:
    """Verifies that render_coverage executes cleanly with Streamlit components mocked."""

    def test_render_coverage_smoke(self):
        images = [_img("i1", timeofday="night", weather="rain")]
        objects = [_obj("o1", "i1", "person")]
        cfg = get_default_coverage_config()

        mock_session_state = {}

        created_cols = []
        def fake_columns(spec, **kwargs):
            count = len(spec) if isinstance(spec, (list, tuple)) else int(spec)
            cols = [MagicMock() for _ in range(count)]
            created_cols.extend(cols)
            return cols

        with patch("streamlit.session_state", mock_session_state), \
             patch("streamlit.header") as mock_header, \
             patch("streamlit.subheader") as mock_subheader, \
             patch("streamlit.columns", side_effect=fake_columns) as mock_columns, \
             patch("streamlit.dataframe") as mock_dataframe, \
             patch("streamlit.plotly_chart") as mock_plotly:

            render_coverage(
                images=images,
                valid_objects=objects,
                config=cfg,
                dataset_version="test_dataset_v1",
            )

            # Assert session state was initialized
            assert "coverage_config" in mock_session_state
            assert "coverage_slice_results" in mock_session_state
            assert "coverage_dataset_result" in mock_session_state
            assert "coverage_recommendations" in mock_session_state

            # Assert key components were called
            mock_header.assert_called_once()
            metric_calls = sum(c.metric.call_count for c in created_cols)
            assert metric_calls >= 4
            assert mock_dataframe.call_count >= 1
            assert mock_plotly.call_count >= 1


# ===========================================================================
# 6. Cache Fingerprint & Dataset Invalidation Tests
# ===========================================================================

class TestCacheFingerprintAndDatasetInvalidation:
    """Verifies that dataset changes reliably invalidate cached coverage metrics."""

    def test_cache_key_different_for_different_datasets_with_same_length(self):
        cfg = get_default_coverage_config()
        img_a = [_img("img_a", dataset_id="ds1")]
        img_b = [_img("img_b", dataset_id="ds1")]
        obj_a = [_obj("obj_a", img_id="img_a", dataset_id="ds1")]
        obj_b = [_obj("obj_b", img_id="img_b", dataset_id="ds1")]

        key_a = compute_coverage_cache_key(img_a, obj_a, cfg, dataset_version="v1")
        key_b = compute_coverage_cache_key(img_b, obj_b, cfg, dataset_version="v1")
        assert key_a != key_b

    def test_cache_key_different_for_different_dataset_versions(self):
        cfg = get_default_coverage_config()
        imgs = [_img("i1")]
        objs = [_obj("o1", "i1")]

        key1 = compute_coverage_cache_key(imgs, objs, cfg, dataset_version="v1")
        key2 = compute_coverage_cache_key(imgs, objs, cfg, dataset_version="v2")
        assert key1 != key2

    def test_cache_key_detects_middle_record_image_change(self):
        """Ensure changes to middle images (>50 from head and tail) invalidate the cache key."""
        cfg = get_default_coverage_config()
        imgs_a = [_img(f"img_{i}", dataset_id="ds1") for i in range(120)]
        imgs_b = [_img(f"img_{i}", dataset_id="ds1") for i in range(120)]
        objs = [_obj(f"obj_{i}", img_id=f"img_{i}", dataset_id="ds1") for i in range(120)]

        # Mutate an image in the middle (index 60)
        imgs_b[60] = _img("img_60_modified", dataset_id="ds1")

        key_a = compute_coverage_cache_key(imgs_a, objs, cfg)
        key_b = compute_coverage_cache_key(imgs_b, objs, cfg)
        assert key_a != key_b

    def test_cache_key_detects_middle_record_object_change(self):
        """Ensure changes to middle objects (>50 from head and tail) invalidate the cache key."""
        cfg = get_default_coverage_config()
        imgs = [_img(f"img_{i}", dataset_id="ds1") for i in range(120)]
        objs_a = [_obj(f"obj_{i}", img_id=f"img_{i}", dataset_id="ds1") for i in range(120)]
        objs_b = [_obj(f"obj_{i}", img_id=f"img_{i}", dataset_id="ds1") for i in range(120)]

        # Mutate an object in the middle (index 60)
        objs_b[60] = _obj("obj_60_modified", img_id="img_60", dataset_id="ds1")

        key_a = compute_coverage_cache_key(imgs, objs_a, cfg)
        key_b = compute_coverage_cache_key(imgs, objs_b, cfg)
        assert key_a != key_b

    def test_cache_key_detects_image_metadata_changes(self):
        """Ensure changes to scene metadata (timeofday, weather, conflicts, tags) invalidate the cache key."""
        cfg = get_default_coverage_config()
        objs = [_obj("o1", "i1")]

        base_img = _img("i1", timeofday="day", weather="clear")
        key_base = compute_coverage_cache_key([base_img], objs, cfg)

        # 1. timeofday change
        img_tod = _img("i1", timeofday="night", weather="clear")
        assert compute_coverage_cache_key([img_tod], objs, cfg) != key_base

        # 2. weather change
        img_wtr = _img("i1", timeofday="day", weather="rain")
        assert compute_coverage_cache_key([img_wtr], objs, cfg) != key_base

        # 3. has_scene_conflict change
        img_conf = ImageRecord("ds1", "i1", "/path/i1.jpg", 1920, 1080, "day", "clear", has_scene_conflict=True)
        assert compute_coverage_cache_key([img_conf], objs, cfg) != key_base

        # 4. scene_tags change
        img_tags = ImageRecord("ds1", "i1", "/path/i1.jpg", 1920, 1080, "day", "clear", scene_tags=[{"weather": "rain"}])
        assert compute_coverage_cache_key([img_tags], objs, cfg) != key_base

        # 5. dimensions change
        img_dim = ImageRecord("ds1", "i1", "/path/i1.jpg", 3840, 2160, "day", "clear")
        assert compute_coverage_cache_key([img_dim], objs, cfg) != key_base

    def test_cache_key_detects_object_geometry_and_class_changes(self):
        """Ensure changes to object bounding box coordinates, class, occlusion, and attributes invalidate key."""
        cfg = get_default_coverage_config()
        imgs = [_img("i1")]

        base_obj = _obj("o1", "i1", class_name="person", x_min=10.0, y_min=10.0, x_max=50.0, y_max=50.0)
        key_base = compute_coverage_cache_key(imgs, [base_obj], cfg)

        # 1. class_name change
        obj_cls = _obj("o1", "i1", class_name="car", x_min=10.0, y_min=10.0, x_max=50.0, y_max=50.0)
        assert compute_coverage_cache_key(imgs, [obj_cls], cfg) != key_base

        # 2. coordinate / geometry change
        obj_geo = _obj("o1", "i1", class_name="person", x_min=10.0, y_min=10.0, x_max=80.0, y_max=50.0)
        assert compute_coverage_cache_key(imgs, [obj_geo], cfg) != key_base

        # 3. occluded change
        obj_occ = ObjectRecord("o1", "i1", "person", 10.0, 10.0, 50.0, 50.0, occluded=True, dataset_id="ds1")
        assert compute_coverage_cache_key(imgs, [obj_occ], cfg) != key_base

        # 4. attributes change
        obj_attr = ObjectRecord("o1", "i1", "person", 10.0, 10.0, 50.0, 50.0, attributes={"pose": "sitting"}, dataset_id="ds1")
        assert compute_coverage_cache_key(imgs, [obj_attr], cfg) != key_base

    def test_cache_key_detects_source_mapping_changes(self):
        """Ensure changes to source mappings invalidate cache key even with identical dataset length."""
        cfg = get_default_coverage_config()
        imgs = [_img("i1")]
        objs = [_obj("o1", "i1")]

        key_none = compute_coverage_cache_key(imgs, objs, cfg, sources=None)
        key_src_a = compute_coverage_cache_key(imgs, objs, cfg, sources={"ds1:i1": "cam_a"})
        key_src_b = compute_coverage_cache_key(imgs, objs, cfg, sources={"ds1:i1": "cam_b"})

        assert key_none != key_src_a
        assert key_src_a != key_src_b

        # List of sources format
        key_list_a = compute_coverage_cache_key(imgs, objs, cfg, sources=[{"image_key": "ds1:i1", "source_id": "cam_a"}])
        key_list_b = compute_coverage_cache_key(imgs, objs, cfg, sources=[{"image_key": "ds1:i1", "source_id": "cam_b"}])
        assert key_list_a != key_list_b

    def test_cache_key_detects_config_changes_without_version_bump(self):
        """Ensure modification of slice filters, targets, weights, flags, or policy invalidates key without version bump."""
        imgs = [_img("i1")]
        objs = [_obj("o1", "i1")]

        base_cfg = CoverageConfig(
            config_version="1",
            metadata_policy=MetadataPolicy(missing_warning_rate=0.05, unknown_warning_rate=0.10),
            slices=[
                SliceDefinition(
                    id="s1",
                    name="S1",
                    unit="image",
                    filters={"contains_class": "person"},
                    target_count=50,
                    weight=2.0,
                    enabled=True,
                )
            ],
        )
        key_base = compute_coverage_cache_key(imgs, objs, base_cfg)

        # 1. target_count changed (same config_version="1")
        cfg_target = CoverageConfig(
            config_version="1",
            slices=[
                SliceDefinition(id="s1", name="S1", unit="image", filters={"contains_class": "person"}, target_count=75, weight=2.0, enabled=True)
            ],
        )
        assert compute_coverage_cache_key(imgs, objs, cfg_target) != key_base

        # 2. weight changed
        cfg_weight = CoverageConfig(
            config_version="1",
            slices=[
                SliceDefinition(id="s1", name="S1", unit="image", filters={"contains_class": "person"}, target_count=50, weight=4.0, enabled=True)
            ],
        )
        assert compute_coverage_cache_key(imgs, objs, cfg_weight) != key_base

        # 3. filters changed
        cfg_filters = CoverageConfig(
            config_version="1",
            slices=[
                SliceDefinition(id="s1", name="S1", unit="image", filters={"contains_class": "car"}, target_count=50, weight=2.0, enabled=True)
            ],
        )
        assert compute_coverage_cache_key(imgs, objs, cfg_filters) != key_base

        # 4. enabled changed
        cfg_enabled = CoverageConfig(
            config_version="1",
            slices=[
                SliceDefinition(id="s1", name="S1", unit="image", filters={"contains_class": "person"}, target_count=50, weight=2.0, enabled=False)
            ],
        )
        assert compute_coverage_cache_key(imgs, objs, cfg_enabled) != key_base

        # 5. metadata_policy changed
        cfg_policy = CoverageConfig(
            config_version="1",
            metadata_policy=MetadataPolicy(missing_warning_rate=0.20, unknown_warning_rate=0.10),
            slices=[
                SliceDefinition(id="s1", name="S1", unit="image", filters={"contains_class": "person"}, target_count=50, weight=2.0, enabled=True)
            ],
        )
        assert compute_coverage_cache_key(imgs, objs, cfg_policy) != key_base

    def test_render_coverage_recalculates_when_dataset_changes(self):
        """Regression test for Finding 1: Ensure stale results are not reused across dataset swaps."""
        img1 = _img("i1", timeofday="night", weather="rain")
        obj1 = _obj("o1", "i1", "person")

        mock_session_state = {}

        def fake_columns(spec, **kwargs):
            count = len(spec) if isinstance(spec, (list, tuple)) else int(spec)
            return [MagicMock() for _ in range(count)]

        with patch("streamlit.session_state", mock_session_state), \
             patch("streamlit.columns", side_effect=fake_columns), \
             patch("streamlit.header"), \
             patch("streamlit.subheader"), \
             patch("streamlit.dataframe"), \
             patch("streamlit.plotly_chart"):

            # Run 1: Dataset A (1 image)
            render_coverage([img1], valid_objects=[obj1], dataset_version="v1")
            assert mock_session_state["coverage_slice_results"]["person_night_rain"].support == 1

            # Run 2: Dataset B (different images with no night rain match)
            img2 = _img("i2", timeofday="day", weather="clear")
            obj2 = _obj("o2", "i2", "person")
            render_coverage([img2], valid_objects=[obj2], dataset_version="v2")

            # Must have recalculated to 0, not stale 1
            assert mock_session_state["coverage_slice_results"]["person_night_rain"].support == 0


# ===========================================================================
# 7. Interactive Button & Banner Tests
# ===========================================================================

class TestRenderCoverageInteractiveAndBanners:
    """Verifies apply-button execution path, flash messages, empty-slice states, and chart colors."""

    def _fake_columns(self, spec, **kwargs):
        count = len(spec) if isinstance(spec, (list, tuple)) else int(spec)
        return [MagicMock() for _ in range(count)]

    def test_render_coverage_apply_button_valid_edit_updates_state_and_reruns(self):
        """Regression test for Finding 2 & 3: Valid edit updates config, stores flash message, and reruns."""
        images = [_img("i1", timeofday="night", weather="rain")]
        objects = [_obj("o1", "i1", "person")]
        cfg = get_default_coverage_config()

        mock_session_state = {}

        # Configure mocks so st.button returns True
        with patch("streamlit.session_state", mock_session_state), \
             patch("streamlit.columns", side_effect=self._fake_columns), \
             patch("streamlit.header"), \
             patch("streamlit.subheader"), \
             patch("streamlit.dataframe"), \
             patch("streamlit.plotly_chart"), \
             patch("streamlit.selectbox", return_value="person_night_rain"), \
             patch("streamlit.number_input", side_effect=[75, 4.5]), \
             patch("streamlit.checkbox", return_value=True), \
             patch("streamlit.button", return_value=True), \
             patch("streamlit.rerun") as mock_rerun:

            render_coverage(images, valid_objects=objects, config=cfg, dataset_version="v1")

            # Config updated and version incremented
            new_cfg = mock_session_state["coverage_config"]
            target_slice = next(s for s in new_cfg.slices if s.id == "person_night_rain")
            assert target_slice.target_count == 75
            assert target_slice.weight == 4.5
            assert new_cfg.config_version == "2"

            # Results recalculated
            assert mock_session_state["coverage_slice_results"]["person_night_rain"].target_count == 75

            # Flash messages queued
            assert "coverage_flash_messages" in mock_session_state
            flash_types = [m[0] for m in mock_session_state["coverage_flash_messages"]]
            assert "success" in flash_types

            # Streamlit rerun triggered
            mock_rerun.assert_called_once()

    def test_render_coverage_apply_button_invalid_edit_reports_error(self):
        """Regression test for Finding 2: Invalid edit shows error and does not rerun."""
        images = [_img("i1", timeofday="night", weather="rain")]
        objects = [_obj("o1", "i1", "person")]
        cfg = get_default_coverage_config()

        mock_session_state = {}

        # Target = 0 (invalid)
        with patch("streamlit.session_state", mock_session_state), \
             patch("streamlit.columns", side_effect=self._fake_columns), \
             patch("streamlit.header"), \
             patch("streamlit.subheader"), \
             patch("streamlit.dataframe"), \
             patch("streamlit.plotly_chart"), \
             patch("streamlit.selectbox", return_value="person_night_rain"), \
             patch("streamlit.number_input", side_effect=[0, 4.5]), \
             patch("streamlit.checkbox", return_value=True), \
             patch("streamlit.button", return_value=True), \
             patch("streamlit.error") as mock_error, \
             patch("streamlit.rerun") as mock_rerun:

            render_coverage(images, valid_objects=objects, config=cfg, dataset_version="v1")

            mock_error.assert_called()
            mock_rerun.assert_not_called()
            assert mock_session_state["coverage_config"].config_version == "1"

    def test_render_coverage_apply_button_no_op_edit_no_rerun(self):
        """Regression test for Finding 4: No-op edit shows info and does not rerun or bump version."""
        images = [_img("i1", timeofday="night", weather="rain")]
        objects = [_obj("o1", "i1", "person")]
        cfg = get_default_coverage_config()

        mock_session_state = {}

        # Exact same values for person_night_rain (target=50, weight=3.0, enabled=True)
        with patch("streamlit.session_state", mock_session_state), \
             patch("streamlit.columns", side_effect=self._fake_columns), \
             patch("streamlit.header"), \
             patch("streamlit.subheader"), \
             patch("streamlit.dataframe"), \
             patch("streamlit.plotly_chart"), \
             patch("streamlit.selectbox", return_value="person_night_rain"), \
             patch("streamlit.number_input", side_effect=[50, 3.0]), \
             patch("streamlit.checkbox", return_value=True), \
             patch("streamlit.button", return_value=True), \
             patch("streamlit.info") as mock_info, \
             patch("streamlit.rerun") as mock_rerun:

            render_coverage(images, valid_objects=objects, config=cfg, dataset_version="v1")

            mock_rerun.assert_not_called()
            assert mock_session_state["coverage_config"].config_version == "1"
            assert any("Không có thay đổi" in str(call) for call in mock_info.call_args_list)

    def test_render_coverage_flash_messages_rendered_and_cleared(self):
        """Regression test for Finding 3: Pending flash messages render on next run and are cleared."""
        mock_session_state = {
            "coverage_flash_messages": [
                ("success", "Thành công test!"),
                ("warning", "Cảnh báo test!"),
            ]
        }

        with patch("streamlit.session_state", mock_session_state), \
             patch("streamlit.columns", side_effect=self._fake_columns), \
             patch("streamlit.header"), \
             patch("streamlit.subheader"), \
             patch("streamlit.dataframe"), \
             patch("streamlit.plotly_chart"), \
             patch("streamlit.success") as mock_success, \
             patch("streamlit.warning") as mock_warning:

            render_coverage([], valid_objects=[], dataset_version="v1")

            mock_success.assert_called_with("Thành công test!")
            mock_warning.assert_any_call("Cảnh báo test!")
            # Emptied from session state so they do not repeat
            assert "coverage_flash_messages" not in mock_session_state

    def test_render_coverage_empty_eligible_slices_banner(self):
        """Regression test for Finding 5: Empty eligible slice set displays explicit |S| = 0 and no 0/0."""
        empty_cfg = CoverageConfig(slices=[])
        mock_session_state = {}

        with patch("streamlit.session_state", mock_session_state), \
             patch("streamlit.columns", side_effect=self._fake_columns), \
             patch("streamlit.header"), \
             patch("streamlit.subheader"), \
             patch("streamlit.dataframe"), \
             patch("streamlit.plotly_chart"), \
             patch("streamlit.info") as mock_info:

            render_coverage([], valid_objects=[], config=empty_cfg, dataset_version="v1")

            info_calls = [str(c) for c in mock_info.call_args_list]
            assert any("|S| = 0" in c for c in info_calls)
            # Ensure "0/0" below-target string was NOT produced
            assert not any("0/0 slice" in c for c in info_calls)

    def test_render_coverage_chart_distinguishes_provisional_support(self):
        """Regression test for Finding 6: Provisional slices use amber color in Plotly chart."""
        # Image has missing weather -> person_night_rain becomes provisional (unresolved_count > 0)
        img = _img("i1", timeofday="night", weather=None)
        obj = _obj("o1", "i1", "person")

        mock_session_state = {}
        captured_figs = []

        def fake_plotly(fig, **kwargs):
            captured_figs.append(fig)

        with patch("streamlit.session_state", mock_session_state), \
             patch("streamlit.columns", side_effect=self._fake_columns), \
             patch("streamlit.header"), \
             patch("streamlit.subheader"), \
             patch("streamlit.dataframe"), \
             patch("streamlit.plotly_chart", side_effect=fake_plotly):

            render_coverage([img], valid_objects=[obj], dataset_version="v1")

            assert len(captured_figs) == 1
            fig = captured_figs[0]
            # Trace 0 is Support bar
            support_trace = fig.data[0]
            # person_night_rain has missing weather -> provisional -> amber #e67700
            assert "#e67700" in support_trace.marker.color
