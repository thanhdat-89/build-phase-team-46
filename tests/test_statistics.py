"""Unit tests for the statistics layer (core/statistics.py).

Tests cover all five public functions with in-memory fixtures.
No CVAT XML, no Streamlit, no file I/O.
"""

from __future__ import annotations

import pytest

from core.schema import ImageRecord, ObjectRecord
from core.statistics import (
    class_distribution,
    class_image_distribution,
    dataset_summary,
    dq01_schema_validity_images,
    dq01_schema_validity_objects,
    dq01_schema_validity_rate,
    dq01_schema_validity_tags,
    dq07_duplicate_record_rate,
    dq08_audited_error_rate,
    timeofday_distribution,
    weather_distribution,
)


# ── helpers ────────────────────────────────────────────────────────────


def _img(
    image_id: str = "img_1",
    *,
    dataset_id: str = "ds1",
    path: str = "a.jpg",
    width: int = 100,
    height: int = 100,
    timeofday: str | None = None,
    weather: str | None = None,
) -> ImageRecord:
    return ImageRecord(
        dataset_id=dataset_id,
        image_id=image_id,
        image_path=path,
        width=width,
        height=height,
        timeofday=timeofday,
        weather=weather,
    )


def _obj(
    object_id: str = "obj_1",
    image_id: str = "img_1",
    class_name: str = "car",
) -> ObjectRecord:
    return ObjectRecord(
        object_id=object_id,
        image_id=image_id,
        class_name=class_name,
        x_min=0.0,
        y_min=0.0,
        x_max=10.0,
        y_max=10.0,
    )


# ═══════════════════════════════════════════════════════════════════════
# 1. dataset_summary
# ═══════════════════════════════════════════════════════════════════════


class TestDatasetSummary:
    """Tests for dataset_summary()."""

    def test_empty_dataset(self):
        result = dataset_summary([], [])
        assert result == {
            "total_images": 0,
            "total_objects": 0,
            "total_classes": 0,
            "annotated_images": 0,
            "unannotated_images": 0,
        }

    def test_multiple_images(self):
        images = [_img("i1"), _img("i2"), _img("i3")]
        result = dataset_summary(images, [])
        assert result["total_images"] == 3

    def test_multiple_objects(self):
        images = [_img("i1")]
        objects = [
            _obj("o1", "i1", "car"),
            _obj("o2", "i1", "person"),
        ]
        result = dataset_summary(images, objects)
        assert result["total_objects"] == 2

    def test_multiple_objects_same_class(self):
        images = [_img("i1")]
        objects = [
            _obj("o1", "i1", "car"),
            _obj("o2", "i1", "car"),
            _obj("o3", "i1", "car"),
        ]
        result = dataset_summary(images, objects)
        assert result["total_objects"] == 3
        assert result["total_classes"] == 1

    def test_image_with_zero_objects(self):
        images = [_img("i1"), _img("i2")]
        objects = [_obj("o1", "i1", "car")]
        result = dataset_summary(images, objects)
        assert result["annotated_images"] == 1
        assert result["unannotated_images"] == 1

    def test_annotated_and_unannotated(self):
        images = [_img("i1"), _img("i2"), _img("i3")]
        objects = [
            _obj("o1", "i1", "car"),
            _obj("o2", "i2", "bus"),
        ]
        result = dataset_summary(images, objects)
        assert result["annotated_images"] == 2
        assert result["unannotated_images"] == 1

    def test_total_classes_unique(self):
        images = [_img("i1"), _img("i2")]
        objects = [
            _obj("o1", "i1", "car"),
            _obj("o2", "i1", "car"),
            _obj("o3", "i2", "person"),
            _obj("o4", "i2", "car"),
        ]
        result = dataset_summary(images, objects)
        assert result["total_classes"] == 2  # car, person


# ═══════════════════════════════════════════════════════════════════════
# 2. class_distribution
# ═══════════════════════════════════════════════════════════════════════


