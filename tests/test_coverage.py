"""Deterministic unit tests for Phase 2 Coverage Engine.

Verifies acceptance criteria from:
- FEEDBACK/Recommended-solution_DAT/Coverage_Recommendation_Engine_Coding_Spec_N2-05B.md §11
- FEEDBACK/Recommended-solution_DAT/Co_so_ly_thuyet_Data_Quality_Coverage_N2-05B.md §6
"""

import math
import pytest

from core.coverage_config import (
    CoverageConfig,
    MetadataPolicy,
    SliceDefinition,
    validate_coverage_config,
)
from core.coverage_metrics import (
    calculate_dataset_coverage,
    calculate_slice_metrics,
)
from core.schema import ImageRecord, ObjectRecord
from core.slice_engine import evaluate_slice, measure_slices


# ---------------------------------------------------------------------------
# Test Fixture Helpers
# ---------------------------------------------------------------------------

def _img(
    img_id: str = "img1",
    dataset_id: str = "ds1",
    width: int = 1920,
    height: int = 1080,
    timeofday: str | None = "day",
    weather: str | None = "clear",
    source_id: str | None = None,
    has_scene_conflict: bool = False,
    scene_tags: list | None = None,
) -> ImageRecord:
    rec = ImageRecord(
        dataset_id=dataset_id,
        image_id=img_id,
        image_path=f"/path/{img_id}.jpg",
        width=width,
        height=height,
        timeofday=timeofday,
        weather=weather,
        has_scene_conflict=has_scene_conflict,
        scene_tags=scene_tags or [],
    )
    if source_id is not None:
        rec.source_id = source_id  # type: ignore[attr-defined]
    return rec


def _obj(
    obj_id: str = "o1",
    img_id: str = "img1",
    class_name: str = "person",
    dataset_id: str = "ds1",
    x_min: float = 10.0,
    y_min: float = 10.0,
    x_max: float = 50.0,
    y_max: float = 50.0,
    occluded: bool = False,
) -> ObjectRecord:
    return ObjectRecord(
        object_id=obj_id,
        image_id=img_id,
        class_name=class_name,
        x_min=x_min,
        y_min=y_min,
        x_max=x_max,
        y_max=y_max,
        occluded=occluded,
        dataset_id=dataset_id,
    )


# ===========================================================================
# 1. Configuration Validation Tests
# ===========================================================================


