"""Unit tests for Sprint 2A Data Profiling: DP01, DP02, DP03.

Tests cover:
- DP01 Inventory (N, M_valid, classes, annotated_image_count, unannotated_image_count)
- DP02 Class Instance Share (M_valid denominator, exclusion of invalid objects, M_valid=0)
- DP03 Class Image Prevalence (unique images numerator, N denominator, N=0, ratio sum > 100%)
"""

from __future__ import annotations

import unittest

from core.schema import ImageRecord, ObjectRecord
from core.statistics import (
    calculate_bbox_area_ratio,
    class_distribution,
    dataset_summary,
    dp01_inventory,
    dp02_class_instance_share,
    dp03_class_image_prevalence,
    dp05_relative_bbox_area,
    dp06_occlusion_rate,
    dp07_attribute_availability,
)


# ── Helpers ─────────────────────────────────────────────────────────────

def _make_img(image_id: str, dataset_id: str = "ds1") -> ImageRecord:
    return ImageRecord(
        dataset_id=dataset_id,
        image_id=image_id,
        image_path=f"{image_id}.jpg",
        width=640,
        height=480,
    )


def _make_obj(object_id: str, image_id: str, class_name: str) -> ObjectRecord:
    return ObjectRecord(
        object_id=object_id,
        image_id=image_id,
        class_name=class_name,
        x_min=10.0,
        y_min=10.0,
        x_max=50.0,
        y_max=50.0,
    )


# ═══════════════════════════════════════════════════════════════════════
# 1. DP01 — Inventory Tests (Requirements 1 - 5)
# ═══════════════════════════════════════════════════════════════════════

class TestDP01Inventory(unittest.TestCase):
    """Test suite for DP01 Inventory metric."""

    def test_01_normal_dataset(self):
        """1. Normal dataset with annotated and unannotated images."""
        images = [_make_img("img1"), _make_img("img2"), _make_img("img3")]
        objects = [
            _make_obj("obj1", "img1", "car"),
            _make_obj("obj2", "img1", "car"),
            _make_obj("obj3", "img1", "person"),
            _make_obj("obj4", "img2", "car"),
        ]
        inv = dp01_inventory(images, objects)

        self.assertEqual(inv["total_images"], 3)
        self.assertEqual(inv["total_objects"], 4)
        self.assertEqual(inv["total_classes"], 2)
        self.assertEqual(inv["annotated_image_count"], 2)
        self.assertEqual(inv["unannotated_image_count"], 1)
        # Verify backward-compatible alias keys
        self.assertEqual(inv["annotated_images"], 2)
        self.assertEqual(inv["unannotated_images"], 1)

    def test_02_images_without_annotations(self):
        """2. Images without annotations remain in N and are not lost."""
        images = [_make_img(f"img{i}") for i in range(5)]
        objects = [
            _make_obj("obj1", "img0", "car"),
            _make_obj("obj2", "img1", "bus"),
        ]
        inv = dp01_inventory(images, objects)

        self.assertEqual(inv["total_images"], 5)
        self.assertEqual(inv["total_objects"], 2)
        self.assertEqual(inv["annotated_image_count"], 2)
        self.assertEqual(inv["unannotated_image_count"], 3)

    def test_03_invalid_objects_excluded_from_m_valid(self):
        """3. Invalid bbox records must not contribute to profiling object metrics."""
        images = [_make_img("img1")]
        # Suppose parser found 4 objects (2 valid, 2 invalid). DP01 receives valid_objects (M_valid).
        valid_objects = [
            _make_obj("valid_1", "img1", "car"),
            _make_obj("valid_2", "img1", "person"),
        ]
        inv = dp01_inventory(images, valid_objects)

        self.assertEqual(inv["total_objects"], 2)
        self.assertEqual(inv["total_classes"], 2)

    def test_04_empty_dataset(self):
        """4. Empty dataset returns zeros for all counts."""
        inv = dp01_inventory([], [])
        self.assertEqual(inv["total_images"], 0)
        self.assertEqual(inv["total_objects"], 0)
        self.assertEqual(inv["total_classes"], 0)
        self.assertEqual(inv["annotated_image_count"], 0)
        self.assertEqual(inv["unannotated_image_count"], 0)

    def test_05_deterministic_output(self):
        """5. Inventory output is deterministic across multiple calls."""
        images = [_make_img("img1"), _make_img("img2")]
        objects = [_make_obj("obj1", "img1", "car")]
        inv1 = dp01_inventory(images, objects)
        inv2 = dp01_inventory(images, objects)
        self.assertEqual(inv1, inv2)

    def test_05b_dataset_summary_backward_compatibility(self):
        """Verify dataset_summary keeps exact legacy keys while dp01_inventory provides DP01 keys."""
        images = [_make_img("img1"), _make_img("img2")]
        objects = [_make_obj("obj1", "img1", "car")]
        summary = dataset_summary(images, objects)
        self.assertEqual(summary["total_images"], 2)
        self.assertEqual(summary["total_objects"], 1)
        self.assertEqual(summary["annotated_images"], 1)
        self.assertEqual(summary["unannotated_images"], 1)

        inv = dp01_inventory(images, objects)
        self.assertEqual(inv["annotated_image_count"], 1)
        self.assertEqual(inv["unannotated_image_count"], 1)
        self.assertEqual(inv["annotated_images"], 1)
        self.assertEqual(inv["unannotated_images"], 1)