class TestClassDistribution:
    """Tests for class_distribution()."""

    def test_empty_objects(self):
        result = class_distribution([])
        assert result == []

    def test_one_class_multiple_objects(self):
        objects = [
            _obj("o1", "i1", "car"),
            _obj("o2", "i2", "car"),
            _obj("o3", "i3", "car"),
        ]
        result = class_distribution(objects)
        assert len(result) == 1
        entry = result[0]
        assert entry["class_name"] == "car"
        assert entry["object_count"] == 3

    def test_multiple_classes(self):
        objects = [
            _obj("o1", "i1", "car"),
            _obj("o2", "i2", "person"),
        ]
        result = class_distribution(objects)
        names = {r["class_name"] for r in result}
        assert names == {"car", "person"}

    def test_object_count_correct(self):
        objects = [
            _obj("o1", "i1", "car"),
            _obj("o2", "i1", "car"),
            _obj("o3", "i1", "person"),
        ]
        result = class_distribution(objects)
        car = next(r for r in result if r["class_name"] == "car")
        person = next(r for r in result if r["class_name"] == "person")
        assert car["object_count"] == 2
        assert person["object_count"] == 1

    def test_image_count_unique_images(self):
        """Two objects of class 'car' in image i1 → image_count must be 1."""
        objects = [
            _obj("o1", "i1", "car"),
            _obj("o2", "i1", "car"),
        ]
        result = class_distribution(objects)
        car = result[0]
        assert car["image_count"] == 1

    def test_image_count_across_images(self):
        """Same class in two different images → image_count = 2."""
        objects = [
            _obj("o1", "i1", "car"),
            _obj("o2", "i2", "car"),
        ]
        result = class_distribution(objects)
        car = result[0]
        assert car["image_count"] == 2

    def test_percentage_based_on_total(self):
        objects = [
            _obj("o1", "i1", "car"),
            _obj("o2", "i1", "car"),
            _obj("o3", "i2", "person"),
        ]
        result = class_distribution(objects)
        car = next(r for r in result if r["class_name"] == "car")
        person = next(r for r in result if r["class_name"] == "person")
        assert car["percentage"] == pytest.approx(200 / 3)       # ~66.67
        assert person["percentage"] == pytest.approx(100 / 3)    # ~33.33

    def test_multiple_objects_same_class_same_image(self):
        """3 'car' boxes in one image → object_count=3, image_count=1."""
        objects = [
            _obj("o1", "i1", "car"),
            _obj("o2", "i1", "car"),
            _obj("o3", "i1", "car"),
        ]
        result = class_distribution(objects)
        car = result[0]
        assert car["object_count"] == 3
        assert car["image_count"] == 1

    def test_no_division_by_zero(self):
        """Empty objects list must not raise ZeroDivisionError."""
        result = class_distribution([])  # no assertion needed; just no crash
        assert result == []


# ═══════════════════════════════════════════════════════════════════════
# 3. timeofday_distribution
# ═══════════════════════════════════════════════════════════════════════


class TestTimeofdayDistribution:
    """Tests for timeofday_distribution()."""

    def test_empty_images(self):
        result = timeofday_distribution([])
        assert result == {
            "day": 0,
            "night": 0,
            "dawn_dusk": 0,
            "unknown": 0,
            "missing": 0,
        }

    def test_day(self):
        images = [_img("i1", timeofday="day")]
        result = timeofday_distribution(images)
        assert result["day"] == 1

    def test_night(self):
        images = [_img("i1", timeofday="night")]
        result = timeofday_distribution(images)
        assert result["night"] == 1

    def test_dawn_dusk(self):
        images = [_img("i1", timeofday="dawn_dusk")]
        result = timeofday_distribution(images)
        assert result["dawn_dusk"] == 1

    def test_unknown(self):
        images = [_img("i1", timeofday="unknown")]
        result = timeofday_distribution(images)
        assert result["unknown"] == 1

    def test_missing_none(self):
        images = [_img("i1", timeofday=None)]
        result = timeofday_distribution(images)
        assert result["missing"] == 1

    def test_unknown_and_missing_separate(self):
        images = [
            _img("i1", timeofday="unknown"),
            _img("i2", timeofday=None),
        ]
        result = timeofday_distribution(images)
        assert result["unknown"] == 1
        assert result["missing"] == 1

    def test_mixed_values(self):
        images = [
            _img("i1", timeofday="day"),
            _img("i2", timeofday="day"),
            _img("i3", timeofday="night"),
            _img("i4", timeofday=None),
        ]
        result = timeofday_distribution(images)
        assert result["day"] == 2
        assert result["night"] == 1
        assert result["missing"] == 1
        assert result["dawn_dusk"] == 0
        assert result["unknown"] == 0