class TestCoverageConfigValidation:
    """Tests for core.coverage_config.validate_coverage_config."""

    def test_valid_minimal_config(self):
        """Valid configuration passes validation."""
        cfg = {
            "definition_version": "1.0",
            "config_version": "1",
            "metadata_policy": {"missing_warning_rate": 0.05, "unknown_warning_rate": 0.10},
            "slices": [
                {
                    "id": "person_slice",
                    "name": "Person Image Slice",
                    "unit": "image",
                    "filters": {"contains_class": "person", "timeofday": "day"},
                    "target_count": 50,
                    "weight": 2.0,
                }
            ],
        }
        res = validate_coverage_config(cfg)
        assert res.valid is True
        assert len(res.errors) == 0
        assert res.config is not None
        assert len(res.config.slices) == 1
        assert res.config.slices[0].id == "person_slice"

    def test_duplicate_slice_id_rejected(self):
        """Duplicate slice IDs must be rejected."""
        cfg = {
            "slices": [
                {
                    "id": "dup_slice",
                    "name": "Slice 1",
                    "unit": "image",
                    "filters": {"contains_class": "person"},
                    "target_count": 10,
                },
                {
                    "id": "dup_slice",
                    "name": "Slice 2",
                    "unit": "object",
                    "filters": {"class_name": "car"},
                    "target_count": 20,
                },
            ]
        }
        res = validate_coverage_config(cfg)
        assert res.valid is False
        assert any("Duplicate slice id" in err for err in res.errors)

    def test_invalid_unit_rejected(self):
        """Unit other than 'image' or 'object' must be rejected."""
        cfg = {
            "slices": [
                {
                    "id": "invalid_unit_slice",
                    "name": "Slice",
                    "unit": "dataset",
                    "filters": {"contains_class": "person"},
                    "target_count": 10,
                }
            ]
        }
        res = validate_coverage_config(cfg)
        assert res.valid is False
        assert any("unit 'dataset' is invalid" in err for err in res.errors)

    def test_non_positive_or_non_integer_target_count_rejected(self):
        """target_count must be a positive integer."""
        for bad_target in [0, -5, 10.5, "10", True]:
            cfg = {
                "slices": [
                    {
                        "id": "bad_target_slice",
                        "name": "Slice",
                        "unit": "image",
                        "filters": {"contains_class": "person"},
                        "target_count": bad_target,
                    }
                ]
            }
            res = validate_coverage_config(cfg)
            assert res.valid is False
            assert any("target_count must be a positive integer" in err for err in res.errors)

    def test_invalid_weight_rejected(self):
        """weight must be a finite positive number."""
        for bad_weight in [0, -1.0, float("nan"), float("inf"), True]:
            cfg = {
                "slices": [
                    {
                        "id": "bad_weight_slice",
                        "name": "Slice",
                        "unit": "image",
                        "filters": {"contains_class": "person"},
                        "target_count": 10,
                        "weight": bad_weight,
                    }
                ]
            }
            res = validate_coverage_config(cfg)
            assert res.valid is False
            assert any("weight must be a finite positive number" in err for err in res.errors)

    def test_unsupported_filter_keys_rejected_explicitly(self):
        """Unsupported filter keys must never be silently ignored; reject explicitly."""
        cfg = {
            "slices": [
                {
                    "id": "unsupported_filter_slice",
                    "name": "Slice",
                    "unit": "image",
                    "filters": {
                        "contains_class": "person",
                        "arbitrary_unsupported_key": "some_value",
                    },
                    "target_count": 10,
                }
            ]
        }
        res = validate_coverage_config(cfg)
        assert res.valid is False
        assert any("unsupported filter 'arbitrary_unsupported_key'" in err for err in res.errors)

    def test_area_ratio_min_greater_than_max_rejected(self):
        """area_ratio_min cannot exceed area_ratio_max."""
        cfg = {
            "slices": [
                {
                    "id": "bad_area_slice",
                    "name": "Slice",
                    "unit": "object",
                    "filters": {
                        "class_name": "person",
                        "area_ratio_min": 0.5,
                        "area_ratio_max": 0.1,
                    },
                    "target_count": 10,
                }
            ]
        }
        res = validate_coverage_config(cfg)
        assert res.valid is False
        assert any("area_ratio_min (0.5) cannot be greater than area_ratio_max (0.1)" in err for err in res.errors)

    def test_metadata_policy_out_of_bounds_rejected(self):
        """Metadata policy rates must be within [0, 1]."""
        cfg = {
            "metadata_policy": {"missing_warning_rate": 1.5, "unknown_warning_rate": -0.1},
            "slices": [
                {
                    "id": "s1",
                    "name": "S1",
                    "unit": "image",
                    "filters": {"contains_class": "person"},
                    "target_count": 10,
                }
            ],
        }
        res = validate_coverage_config(cfg)
        assert res.valid is False
        assert any("missing_warning_rate must be within [0.0, 1.0]" in err for err in res.errors)
        assert any("unknown_warning_rate must be within [0.0, 1.0]" in err for err in res.errors)

    def test_unknown_class_warns_configuration(self):
        """Criterion 8: Class not in label schema emits a configuration warning."""
        cfg = {
            "slices": [
                {
                    "id": "unknown_class_slice",
                    "name": "Slice",
                    "unit": "image",
                    "filters": {"contains_class": "unsupported_alien_class"},
                    "target_count": 10,
                }
            ]
        }
        known_classes = {"person", "car", "bicycle"}
        res = validate_coverage_config(cfg, known_classes=known_classes)
        assert res.valid is True
        assert len(res.warnings) == 1
        assert "not in known class schema" in res.warnings[0]


# ===========================================================================
# 2. Acceptance Criteria & Slice Engine Tests
# ===========================================================================