# ═══════════════════════════════════════════════════════════════════════
# 2. DP02 — Class Instance Share Tests (Requirements 6 - 10)
# ═══════════════════════════════════════════════════════════════════════

class TestDP02ClassInstanceShare(unittest.TestCase):
    """Test suite for DP02 Class Instance Share metric."""

    def test_06_multiple_classes(self):
        """6. Multiple classes calculate correct object counts and ratios."""
        objects = (
            [_make_obj(f"c{i}", "i1", "car") for i in range(6)]
            + [_make_obj(f"p{i}", "i1", "person") for i in range(3)]
            + [_make_obj("b0", "i1", "bike")]
        )
        # M_valid = 10
        res = dp02_class_instance_share(objects)
        by_class = {r["class_name"]: r for r in res}

        self.assertEqual(by_class["car"]["class_object_count"], 6)
        self.assertAlmostEqual(by_class["car"]["class_object_ratio"], 0.6)
        self.assertEqual(by_class["car"]["status"], "available")
        self.assertAlmostEqual(by_class["car"]["percentage"], 60.0)

        self.assertEqual(by_class["person"]["class_object_count"], 3)
        self.assertAlmostEqual(by_class["person"]["class_object_ratio"], 0.3)

        self.assertEqual(by_class["bike"]["class_object_count"], 1)
        self.assertAlmostEqual(by_class["bike"]["class_object_ratio"], 0.1)

        total_ratio = sum(r["class_object_ratio"] for r in res)
        self.assertAlmostEqual(total_ratio, 1.0)

    def test_07_class_ratio_uses_m_valid_denominator(self):
        """7. Denominator MUST be M_valid (valid objects), not total parsed M."""
        # Suppose M_total was 12, but M_valid = 10 (2 invalid excluded)
        valid_objects = (
            [_make_obj(f"c{i}", "i1", "car") for i in range(5)]
            + [_make_obj(f"b{i}", "i1", "bus") for i in range(5)]
        )
        res = dp02_class_instance_share(valid_objects)
        by_class = {r["class_name"]: r for r in res}
        # Ratio is 5 / 10 = 0.5 (not 5 / 12)
        self.assertEqual(by_class["car"]["class_object_ratio"], 0.5)

    def test_08_invalid_objects_excluded(self):
        """8. Invalid objects are not part of valid_objects and do not distort ratios."""
        valid_objects = [_make_obj("c1", "i1", "car")]
        res = dp02_class_instance_share(valid_objects)
        classes_present = {r["class_name"] for r in res}
        self.assertNotIn("ghost_invalid_class", classes_present)
        self.assertEqual(res[0]["class_object_ratio"], 1.0)

    def test_09_m_valid_zero(self):
        """9. When M_valid == 0, value = null and status = not_available, NOT 0%."""
        res_empty = dp02_class_instance_share([])
        self.assertEqual(res_empty, [])

        # When explicitly querying a class with M_valid == 0
        res_queried = dp02_class_instance_share([], classes=["car"])
        self.assertEqual(len(res_queried), 1)
        self.assertEqual(res_queried[0]["class_name"], "car")
        self.assertEqual(res_queried[0]["class_object_count"], 0)
        self.assertIsNone(res_queried[0]["class_object_ratio"])
        self.assertIsNone(res_queried[0]["percentage"])
        self.assertEqual(res_queried[0]["status"], "not_available")

    def test_10_multiple_objects_same_class(self):
        """10. Multiple objects of the same class are all counted."""
        objects = [_make_obj(f"c{i}", "i1", "car") for i in range(7)]
        res = dp02_class_instance_share(objects)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["class_object_count"], 7)
        self.assertEqual(res[0]["class_object_ratio"], 1.0)