# ═══════════════════════════════════════════════════════════════════════
# 4. weather_distribution
# ═══════════════════════════════════════════════════════════════════════


class TestWeatherDistribution:
    """Tests for weather_distribution()."""

    def test_empty_images(self):
        result = weather_distribution([])
        assert result == {
            "clear": 0,
            "rain": 0,
            "fog": 0,
            "overcast": 0,
            "unknown": 0,
            "missing": 0,
        }

    def test_clear(self):
        images = [_img("i1", weather="clear")]
        result = weather_distribution(images)
        assert result["clear"] == 1

    def test_rain(self):
        images = [_img("i1", weather="rain")]
        result = weather_distribution(images)
        assert result["rain"] == 1

    def test_fog(self):
        images = [_img("i1", weather="fog")]
        result = weather_distribution(images)
        assert result["fog"] == 1

    def test_overcast(self):
        images = [_img("i1", weather="overcast")]
        result = weather_distribution(images)
        assert result["overcast"] == 1

    def test_unknown(self):
        images = [_img("i1", weather="unknown")]
        result = weather_distribution(images)
        assert result["unknown"] == 1

    def test_missing_none(self):
        images = [_img("i1", weather=None)]
        result = weather_distribution(images)
        assert result["missing"] == 1

    def test_unknown_and_missing_separate(self):
        images = [
            _img("i1", weather="unknown"),
            _img("i2", weather=None),
        ]
        result = weather_distribution(images)
        assert result["unknown"] == 1
        assert result["missing"] == 1

    def test_mixed_values(self):
        images = [
            _img("i1", weather="clear"),
            _img("i2", weather="rain"),
            _img("i3", weather="rain"),
            _img("i4", weather=None),
            _img("i5", weather="unknown"),
        ]
        result = weather_distribution(images)
        assert result["clear"] == 1
        assert result["rain"] == 2
        assert result["fog"] == 0
        assert result["overcast"] == 0
        assert result["unknown"] == 1
        assert result["missing"] == 1


# ═══════════════════════════════════════════════════════════════════════
# 5. class_image_distribution
# ═══════════════════════════════════════════════════════════════════════


