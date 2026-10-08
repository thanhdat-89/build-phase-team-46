"""Regression tests for Phase B foundational corrections.

Covers the 10 specific audit failure cases and core constraints from:
1. Co_so_ly_thuyet_Data_Quality_Coverage_N2-05B.md
2. Coverage_Recommendation_Engine_Coding_Spec_N2-05B.md
"""

from __future__ import annotations

import unittest
from core.schema import ImageRecord, ObjectRecord
from core.validation import (
    MetadataState,
    validate_bbox,
    validate_scene_tags,
)
from core.statistics import (
    class_distribution,
    dp01_inventory,
    dp02_class_instance_share,
    dp03_class_image_prevalence,
    dp04_attribute_distribution,
    dq02_metadata_missing_rate,
    dq03_unknown_metadata_rate,
    dq04_invalid_metadata_rate,
    dq05_known_metadata_rate,
    dq06_invalid_bbox_rate,
    dq09_scene_tag_conflict_rate,
)


class TestPhaseBRegression(unittest.TestCase):
    """Test suite verifying all 10 Phase B requirements."""

    def test_01_two_datasets_same_image_id_remain_distinct(self):
        """Case 1: Two datasets contain the same image_id; their images must remain distinct."""
        img_ds1 = ImageRecord(
            dataset_id="batch_A",
            image_id="frame_001",
            image_path="A/001.jpg",
            width=640,
            height=480,
        )
        img_ds2 = ImageRecord(
            dataset_id="batch_B",
            image_id="frame_001",
            image_path="B/001.jpg",
            width=640,
            height=480,
        )
        images = [img_ds1, img_ds2]

        # batch_A has a car; batch_B has no objects
        obj_ds1 = ObjectRecord(
            object_id="obj_1",
            image_id="frame_001",
            class_name="car",
            x_min=10.0,
            y_min=10.0,
            x_max=50.0,
            y_max=50.0,
            dataset_id="batch_A",
        )

        inv = dp01_inventory(images, [obj_ds1])
        self.assertEqual(inv["total_images"], 2)
        self.assertEqual(inv["annotated_image_count"], 1)
        self.assertEqual(inv["unannotated_image_count"], 1)

        # Class image prevalence must be 1 / 2 = 0.5
        prev = dp03_class_image_prevalence(images, [obj_ds1])
        car_prev = next(r for r in prev if r["class_name"] == "car")
        self.assertEqual(car_prev["class_image_count"], 1)
        self.assertEqual(car_prev["class_image_ratio"], 0.5)

        # If both datasets have a car on frame_001, prevalence must be 2 / 2 = 1.0
        obj_ds2 = ObjectRecord(
            object_id="obj_1",
            image_id="frame_001",
            class_name="car",
            x_min=10.0,
            y_min=10.0,
            x_max=50.0,
            y_max=50.0,
            dataset_id="batch_B",
        )
        prev2 = dp03_class_image_prevalence(images, [obj_ds1, obj_ds2])
        car_prev2 = next(r for r in prev2 if r["class_name"] == "car")
        self.assertEqual(car_prev2["class_image_count"], 2)
        self.assertEqual(car_prev2["class_image_ratio"], 1.0)

    def test_02_images_without_bounding_boxes_remain_in_inventory(self):
        """Case 2: Images without bounding boxes remain in the image inventory."""
        images = [
            ImageRecord("ds", f"img_{i}", f"{i}.jpg", 640, 480)
            for i in range(5)
        ]
        # Only img_0 and img_1 have annotations
        valid_objects = [
            ObjectRecord("o1", "img_0", "car", 10, 10, 50, 50, dataset_id="ds"),
            ObjectRecord("o2", "img_1", "pedestrian", 10, 10, 50, 50, dataset_id="ds"),
        ]

        inv = dp01_inventory(images, valid_objects)
        self.assertEqual(inv["total_images"], 5)
        self.assertEqual(inv["total_valid_objects"], 2)
        self.assertEqual(inv["annotated_image_count"], 2)
        self.assertEqual(inv["unannotated_image_count"], 3)

    def test_03_multi_rule_violating_box_counted_once(self):
        """Case 3: One bounding box violates multiple validation rules but contributes only once to invalid count."""
        # Box with reversed x, zero height, and out-of-bounds coordinates
        box = ObjectRecord(
            object_id="bad_box",
            image_id="img_1",
            class_name="car",
            x_min=700.0,
            y_min=50.0,
            x_max=600.0,
            y_max=50.0,
            dataset_id="ds",
        )
        v_res = validate_bbox(box, image_width=640, image_height=480)
        self.assertFalse(v_res.valid)
        self.assertGreater(len(v_res.reasons), 1)

        # DQ06 calculation: 1 valid box, 1 multi-violating box -> 1 / 2 = 0.5
        valid_box = ObjectRecord("good_box", "img_1", "car", 10, 10, 50, 50, dataset_id="ds")
        all_objects = [valid_box, box]
        invalid_objects = [box]

        dq06 = dq06_invalid_bbox_rate(all_objects, invalid_objects)
        self.assertEqual(dq06["numerator"], 1)
        self.assertEqual(dq06["denominator"], 2)
        self.assertEqual(dq06["value"], 0.5)
        self.assertEqual(dq06["status"], "available")

    def test_04_metadata_states_remain_distinguishable(self):
        """Case 4: known, unknown, missing, and invalid metadata states remain distinguishable and sum to 100%."""
        images = [
            ImageRecord("ds", "img_1", "1.jpg", 640, 480, timeofday="day"),        # known
            ImageRecord("ds", "img_2", "2.jpg", 640, 480, timeofday="unknown"),    # unknown
            ImageRecord("ds", "img_3", "3.jpg", 640, 480, timeofday=None),         # missing
            ImageRecord("ds", "img_4", "4.jpg", 640, 480, timeofday="midnight"),   # invalid (outside taxonomy)
        ]

        dq02 = dq02_metadata_missing_rate(images, "timeofday")
        dq03 = dq03_unknown_metadata_rate(images, "timeofday")
        dq04 = dq04_invalid_metadata_rate(images, "timeofday")
        dq05 = dq05_known_metadata_rate(images, "timeofday")

        self.assertEqual(dq02["value"], 0.25)
        self.assertEqual(dq03["value"], 0.25)
        self.assertEqual(dq04["value"], 0.25)
        self.assertEqual(dq05["value"], 0.25)

        # The 4 mutually exclusive states must sum to 100%
        total_rate = dq02["value"] + dq03["value"] + dq04["value"] + dq05["value"]
        self.assertAlmostEqual(total_rate, 1.0)

        # DP04 Attribute distribution breakdown
        dp04 = dp04_attribute_distribution(images, "timeofday")
        self.assertEqual(dp04["state_counts"]["known"], 1)
        self.assertEqual(dp04["state_counts"]["unknown"], 1)
        self.assertEqual(dp04["state_counts"]["missing"], 1)
        self.assertEqual(dp04["state_counts"]["invalid"], 1)

    def test_05_scene_tag_conflicts_explicitly_represented(self):
        """Case 5: Scene-tag conflicts are explicitly represented and not silently resolved."""
        tags = [
            {"timeofday": "day", "weather": "clear"},
            {"timeofday": "night", "weather": "clear"},
        ]
        scene_res = validate_scene_tags(tags)
        self.assertTrue(scene_res.has_conflict)
        self.assertIn("timeofday", scene_res.conflicting_fields)
        self.assertIsNone(scene_res.timeofday)  # Never silently picks day or night
        self.assertEqual(scene_res.weather, "clear")

        img = ImageRecord(
            dataset_id="ds",
            image_id="img_1",
            image_path="1.jpg",
            width=640,
            height=480,
            has_scene_conflict=True,
            scene_tags=tags,
        )
        dq09 = dq09_scene_tag_conflict_rate([img])
        self.assertEqual(dq09["numerator"], 1)
        self.assertEqual(dq09["denominator"], 1)
        self.assertEqual(dq09["value"], 1.0)
        self.assertEqual(dq09["status"], "available")

    def test_06_zero_denominators_produce_not_available_with_reason(self):
        """Case 6: Zero denominators produce N/A or not_available with an explicit reason, never 0%."""
        empty_images: list[ImageRecord] = []
        empty_objects: list[ObjectRecord] = []

        # DP02
        dp02 = dp02_class_instance_share(empty_objects, classes=["car"])
        self.assertEqual(dp02[0]["status"], "not_available")
        self.assertIsNone(dp02[0]["class_object_ratio"])
        self.assertIsNone(dp02[0]["percentage"])

        # DP03
        dp03 = dp03_class_image_prevalence(empty_images, empty_objects, classes=["car"])
        self.assertEqual(dp03[0]["status"], "not_available")
        self.assertIsNone(dp03[0]["class_image_ratio"])
        self.assertIsNone(dp03[0]["percentage"])

        # DP04
        dp04 = dp04_attribute_distribution(empty_images, "timeofday")
        self.assertEqual(dp04["status"], "not_available")
        self.assertIn("Empty dataset", dp04["reason"])

        # DQ02 - DQ05
        dq02 = dq02_metadata_missing_rate(empty_images, "timeofday")
        self.assertEqual(dq02["status"], "not_available")
        self.assertIsNone(dq02["value"])
        self.assertIn("Empty dataset", dq02["reason"])

        # DQ06
        dq06 = dq06_invalid_bbox_rate(0, 0)
        self.assertEqual(dq06["status"], "not_available")
        self.assertIsNone(dq06["value"])
        self.assertIn("No bounding boxes", dq06["reason"])

        # DQ09
        dq09 = dq09_scene_tag_conflict_rate(empty_images)
        self.assertEqual(dq09["status"], "not_available")
        self.assertIsNone(dq09["value"])
        self.assertIn("Empty dataset", dq09["reason"])

        # class_distribution
        cd = class_distribution([])
        self.assertEqual(cd, [])

    def test_07_image_level_filters_applied_before_matching_objects(self):
        """Case 7: Image-level filters are applied before evaluating matching objects."""
        img_clear = ImageRecord("ds", "img_clear", "clear.jpg", 640, 480, weather="clear")
        img_rain = ImageRecord("ds", "img_rain", "rain.jpg", 640, 480, weather="rain")

        obj_clear = ObjectRecord("o1", "img_clear", "pedestrian", 10, 10, 50, 50, dataset_id="ds")
        obj_rain = ObjectRecord("o2", "img_rain", "pedestrian", 10, 10, 50, 50, dataset_id="ds")

        # Filtering step: select images with weather == "rain"
        rain_images = [img for img in [img_clear, img_rain] if img.weather == "rain"]
        rain_keys = {img.image_key for img in rain_images}

        # Objects evaluated only on filtered images
        rain_objects = [obj for obj in [obj_clear, obj_rain] if obj.image_key in rain_keys]

        self.assertEqual(len(rain_images), 1)
        self.assertEqual(len(rain_objects), 1)
        self.assertEqual(rain_objects[0].object_id, "o2")

    def test_08_image_and_object_level_metrics_differ_appropriately(self):
        """Case 8: Image-level and object-level metrics return different counts when appropriate."""
        img = ImageRecord("ds", "img_1", "1.jpg", 640, 480)
        # 1 image containing 4 pedestrian boxes
        objects = [
            ObjectRecord(f"o_{i}", "img_1", "pedestrian", 10, 10, 50, 50, dataset_id="ds")
            for i in range(4)
        ]

        inv = dp01_inventory([img], objects)
        self.assertEqual(inv["total_images"], 1)
        self.assertEqual(inv["total_valid_objects"], 4)

        prev = dp03_class_image_prevalence([img], objects)
        self.assertEqual(prev[0]["class_image_count"], 1)

        share = dp02_class_instance_share(objects)
        self.assertEqual(share[0]["class_object_count"], 4)

    def test_09_class_image_prevalence_counts_unique_images_not_instances(self):
        """Case 9: Class image prevalence counts unique images, not object instances."""
        img1 = ImageRecord("ds", "img_1", "1.jpg", 640, 480)
        img2 = ImageRecord("ds", "img_2", "2.jpg", 640, 480)
        images = [img1, img2]

        # 3 cars in img1, 2 cars in img2 -> total 5 instances across 2 images
        objects = (
            [ObjectRecord(f"c1_{i}", "img_1", "car", 10, 10, 50, 50, dataset_id="ds") for i in range(3)]
            + [ObjectRecord(f"c2_{i}", "img_2", "car", 10, 10, 50, 50, dataset_id="ds") for i in range(2)]
        )

        res = dp03_class_image_prevalence(images, objects)
        car_stat = res[0]
        self.assertEqual(car_stat["class_name"], "car")
        self.assertEqual(car_stat["class_image_count"], 2)  # Exactly 2 images, NOT 5!
        self.assertEqual(car_stat["class_image_ratio"], 1.0)  # 2 / 2 = 1.0

    def test_10_existing_and_extended_contract_compatibility(self):
        """Case 10: Existing metrics contracts and newly implemented metrics co-exist smoothly."""
        images = [
            ImageRecord("ds", "i1", "1.jpg", 640, 480, timeofday="day", weather="clear"),
            ImageRecord("ds", "i2", "2.jpg", 640, 480, timeofday="night", weather="rain"),
        ]
        valid_objects = [
            ObjectRecord("o1", "i1", "car", 10, 10, 50, 50, dataset_id="ds"),
        ]
        invalid_objects = [
            ObjectRecord("o2", "i2", "bus", 700, 10, 600, 50, dataset_id="ds"),  # reversed x
        ]
        all_objects = valid_objects + invalid_objects

        # DP01
        inv = dp01_inventory(images, valid_objects, all_objects=all_objects)
        self.assertEqual(inv["total_images"], 2)
        self.assertEqual(inv["total_objects"], 2)
        self.assertEqual(inv["total_valid_objects"], 1)

        # DQ06
        dq06 = dq06_invalid_bbox_rate(all_objects, invalid_objects)
        self.assertEqual(dq06["value"], 0.5)

        # DQ09
        dq09 = dq09_scene_tag_conflict_rate(images)
        self.assertEqual(dq09["value"], 0.0)