class TestAcceptanceCriteria:
    """Verifies all mandatory acceptance criteria from Coding Spec §11."""

    def test_criterion_1_one_image_three_person_objects(self):
        """Criterion 1: One image with 3 person objects: image support=1, object support=3."""
        img = _img("img1")
        objs = [
            _obj("o1", "img1", "person"),
            _obj("o2", "img1", "person"),
            _obj("o3", "img1", "person"),
        ]

        # Image slice
        img_slice = SliceDefinition(
            id="s_img",
            name="Image Person",
            unit="image",
            filters={"contains_class": "person"},
            target_count=5,
        )
        res_img = evaluate_slice(img_slice, [img], objs)
        assert res_img.support == 1
        assert res_img.matched_keys == ["ds1:img1"]

        # Object slice
        obj_slice = SliceDefinition(
            id="s_obj",
            name="Object Person",
            unit="object",
            filters={"class_name": "person"},
            target_count=5,
        )
        res_obj = evaluate_slice(obj_slice, [img], objs)
        assert res_obj.support == 3
        assert set(res_obj.matched_keys) == {"ds1:o1", "ds1:o2", "ds1:o3"}

    def test_criterion_2_cooccurrence_large_person_small_car(self):
        """Criterion 2: Image with large person and small car does not satisfy small-person image slice.

        Enforces same-object conjunction: person and small bbox must be on the SAME object.
        """
        # Image dimensions 1000 x 1000 => area = 1,000,000
        img = _img("img1", width=1000, height=1000)

        # Large person: 500x500 => area = 250,000 => area_ratio = 0.25 (> 0.01)
        large_person = _obj(
            "o1", "img1", "person",
            x_min=0, y_min=0, x_max=500, y_max=500
        )
        # Small car: 50x50 => area = 2,500 => area_ratio = 0.0025 (<= 0.01)
        small_car = _obj(
            "o2", "img1", "car",
            x_min=600, y_min=600, x_max=650, y_max=650
        )

        slice_def = SliceDefinition(
            id="small_person_slice",
            name="Small Person Image Slice",
            unit="image",
            filters={"contains_class": "person", "area_ratio_max": 0.01},
            target_count=10,
        )

        res = evaluate_slice(slice_def, [img], [large_person, small_car])
        # Must NOT match because person is large and small object is a car!
        assert res.support == 0
        assert len(res.matched_keys) == 0

    def test_criterion_3_support_10_target_50_weight_3(self):
        """Criterion 3: support=10, target=50, weight=3 => gap=40, attainment=0.2, priority=2.4."""
        # Create 10 images with 1 person each
        images = [_img(f"img_{i}") for i in range(10)]
        objects = [_obj(f"o_{i}", f"img_{i}", "person") for i in range(10)]

        slice_def = SliceDefinition(
            id="s_test",
            name="Test Slice",
            unit="image",
            filters={"contains_class": "person"},
            target_count=50,
            weight=3.0,
        )
        res = evaluate_slice(slice_def, images, objects)
        assert res.support == 10
        assert res.target_count == 50
        assert res.gap == 40
        assert pytest.approx(res.attainment, 1e-6) == 0.2
        assert pytest.approx(res.priority, 1e-6) == 2.4

    def test_criterion_4_support_greater_than_target(self):
        """Criterion 4: support > target => gap=0, attainment=1.0, priority=0.0."""
        images = [_img(f"img_{i}") for i in range(15)]
        objects = [_obj(f"o_{i}", f"img_{i}", "person") for i in range(15)]

        slice_def = SliceDefinition(
            id="s_met",
            name="Met Slice",
            unit="image",
            filters={"contains_class": "person"},
            target_count=10,
            weight=2.5,
        )
        res = evaluate_slice(slice_def, images, objects)
        assert res.support == 15
        assert res.gap == 0
        assert res.attainment == 1.0
        assert res.priority == 0.0
        assert res.status == "met"

    def test_criterion_5_missing_metadata_unresolved_not_false(self):
        """Criterion 5: Missing required metadata produces unresolved count; does not confirm false."""
        # Image has person, but weather is None (missing)
        img_missing_weather = _img("img1", timeofday="day", weather=None)
        obj = _obj("o1", "img1", "person")

        slice_def = SliceDefinition(
            id="person_rain",
            name="Person in Rain",
            unit="image",
            filters={"contains_class": "person", "weather": "rain"},
            target_count=10,
        )
        res = evaluate_slice(slice_def, [img_missing_weather], [obj])
        assert res.support == 0
        assert res.unresolved_count == 1
        assert res.unresolved_keys == ["ds1:img1"]
        assert res.status == "unresolved"

    def test_criterion_6_missing_source_id_returns_unavailable(self):
        """Criterion 6: Missing source_id returns unavailable source support; never fabricates."""
        img = _img("img1")  # No source_id attached
        obj = _obj("o1", "img1", "person")

        slice_def = SliceDefinition(
            id="s1",
            name="S1",
            unit="image",
            filters={"contains_class": "person"},
            target_count=5,
        )
        res = evaluate_slice(slice_def, [img], [obj], sources=None)
        assert res.support == 1
        assert res.source_support is None
        assert res.source_support_status == "not_available"

    def test_criterion_6_present_source_id_counts_unique_sources(self):
        """Criterion 6 (positive case): When source_id is present, counts independent sources."""
        img1 = _img("img1", source_id="src_camera_A")
        img2 = _img("img2", source_id="src_camera_A")  # Same source
        img3 = _img("img3", source_id="src_camera_B")  # Different source
        objs = [
            _obj("o1", "img1", "person"),
            _obj("o2", "img2", "person"),
            _obj("o3", "img3", "person"),
        ]

        slice_def = SliceDefinition(
            id="s1",
            name="S1",
            unit="image",
            filters={"contains_class": "person"},
            target_count=5,
        )
        res = evaluate_slice(slice_def, [img1, img2, img3], objs)
        assert res.support == 3
        assert res.source_support == 2  # 2 unique sources: src_camera_A, src_camera_B
        assert res.source_support_status == "available"

    def test_criterion_7_unknown_timeofday_does_not_match_day_or_night(self):
        """Criterion 7: 'unknown' is not day or night; tracked separately from missing as unresolved."""
        img_unknown = _img("img1", timeofday="unknown")
        obj = _obj("o1", "img1", "person")

        slice_night = SliceDefinition(
            id="night_slice",
            name="Night Person",
            unit="image",
            filters={"contains_class": "person", "timeofday": "night"},
            target_count=5,
        )
        res = evaluate_slice(slice_night, [img_unknown], [obj])
        # Must not match night!
        assert res.support == 0
        # Tracked as unresolved
        assert res.unresolved_count == 1
        assert res.unresolved_keys == ["ds1:img1"]

    def test_criterion_9_overlapping_slices_no_summed_gaps(self):
        """Criterion 9: Overlapping slices do not sum gaps across slices into total needed samples."""
        img1 = _img("img1", timeofday="day", weather="clear")
        obj1 = _obj("o1", "img1", "person")

        slice_a = SliceDefinition(
            id="sa", name="A", unit="image",
            filters={"contains_class": "person"}, target_count=5, weight=1.0
        )
        slice_b = SliceDefinition(
            id="sb", name="B", unit="image",
            filters={"timeofday": "day"}, target_count=5, weight=1.0
        )

        res_a = evaluate_slice(slice_a, [img1], [obj1])
        res_b = evaluate_slice(slice_b, [img1], [obj1])

        assert res_a.gap == 4
        assert res_b.gap == 4

        dataset_res = calculate_dataset_coverage([res_a, res_b])
        # Verify that DatasetCoverageResult does not fabricate a total_samples_needed sum of 8
        metrics_dict = dataset_res.slice_metrics
        assert metrics_dict["sa"]["gap"] == 4
        assert metrics_dict["sb"]["gap"] == 4
        assert not hasattr(dataset_res, "total_gap_sum")

    def test_criterion_14_invalid_geometry_excluded_from_size_slice(self):
        """Criterion 14: Invalid bbox geometry excluded from area-ratio slice; reported as excluded."""
        img = _img("img1", width=1000, height=1000)
        # Invalid bbox: reversed x (x_min > x_max)
        bad_obj = _obj("o1", "img1", "person", x_min=500, y_min=10, x_max=100, y_max=50)

        slice_def = SliceDefinition(
            id="size_slice",
            name="Size Slice",
            unit="object",
            filters={"class_name": "person", "area_ratio_min": 0.01},
            target_count=5,
        )
        res = evaluate_slice(slice_def, [img], [bad_obj])
        assert res.support == 0
        assert res.excluded_invalid_geometry_count == 1

    def test_criterion_15_empty_slice_set_zero_denominator_safe(self):
        """Criterion 15: S empty or zero denominator returns not_available, never ZeroDivisionError."""
        res = calculate_dataset_coverage([])
        assert res.eligible_slices_count == 0
        assert res.coverage is None
        assert res.weighted_coverage is None
        assert res.weighted_attainment is None
        assert res.status == "not_available"
        assert "No eligible slices" in res.reasons[0]

    def test_criterion_16_all_targets_met_with_unresolved_blockers_withholds_signoff(self):
        """Criterion 16: All targets met but unresolved metadata blockers remain: do not emit TARGETS_MET."""
        img1 = _img("img1", weather="rain")
        obj1 = _obj("o1", "img1", "person")

        # Second image has person but weather is missing
        img2 = _img("img2", weather=None)
        obj2 = _obj("o2", "img2", "person")

        slice_def = SliceDefinition(
            id="s1",
            name="S1",
            unit="image",
            filters={"contains_class": "person", "weather": "rain"},
            target_count=1,  # Target is 1, and img1 satisfies target
            weight=1.0,
        )
        res = evaluate_slice(slice_def, [img1, img2], [obj1, obj2])
        assert res.support == 1
        assert res.target_count == 1
        assert res.unresolved_count == 1  # img2 is unresolved!

        dataset_res = calculate_dataset_coverage([res])
        assert dataset_res.met_slices_count == 1
        assert dataset_res.is_provisional is True
        # Sign-off must be withheld because unresolved metadata blocker remains!
        assert dataset_res.targets_met is False
        assert any("unresolved metadata blockers remain" in r for r in dataset_res.reasons)