# ═══════════════════════════════════════════════════════════════════════
# 3. DP03 — Class Image Prevalence Tests (Requirements 11 - 15)
# ═══════════════════════════════════════════════════════════════════════

class TestDP03ClassImagePrevalence(unittest.TestCase):
    """Test suite for DP03 Class Image Prevalence metric."""

    def test_11_multiple_objects_same_class_in_one_image(self):
        """11. Multiple objects of the same class in one image count as ONE image."""
        images = [_make_img("i1")]
        # 5 cars in image 1
        objects = [_make_obj(f"c{i}", "i1", "car") for i in range(5)]
        res = dp03_class_image_prevalence(images, objects)

        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["class_name"], "car")
        self.assertEqual(res[0]["class_image_count"], 1)
        self.assertEqual(res[0]["class_image_ratio"], 1.0)
        self.assertEqual(res[0]["status"], "available")

    def test_12_class_appearing_in_multiple_images(self):
        """12. Class appearing in multiple unique images increments count per unique image."""
        images = [_make_img("i1"), _make_img("i2"), _make_img("i3"), _make_img("i4")]
        objects = [
            _make_obj("c1", "i1", "car"),
            _make_obj("c2", "i2", "car"),
            _make_obj("c3", "i3", "car"),
        ]
        res = dp03_class_image_prevalence(images, objects)
        by_class = {r["class_name"]: r for r in res}

        self.assertEqual(by_class["car"]["class_image_count"], 3)
        self.assertAlmostEqual(by_class["car"]["class_image_ratio"], 0.75)  # 3 / 4

    def test_13_multiple_classes_in_same_image_ratios_can_sum_gt_100(self):
        """13. Multiple classes in same image both count the image; ratios can sum to > 100%."""
        images = [_make_img("i1")]
        objects = [
            _make_obj("c1", "i1", "car"),
            _make_obj("p1", "i1", "person"),
        ]
        res = dp03_class_image_prevalence(images, objects)
        by_class = {r["class_name"]: r for r in res}

        self.assertEqual(by_class["car"]["class_image_count"], 1)
        self.assertEqual(by_class["car"]["class_image_ratio"], 1.0)
        self.assertEqual(by_class["person"]["class_image_count"], 1)
        self.assertEqual(by_class["person"]["class_image_ratio"], 1.0)

        # Sum of prevalence ratios across classes = 2.0 (200%), which is legitimately > 100%
        sum_ratios = sum(r["class_image_ratio"] for r in res)
        self.assertEqual(sum_ratios, 2.0)

    def test_14_n_zero(self):
        """14. When N == 0, value = null and status = not_available, NOT 0%."""
        objects = [_make_obj("c1", "i1", "car")]
        res = dp03_class_image_prevalence([], objects)

        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["class_name"], "car")
        self.assertIsNone(res[0]["class_image_ratio"])
        self.assertIsNone(res[0]["percentage"])
        self.assertEqual(res[0]["status"], "not_available")

    def test_15_images_without_annotations_remain_in_denominator(self):
        """15. Images without annotations remain in denominator N."""
        # 10 images total, car is in only 2 images
        images = [_make_img(f"img_{i}") for i in range(10)]
        objects = [
            _make_obj("c1", "img_0", "car"),
            _make_obj("c2", "img_1", "car"),
        ]
        res = dp03_class_image_prevalence(images, objects)
        by_class = {r["class_name"]: r for r in res}

        self.assertEqual(by_class["car"]["class_image_count"], 2)
        # Denominator is N = 10, NOT annotated_image_count (2)
        self.assertEqual(by_class["car"]["class_image_ratio"], 0.2)
        self.assertEqual(by_class["car"]["percentage"], 20.0)