class TestClassImageDistribution:
    """Tests for class_image_distribution()."""

    def test_empty_objects(self):
        result = class_image_distribution([])
        assert result == []

    def test_multiple_objects_same_class_one_image(self):
        """3 boxes in one image → object_count=3, image_count=1."""
        objects = [
            _obj("o1", "i1", "car"),
            _obj("o2", "i1", "car"),
            _obj("o3", "i1", "car"),
        ]
        result = class_image_distribution(objects)
        assert len(result) == 1
        car = result[0]
        assert car["object_count"] == 3
        assert car["image_count"] == 1

    def test_same_class_multiple_images(self):
        objects = [
            _obj("o1", "i1", "car"),
            _obj("o2", "i2", "car"),
            _obj("o3", "i3", "car"),
        ]
        result = class_image_distribution(objects)
        car = result[0]
        assert car["object_count"] == 3
        assert car["image_count"] == 3

    def test_multiple_classes(self):
        objects = [
            _obj("o1", "i1", "car"),
            _obj("o2", "i1", "person"),
            _obj("o3", "i2", "car"),
        ]
        result = class_image_distribution(objects)
        names = {r["class_name"] for r in result}
        assert names == {"car", "person"}

    def test_object_and_image_count_distinct(self):
        """4 'car' boxes across 2 images → object=4, image=2."""
        objects = [
            _obj("o1", "i1", "car"),
            _obj("o2", "i1", "car"),
            _obj("o3", "i2", "car"),
            _obj("o4", "i2", "car"),
        ]
        result = class_image_distribution(objects)
        car = result[0]
        assert car["object_count"] == 4
        assert car["image_count"] == 2

    def test_no_percentage_key(self):
        """class_image_distribution should NOT include a percentage key."""
        objects = [_obj("o1", "i1", "car")]
        result = class_image_distribution(objects)
        assert "percentage" not in result[0]


# ═══════════════════════════════════════════════════════════════════════
# 6. DQ01 — Schema Validity Rate Tests (Images, Objects, Tags)
# ═══════════════════════════════════════════════════════════════════════


class TestDQ01SchemaValidityRate:
    """Tests for DQ01 Schema Validity Rate across Images, Objects, and Tags."""

    def test_images_schema_validity(self):
        """Images passing all applicable rules vs failing."""
        img_valid = _img("i1", width=100, height=100, timeofday="day", weather="clear")
        img_zero_dim = _img("i2", width=0, height=100)
        img_invalid_weather = _img("i3", width=100, height=100, weather="alien_storm")
        img_conflict = ImageRecord("ds1", "i4", "4.jpg", 100, 100, has_scene_conflict=True)

        res = dq01_schema_validity_images([img_valid, img_zero_dim, img_invalid_weather, img_conflict])
        assert res["metric_id"] == "DQ01"
        assert res["unit"] == "image"
        assert res["status"] == "available"
        assert res["denominator"] == 4
        assert res["numerator"] == 1
        assert res["value"] == 0.25

    def test_images_zero_denominator(self):
        """Empty images list returns not_available, never 0%."""
        res = dq01_schema_validity_images([])
        assert res["unit"] == "image"
        assert res["status"] == "not_available"
        assert res["value"] is None
        assert res["denominator"] == 0

    def test_objects_schema_validity(self):
        """Objects passing all geometric rules vs failing."""
        img = _img("i1", width=100, height=100)
        obj_valid = _obj("o1", "i1", "car")
        obj_reversed = ObjectRecord("o2", "i1", "car", 50.0, 10.0, 10.0, 30.0)
        obj_empty_class = ObjectRecord("o3", "i1", "", 10.0, 10.0, 30.0, 30.0)

        res = dq01_schema_validity_objects([obj_valid, obj_reversed, obj_empty_class], images=[img])
        assert res["metric_id"] == "DQ01"
        assert res["unit"] == "object"
        assert res["status"] == "available"
        assert res["denominator"] == 3
        assert res["numerator"] == 1
        assert res["value"] == 1 / 3

    def test_objects_non_finite_coordinates_invalid(self):
        """Objects with NaN or Inf coordinates are schema-invalid."""
        img = _img("i1", width=100, height=100)
        obj_nan = ObjectRecord("o1", "i1", "car", float("nan"), 10.0, 50.0, 50.0)
        obj_inf = ObjectRecord("o2", "i1", "car", 10.0, float("inf"), 50.0, 50.0)
        obj_valid = _obj("o3", "i1", "car")

        res = dq01_schema_validity_objects([obj_nan, obj_inf, obj_valid], images=[img])
        assert res["denominator"] == 3
        assert res["numerator"] == 1
        assert res["value"] == 1 / 3

    def test_objects_zero_denominator(self):
        """Empty objects list returns not_available, never 0%."""
        res = dq01_schema_validity_objects([])
        assert res["unit"] == "object"
        assert res["status"] == "not_available"
        assert res["value"] is None
        assert res["denominator"] == 0

    def test_tags_schema_validity(self):
        """Tags with valid metadata vs invalid metadata."""
        tag_valid1 = {"timeofday": "day", "weather": "clear"}
        tag_valid2 = {"timeofday": "unknown", "weather": "rain"}
        tag_invalid = {"timeofday": "middle_of_the_night", "weather": "clear"}

        res = dq01_schema_validity_tags([tag_valid1, tag_valid2, tag_invalid])
        assert res["metric_id"] == "DQ01"
        assert res["unit"] == "tag"
        assert res["status"] == "available"
        assert res["denominator"] == 3
        assert res["numerator"] == 2
        assert res["value"] == 2 / 3

    def test_tags_zero_denominator(self):
        """Empty tags list returns not_available, never 0%."""
        res = dq01_schema_validity_tags([])
        assert res["unit"] == "tag"
        assert res["status"] == "not_available"
        assert res["value"] is None
        assert res["denominator"] == 0

    def test_separate_metrics_dispatcher(self):
        """Top-level dispatcher keeps Images, Objects, and Tags strictly separate."""
        img = _img("i1", width=100, height=100, timeofday="day")
        obj = _obj("o1", "i1", "car")
        tags = [{"timeofday": "day", "weather": "clear"}]

        res = dq01_schema_validity_rate(images=[img], objects=[obj], tags=tags)
        assert "images" in res
        assert "objects" in res
        assert "tags" in res
        assert res["images"]["unit"] == "image"
        assert res["objects"]["unit"] == "object"
        assert res["tags"]["unit"] == "tag"
        # No combined aggregate rate is invented
        assert "aggregate" not in res