# ===========================================================================
# 3. Additional Edge Cases & Resilience Tests
# ===========================================================================


class TestAdditionalCoverageEdgeCases:
    """Tests conflicting metadata, duplicate keys, field-specific availability, and feasibility."""

    def test_conflicting_scene_tags_handled_as_unresolved(self):
        """Scene tag conflict makes required metadata unresolved, not definitive failure."""
        img = _img(
            "img_conflict",
            has_scene_conflict=True,
            scene_tags=[
                {"timeofday": "day", "weather": "clear"},
                {"timeofday": "night", "weather": "rain"},
            ],
        )
        obj = _obj("o1", "img_conflict", "person")

        slice_def = SliceDefinition(
            id="night_slice",
            name="Night",
            unit="image",
            filters={"contains_class": "person", "timeofday": "night"},
            target_count=5,
        )
        res = evaluate_slice(slice_def, [img], [obj])
        assert res.support == 0
        assert res.unresolved_count == 1
        assert res.unresolved_keys == ["ds1:img_conflict"]

    def test_duplicate_keys_deduplicated_cleanly(self):
        """Repeated records with identical keys are counted once."""
        img = _img("img1")
        # Same image repeated in input list
        images = [img, img, img]
        objs = [_obj("o1", "img1", "person")]

        slice_def = SliceDefinition(
            id="s1", name="S1", unit="image",
            filters={"contains_class": "person"}, target_count=5
        )
        res = evaluate_slice(slice_def, images, objs)
        assert res.support == 1
        assert res.matched_keys == ["ds1:img1"]

    def test_field_specific_metadata_availability_tracking(self):
        """Slice tracking only class is not impacted by missing weather."""
        img1 = _img("img1", timeofday="day", weather=None)
        img2 = _img("img2", timeofday="day", weather="rain")
        objs = [_obj("o1", "img1", "person"), _obj("o2", "img2", "person")]

        # Slice only requires timeofday, not weather
        slice_def = SliceDefinition(
            id="s_tod",
            name="S TOD",
            unit="image",
            filters={"contains_class": "person", "timeofday": "day"},
            target_count=5,
        )
        res = evaluate_slice(slice_def, [img1, img2], objs)
        # Both images match because weather was not required!
        assert res.support == 2
        assert res.unresolved_count == 0
        assert res.metadata_availability["timeofday"] == 1.0
        assert "weather" not in res.metadata_availability

    def test_infeasible_slices_excluded_from_dataset_coverage(self):
        """Infeasible slices are excluded from eligible set S."""
        s_feasible = SliceDefinition(
            id="sf", name="Feasible", unit="image",
            filters={"contains_class": "person"}, target_count=1, weight=1.0,
            feasibility="confirmed"
        )
        s_infeasible = SliceDefinition(
            id="si", name="Infeasible", unit="image",
            filters={"contains_class": "person"}, target_count=100, weight=1.0,
            feasibility="infeasible"
        )

        cfg = CoverageConfig(slices=[s_feasible, s_infeasible])
        res_f = evaluate_slice(s_feasible, [_img("i1")], [_obj("o1", "i1", "person")])
        res_i = evaluate_slice(s_infeasible, [_img("i1")], [_obj("o1", "i1", "person")])

        dataset_res = calculate_dataset_coverage([res_f, res_i], config=cfg)
        assert dataset_res.total_slices == 2
        assert dataset_res.eligible_slices_count == 1
        assert dataset_res.met_slices_count == 1
        assert dataset_res.coverage == 1.0
        assert dataset_res.targets_met is True

    def test_measure_slices_top_level_runner(self):
        """measure_slices processes all enabled slices in a config."""
        s1 = SliceDefinition(
            id="s1", name="S1", unit="image",
            filters={"contains_class": "person"}, target_count=1, enabled=True
        )
        s2 = SliceDefinition(
            id="s2", name="S2", unit="image",
            filters={"contains_class": "car"}, target_count=1, enabled=False
        )
        cfg = CoverageConfig(slices=[s1, s2])
        img = _img("i1")
        obj = _obj("o1", "i1", "person")

        results = measure_slices([img], [obj], cfg)
        assert "s1" in results
        assert "s2" not in results  # s2 is disabled
        assert results["s1"].support == 1