# ═══════════════════════════════════════════════════════════════════════
# 4. Backward Compatibility of class_distribution
# ═══════════════════════════════════════════════════════════════════════

class TestClassDistributionEnriched(unittest.TestCase):
    """Verify class_distribution remains backward compatible while enriched."""

    def test_class_distribution_legacy_and_new_keys(self):
        images = [_make_img("i1"), _make_img("i2")]
        objects = [
            _make_obj("o1", "i1", "car"),
            _make_obj("o2", "i1", "car"),
            _make_obj("o3", "i2", "person"),
        ]
        res = class_distribution(objects, images=images)
        car = next(r for r in res if r["class_name"] == "car")

        # Legacy keys
        self.assertEqual(car["object_count"], 2)
        self.assertEqual(car["image_count"], 1)
        self.assertAlmostEqual(car["percentage"], 66.666666, places=4)

        # Enriched DP02 and DP03 keys
        self.assertEqual(car["class_object_count"], 2)
        self.assertAlmostEqual(car["class_object_ratio"], 2 / 3)
        self.assertEqual(car["class_image_count"], 1)
        self.assertEqual(car["class_image_ratio"], 1 / 2)

    def test_class_distribution_with_mixed_valid_and_invalid_same_class(self):
        """CHECK 1: class_distribution must NOT treat invalid objects as valid profiling objects."""
        img1 = _make_img("img1")
        img2 = _make_img("img2")
        images = [img1, img2]

        valid_car = _make_obj("v_car", "img1", "car")
        # Invalid bbox: reversed x (x_min=100, x_max=10) on img2
        invalid_car = ObjectRecord(
            object_id="inv_car",
            image_id="img2",
            class_name="car",
            x_min=100.0,
            y_min=10.0,
            x_max=10.0,
            y_max=50.0,
        )
        objects = [valid_car, invalid_car]

        # Case A: resolving valid objects via images
        res = class_distribution(objects, images=images)
        self.assertEqual(len(res), 1)
        car = res[0]
        # Legacy fields reflect all M = 2 objects
        self.assertEqual(car["object_count"], 2)
        self.assertEqual(car["image_count"], 2)
        self.assertAlmostEqual(car["percentage"], 100.0)
        # DP02 fields MUST use valid objects only (M_valid = 1)
        self.assertEqual(car["class_object_count"], 1)
        self.assertAlmostEqual(car["class_object_ratio"], 1.0)
        # DP03 fields MUST reflect only valid object presence (only img1 has valid car)
        self.assertEqual(car["class_image_count"], 1)
        self.assertAlmostEqual(car["class_image_ratio"], 0.5)  # 1 / 2 images

        # Case B: passing valid_objects explicitly
        res_explicit = class_distribution(
            objects, images=images, valid_objects=[valid_car]
        )
        car_exp = res_explicit[0]
        self.assertEqual(car_exp["class_object_count"], 1)
        self.assertAlmostEqual(car_exp["class_object_ratio"], 1.0)
        self.assertEqual(car_exp["class_image_count"], 1)
        self.assertAlmostEqual(car_exp["class_image_ratio"], 0.5)


# ═══════════════════════════════════════════════════════════════════════
# 4. DP05 — Relative BBox Area Tests
# ═══════════════════════════════════════════════════════════════════════