# ═══════════════════════════════════════════════════════════════════════
# 7. DQ07 — Duplicate Record Rate Tests
# ═══════════════════════════════════════════════════════════════════════


class TestDQ07DuplicateRecordRate:
    """Tests for DQ07 Duplicate Record Rate."""

    def test_duplicate_by_image_key(self):
        """Duplicate rate by key = (total - unique) / total."""
        images = [
            _img("i1", dataset_id="ds1"),
            _img("i2", dataset_id="ds1"),
            _img("i2", dataset_id="ds1"),  # duplicate key ds1:i2
            _img("i3", dataset_id="ds1"),
        ]
        res = dq07_duplicate_record_rate(images, key="image_key", unit="image")
        assert res["metric_id"] == "DQ07"
        assert res["key"] == "image_key"
        assert res["unit"] == "image"
        assert res["status"] == "available"
        assert res["denominator"] == 4
        assert res["duplicate_count"] == 1
        assert res["unique_count"] == 3
        assert res["value"] == 0.25

    def test_duplicate_by_object_key(self):
        """Duplicate rate for objects."""
        objs = [
            _obj("o1", "i1"),
            _obj("o1", "i1"),  # duplicate
        ]
        res = dq07_duplicate_record_rate(objs, key="object_key", unit="object")
        assert res["key"] == "object_key"
        assert res["denominator"] == 2
        assert res["duplicate_count"] == 1
        assert res["value"] == 0.5

    def test_confirmed_duplicate_groups(self):
        """Duplicate groups from Coding Spec: only confirmed=True groups count."""
        images = [_img("i1"), _img("i2"), _img("i3"), _img("i4")]
        groups = [
            {"group_id": "g1", "image_keys": ["ds1:i1", "ds1:i2"], "confirmed": True},  # 1 redundant
            {"group_id": "g2", "image_keys": ["ds1:i3", "ds1:i4"], "confirmed": False},  # not confirmed
        ]
        res = dq07_duplicate_record_rate(images, duplicate_groups=groups, unit="image")
        assert res["key"] == "confirmed_duplicate_group"
        assert res["denominator"] == 4
        assert res["duplicate_count"] == 1  # only from g1
        assert res["value"] == 0.25

    def test_confirmed_duplicate_groups_flat_tabular_format(self):
        """Flat tabular duplicate groups format (image_key, group_id, confirmed) from Coding Spec §2."""
        images = [_img("i1"), _img("i2"), _img("i3"), _img("i4")]
        groups_flat = [
            {"image_key": "ds1:i1", "group_id": "g1", "confirmed": True},
            {"image_key": "ds1:i2", "group_id": "g1", "confirmed": True},
            {"image_key": "ds1:i3", "group_id": "g2", "confirmed": False},
            {"image_key": "ds1:i4", "group_id": "g2", "confirmed": False},
        ]
        res = dq07_duplicate_record_rate(images, duplicate_groups=groups_flat, unit="image")
        assert res["key"] == "confirmed_duplicate_group"
        assert res["denominator"] == 4
        assert res["duplicate_count"] == 1
        assert res["value"] == 0.25

    def test_zero_duplicates_boundary(self):
        """When all records have distinct keys, duplicate rate is exactly 0.0."""
        images = [_img("i1"), _img("i2"), _img("i3")]
        res = dq07_duplicate_record_rate(images, key="image_key", unit="image")
        assert res["denominator"] == 3
        assert res["duplicate_count"] == 0
        assert res["unique_count"] == 3
        assert res["value"] == 0.0

    def test_zero_denominator_returns_not_available(self):
        """Empty records list returns not_available, never 0%."""
        res = dq07_duplicate_record_rate([], key="image_key")
        assert res["status"] == "not_available"
        assert res["value"] is None
        assert res["denominator"] == 0


