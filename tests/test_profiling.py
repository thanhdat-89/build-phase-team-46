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
    dataset_summary,
    dp01_inventory,
    dp02_class_instance_share,
    dp03_class_image_prevalence,
    class_distribution,
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


if __name__ == "__main__":
    unittest.main()