class TestDP05RelativeBBoxArea(unittest.TestCase):
    """Test suite for DP05 Relative BBox Area metric."""

    def test_01_single_box_area_ratio_calculation(self):
        """calculate_bbox_area_ratio computes exact geometric ratio on valid input."""
        # 32x24 bbox on 640x480 image: (32*24) / (640*480) = 768 / 307200 = 0.0025
        obj = ObjectRecord("o1", "i1", "car", 10.0, 10.0, 42.0, 34.0)
        ratio = calculate_bbox_area_ratio(obj, 640, 480)
        self.assertIsNotNone(ratio)
        self.assertAlmostEqual(ratio, 0.0025)

    def test_02_invalid_geometry_excluded(self):
        """Invalid geometry returns None and is excluded from area statistics."""
        # Reversed x
        rev_obj = ObjectRecord("o1", "i1", "car", 50.0, 10.0, 10.0, 30.0)
        self.assertIsNone(calculate_bbox_area_ratio(rev_obj, 640, 480))

        # Out of bounds
        oob_obj = ObjectRecord("o2", "i1", "car", -5.0, 10.0, 20.0, 30.0)
        self.assertIsNone(calculate_bbox_area_ratio(oob_obj, 640, 480))

        # Zero width
        zw_obj = ObjectRecord("o3", "i1", "car", 10.0, 10.0, 10.0, 30.0)
        self.assertIsNone(calculate_bbox_area_ratio(zw_obj, 640, 480))

    def test_03_invalid_image_dimensions_excluded(self):
        """Images with non-positive dimensions (w<=0 or h<=0) return None."""
        obj = ObjectRecord("o1", "i1", "car", 10.0, 10.0, 50.0, 50.0)
        self.assertIsNone(calculate_bbox_area_ratio(obj, 0, 480))
        self.assertIsNone(calculate_bbox_area_ratio(obj, 640, -10))

    def test_04_dataset_level_dp05_statistics(self):
        """dp05_relative_bbox_area calculates correct mean and descriptive statistics."""
        img1 = ImageRecord("ds1", "i1", "1.jpg", 100, 100)
        img2 = ImageRecord("ds1", "i2", "2.jpg", 100, 100)
        # Box 1: 10x10 -> area = 100 / 10000 = 0.01
        # Box 2: 20x20 -> area = 400 / 10000 = 0.04
        # Box 3: invalid geometry -> excluded
        objs = [
            ObjectRecord("o1", "i1", "car", 0.0, 0.0, 10.0, 10.0),
            ObjectRecord("o2", "i2", "car", 0.0, 0.0, 20.0, 20.0),
            ObjectRecord("o3", "i1", "car", 50.0, 0.0, 10.0, 10.0),  # reversed x
        ]
        res = dp05_relative_bbox_area([img1, img2], objs)
        self.assertEqual(res["status"], "available")
        self.assertEqual(res["denominator"], 2)
        self.assertEqual(res["excluded_count"], 1)
        self.assertAlmostEqual(res["value"], 0.025)  # (0.01 + 0.04) / 2
        self.assertIsNotNone(res["summary"])
        self.assertAlmostEqual(res["summary"]["min"], 0.01)
        self.assertAlmostEqual(res["summary"]["max"], 0.04)
        self.assertAlmostEqual(res["summary"]["mean"], 0.025)

    def test_05_zero_denominator_returns_not_available(self):
        """When M_valid == 0, DP05 returns not_available, never an invented 0%."""
        res_empty = dp05_relative_bbox_area([], [])
        self.assertEqual(res_empty["status"], "not_available")
        self.assertIsNone(res_empty["value"])
        self.assertEqual(res_empty["denominator"], 0)

        # Only invalid objects
        img = ImageRecord("ds1", "i1", "1.jpg", 100, 100)
        invalid_obj = ObjectRecord("o1", "i1", "car", 50.0, 0.0, 10.0, 10.0)
        res_inv = dp05_relative_bbox_area([img], [invalid_obj])
        self.assertEqual(res_inv["status"], "not_available")
        self.assertIsNone(res_inv["value"])
        self.assertEqual(res_inv["excluded_count"], 1)

    def test_06_small_bbox_semantics_distance_fallacy_guarded(self):
        """Small bbox area is treated purely as 2D image-space geometric size."""
        img = ImageRecord("ds1", "i1", "1.jpg", 1000, 1000)
        # Small 2x2 bbox: area_ratio = 4 / 1000000 = 0.000004
        small_obj = ObjectRecord("o1", "i1", "screw", 10.0, 10.0, 12.0, 12.0)
        res = dp05_relative_bbox_area([img], [small_obj])
        self.assertEqual(res["status"], "available")
        self.assertEqual(res["unit"], "object")
        self.assertAlmostEqual(res["value"], 0.000004)


# ═══════════════════════════════════════════════════════════════════════
# 5. DP06 — Occlusion Rate Tests
# ═══════════════════════════════════════════════════════════════════════