# ═══════════════════════════════════════════════════════════════════════
# 8. DQ08 — Audited Error Rate Tests
# ═══════════════════════════════════════════════════════════════════════


class TestDQ08AuditedErrorRate:
    """Tests for DQ08 Audited Error Rate."""

    def test_absent_review_log_not_available_no_fabrication(self):
        """When review log is absent (None or empty), returns not_available without fabricating."""
        res_none = dq08_audited_error_rate(None, unit="image")
        assert res_none["metric_id"] == "DQ08"
        assert res_none["unit"] == "image"
        assert res_none["status"] == "not_available"
        assert res_none["value"] is None
        assert res_none["denominator"] == 0
        assert "No review log available" in res_none["reason"]

        res_empty = dq08_audited_error_rate([], unit="object")
        assert res_empty["status"] == "not_available"
        assert res_empty["value"] is None

    def test_unknown_status_does_not_count_as_reviewed(self):
        """'unknown' status does NOT prove the unit has been reviewed."""
        log = [
            {"image_key": "i1", "review_status": "unknown"},
            {"image_key": "i2", "review_status": "unreviewed"},
        ]
        res = dq08_audited_error_rate(log, unit="image")
        assert res["status"] == "not_available"
        assert res["value"] is None
        assert res["reviewed_count"] == 0

    def test_reviewed_units_error_rate_calculation(self):
        """Calculates confirmed errors / reviewed units."""
        log = [
            {"image_key": "i1", "review_status": "verified", "has_error": False},
            {"image_key": "i2", "review_status": "error", "has_error": True},
            {"image_key": "i3", "review_status": "approved", "has_error": False},
            {"image_key": "i4", "review_status": "unknown"},  # not counted
        ]
        res = dq08_audited_error_rate(log, unit="image", reviewer="Alice", reference="v1.0")
        assert res["status"] == "available"
        assert res["reviewer"] == "Alice"
        assert res["reference"] == "v1.0"
        assert res["denominator"] == 3  # i1, i2, i3
        assert res["numerator"] == 1    # i2
        assert res["value"] == 1 / 3

    def test_object_unit_error_rate(self):
        """Supports separate object-level audited error rate."""
        log = [
            {"object_key": "o1", "review_status": "label_error"},
            {"object_key": "o2", "review_status": "verified"},
        ]
        res = dq08_audited_error_rate(log, unit="object")
        assert res["unit"] == "object"
        assert res["denominator"] == 2
        assert res["numerator"] == 1
        assert res["value"] == 0.5

