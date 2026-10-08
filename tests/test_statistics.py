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