class TestDP06OcclusionRate(unittest.TestCase):
    """Test suite for DP06 Occlusion Rate metric."""

    def test_01_normal_dataset_occlusion_rate(self):
        """Formula: count(occluded=True) / count(valid occluded values)."""
        objs = [
            ObjectRecord("o1", "i1", "car", 0, 0, 10, 10, occluded=True),
            ObjectRecord("o2", "i1", "car", 0, 0, 10, 10, occluded=False),
            ObjectRecord("o3", "i1", "pedestrian", 0, 0, 10, 10, occluded=True),
            ObjectRecord("o4", "i1", "pedestrian", 0, 0, 10, 10, occluded=False),
        ]
        res = dp06_occlusion_rate(objs)
        self.assertEqual(res["status"], "available")
        self.assertEqual(res["numerator"], 2)
        self.assertEqual(res["denominator"], 4)
        self.assertAlmostEqual(res["value"], 0.5)
        self.assertAlmostEqual(res["percentage"], 50.0)

    def test_02_per_class_breakdown(self):
        """DP06 provides breakdown by class as defined in DP06(c)."""
        objs = [
            ObjectRecord("o1", "i1", "car", 0, 0, 10, 10, occluded=True),
            ObjectRecord("o2", "i1", "car", 0, 0, 10, 10, occluded=True),
            ObjectRecord("o3", "i1", "pedestrian", 0, 0, 10, 10, occluded=False),
        ]
        res = dp06_occlusion_rate(objs)
        by_class = {c["class_name"]: c for c in res["by_class"]}
        self.assertAlmostEqual(by_class["car"]["value"], 1.0)
        self.assertAlmostEqual(by_class["pedestrian"]["value"], 0.0)

        # Filtering to specific class
        res_car = dp06_occlusion_rate(objs, class_name="car")
        self.assertEqual(res_car["scope"], "class")
        self.assertEqual(res_car["class_name"], "car")
        self.assertAlmostEqual(res_car["value"], 1.0)

    def test_03_zero_denominator_returns_not_available(self):
        """Zero objects with valid occluded values returns not_available, never 0%."""
        res = dp06_occlusion_rate([])
        self.assertEqual(res["status"], "not_available")
        self.assertIsNone(res["value"])
        self.assertEqual(res["denominator"], 0)


# ═══════════════════════════════════════════════════════════════════════
# 6. DP07 — Attribute Availability Tests
# ═══════════════════════════════════════════════════════════════════════

class TestDP07AttributeAvailability(unittest.TestCase):
    """Test suite for DP07 Attribute Availability metric."""

    def test_01_attribute_availability_exact_unit_and_denominator(self):
        """Unit is 'object', denominator is objects in scope."""
        objs = [
            ObjectRecord("o1", "i1", "car", 0, 0, 10, 10, attributes={"color": "red"}),
            ObjectRecord("o2", "i1", "car", 0, 0, 10, 10, attributes={"color": "blue"}),
            ObjectRecord("o3", "i1", "car", 0, 0, 10, 10, attributes={}),
            ObjectRecord("o4", "i1", "car", 0, 0, 10, 10, attributes={"color": ""}),
        ]
        res = dp07_attribute_availability(objs)
        self.assertEqual(res["unit"], "object")
        self.assertEqual(res["status"], "available")
        self.assertEqual(res["denominator"], 4)
        self.assertEqual(res["numerator"], 2)  # o1 and o2 have non-empty attributes
        self.assertAlmostEqual(res["value"], 0.5)

    def test_02_specific_attribute_availability(self):
        """When attribute_name is specified, only that attribute is evaluated."""
        objs = [
            ObjectRecord("o1", "i1", "car", 0, 0, 10, 10, attributes={"color": "red"}),
            ObjectRecord("o2", "i1", "car", 0, 0, 10, 10, attributes={"pose": "standing"}),
        ]
        res_color = dp07_attribute_availability(objs, attribute_name="color")
        self.assertEqual(res_color["numerator"], 1)
        self.assertEqual(res_color["denominator"], 2)
        self.assertAlmostEqual(res_color["value"], 0.5)

    def test_03_zero_denominator_returns_not_available(self):
        """Zero objects in scope returns not_available, never 0%."""
        res = dp07_attribute_availability([])
        self.assertEqual(res["unit"], "object")
        self.assertEqual(res["status"], "not_available")
        self.assertIsNone(res["value"])
        self.assertEqual(res["denominator"], 0)


if __name__ == "__main__":
    unittest.main()