@pytest.mark.parametrize("flat", [False, True])
def test_duplicate_groups_ignore_out_of_scope_members(flat):
    images = [_img("i1"), _img("i2")]
    members = ["other:1", "other:2", "other:3", "other:4"]
    groups = ([{"group_id": "g", "image_key": m, "confirmed": True} for m in members]
              if flat else [{"group_id": "g", "image_keys": members, "confirmed": True}])
    result = dq07_duplicate_record_rate(images, duplicate_groups=groups, unit="image")
    assert result["value"] == 0.0 and result["denominator"] == 2
    assert result["duplicate_count"] == 0 and result["unique_count"] == 2
    assert "outside measurement scope" in result["reason"]


@pytest.mark.parametrize("flat", [False, True])
def test_duplicate_group_repeated_members_count_once(flat):
    import copy
    images = [_img("i1"), _img("i2"), _img("i3")]
    members = ["ds1:i1", "ds1:i1", "ds1:i2", "ds1:i2", "outside:x"]
    groups = ([{"group_id": "g", "image_key": m, "confirmed": True} for m in members]
              if flat else [{"group_id": "g", "image_keys": members, "confirmed": True}])
    original = copy.deepcopy((images, groups))
    result = dq07_duplicate_record_rate(images, duplicate_groups=groups, unit="image")
    assert result["duplicate_count"] == 1 and result["unique_count"] == 2
    assert result["value"] == 1 / 3
    assert (images, groups) == original


@pytest.mark.parametrize("flat", [False, True])
def test_overlapping_duplicate_groups_unavailable(flat):
    images = [_img("i1"), _img("i2"), _img("i3")]
    groups = [{"group_id": "a", "image_keys": ["ds1:i1", "ds1:i2"], "confirmed": True},
              {"group_id": "b", "image_keys": ["ds1:i2", "ds1:i3"], "confirmed": True}]
    if flat:
        groups = [{"group_id": g["group_id"], "image_key": m, "confirmed": True}
                  for g in groups for m in g["image_keys"]]
    for ordered in (groups, list(reversed(groups))):
        result = dq07_duplicate_record_rate(images, duplicate_groups=ordered, unit="image")
        assert result["status"] == "not_available" and result["value"] is None
        assert result["duplicate_count"] is None and result["unique_count"] is None
        assert "Overlapping" in result["reason"]


def test_overlap_only_outside_scope_does_not_block_measurement():
    result = dq07_duplicate_record_rate([_img("i1"), _img("i2")], duplicate_groups=[
        {"group_id": "a", "image_keys": ["ds1:i1", "outside:x"], "confirmed": True},
        {"group_id": "b", "image_keys": ["ds1:i2", "outside:x"], "confirmed": True}])
    assert result["status"] == "available" and result["value"] == 0.0


@pytest.mark.parametrize("group", [None, {"confirmed": True, "image_keys": "ds1:i1"}, {"confirmed": True, "image_keys": [None]}])
def test_malformed_confirmed_group_is_unavailable(group):
    result = dq07_duplicate_record_rate([_img("i1")], duplicate_groups=[group])
    assert result["status"] == "not_available" and result["value"] is None
    assert result["reason"]


def test_audit_mixed_units_are_measured_separately():
    import copy
    log = [{"image_key": "ds:i1", "review_status": "verified"},
           {"image_key": "ds:i1", "object_key": "ds:o1", "review_status": "label_error"}]
    original = copy.deepcopy(log)
    image = dq08_audited_error_rate(log, unit="image")
    obj = dq08_audited_error_rate(log, unit="object")
    assert image["reviewed_count"] == 1 and image["error_count"] == 0 and image["value"] == 0.0
    assert obj["reviewed_count"] == 1 and obj["error_count"] == 1 and obj["value"] == 1.0
    assert log == original


@pytest.mark.parametrize("status", ["typo", "unknown", "pending", "unreviewed", "", None])
def test_invalid_audit_status_never_creates_measured_zero(status):
    result = dq08_audited_error_rate([{"image_key": "i1", "review_status": status, "has_error": True}])
    assert result["status"] == "not_available" and result["value"] is None
    assert result["denominator"] == result["reviewed_count"] == 0
    assert result["reason"]


@pytest.mark.parametrize("unit,key", [("image", "image_key"), ("object", "object_key")])
def test_audit_unique_units_and_repeated_confirmed_errors(unit, key):
    log = [{key: "a", "review_status": "verified"}, {key: "a", "review_status": "approved"},
           {key: "b", "review_status": "error"}, {key: "b", "review_status": "label_error"},
           {key: "c", "review_status": "typo"}]
    for ordered in (log, list(reversed(log))):
        result = dq08_audited_error_rate(ordered, unit=unit, reviewer="Reviewer", reference="v1")
        assert result["denominator"] == result["reviewed_count"] == 2
        assert result["numerator"] == result["error_count"] == 1
        assert result["value"] == 0.5 and result["status"] == "available"
        assert result["reviewer"] == "Reviewer" and result["reference"] == "v1"


def test_audit_missing_unit_identity_is_unavailable():
    result = dq08_audited_error_rate([{"review_status": "verified"}])
    assert result["status"] == "not_available" and result["value"] is None


@pytest.mark.parametrize("unit,key", [("image", "image_key"), ("object", "object_key")])
@pytest.mark.parametrize("remaining", [False, True])
def test_contradictory_audit_units_excluded_from_denominator(unit, key, remaining):
    import copy
    log = [{key: "conflict", "review_status": "verified"},
           {key: "conflict", "review_status": "error"},
           {key: "conflict", "review_status": "approved"}]
    if remaining:
        log += [{key: "clean", "review_status": "verified"},
                {key: "error", "review_status": "rejected"}]
    original = copy.deepcopy(log)
    for ordered in (log, list(reversed(log))):
        result = dq08_audited_error_rate(ordered, unit=unit)
        assert result["unresolved_count"] == 1
        assert "contradictory valid clean/error" in result["reason"]
        assert result["denominator"] == (2 if remaining else 0)
        assert result["numerator"] == (1 if remaining else 0)
        assert result["value"] == (0.5 if remaining else None)
        assert result["status"] == ("available" if remaining else "not_available")
        if not remaining:
            assert "denominator=0" in result["reason"]
    assert log == original


def test_invalid_review_does_not_contradict_valid_review():
    result = dq08_audited_error_rate([
        {"image_key": "i1", "review_status": "verified"},
        {"image_key": "i1", "review_status": "typo", "has_error": True}])
    assert result["value"] == 0.0 and result["denominator"] == 1
    assert result["unresolved_count"] == 0
    assert "invalid status" in result["reason"]


def test_confirmed_error_flag_preserves_legitimate_audit_behavior():
    result = dq08_audited_error_rate([
        {"object_key": "o1", "review_status": "verified", "confirmed_error": True},
        {"object_key": "o1", "review_status": "label_error"}], unit="object")
    assert result["value"] == 1.0 and result["denominator"] == 1


def test_object_reviews_cannot_be_relabelled_as_image_reviews():
    log = [{"unit": "image", "image_key": "i1", "object_key": "o1",
            "review_status": "verified"}]
    for unit in ("image", "object"):
        result = dq08_audited_error_rate(log, unit=unit)
        assert result["value"] is None and result["denominator"] == 0


def test_unsupported_audit_unit_is_unavailable():
    result = dq08_audited_error_rate([
        {"image_key": "i1", "review_status": "verified"}], unit="annotation")
    assert result["value"] is None and "Unsupported audit unit" in result["reason"]
