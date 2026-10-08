"""Unit tests for the validation foundation layer (core/validation.py)
and parser integration (parsers/cvat_images.py).

Sprint 1: Schema Hardening + Validation Foundation.
Tests cover:
1. Bounding box validity (finite, dimensions, reversed, out-of-bounds, non-finite, multiple).
2. Metadata classification into 4 distinct states (known, unknown, missing, invalid).
3. Scene info duplicate vs conflict inspection.
4. Parser integration & regression (M vs M_valid, invalid bboxes preserved, attributes, occluded).
"""

from __future__ import annotations

import math
import unittest
import zipfile
from pathlib import Path
import tempfile

from core.schema import ImageRecord, ObjectRecord
from core.validation import (
    BBoxFailureReason,
    BBoxValidationResult,
    InvalidObjectRecord,
    MetadataState,
    MetadataValidationResult,
    SceneTagValidationResult,
    validate_bbox,
    validate_bbox_coordinates,
    validate_metadata_value,
    validate_scene_tags,
    validate_timeofday,
    validate_weather,
)
from parsers.cvat_images import CvatParseResult, parse_cvat_zip


# ── Helpers ─────────────────────────────────────────────────────────────

def _create_test_zip(dest_dir: Path, xml_content: str, zip_name: str = "test.zip") -> Path:
    """Helper to create a temporary CVAT ZIP archive with given XML content."""
    zip_path = dest_dir / zip_name
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("annotations.xml", xml_content.encode("utf-8"))
    return zip_path


def _wrap_cvat_xml(images_xml: str) -> str:
    """Wrap image elements in minimal valid CVAT annotations XML."""
    return f"""<?xml version="1.0" encoding="utf-8"?>
<annotations>
  <version>1.1</version>
{images_xml}
</annotations>"""


# ═══════════════════════════════════════════════════════════════════════
# 1. Bounding Box Geometry Tests (Items 1 - 10)
# ═══════════════════════════════════════════════════════════════════════

class TestBoundingBoxValidation(unittest.TestCase):
    """Test suite for bounding box geometric constraints."""

    def test_01_valid_bbox(self):
        """1. Valid bbox within image boundaries."""
        bbox = ObjectRecord(
            object_id="obj_1",
            image_id="img_1",
            class_name="car",
            x_min=10.0,
            y_min=20.0,
            x_max=100.0,
            y_max=200.0,
        )
        res = validate_bbox(bbox, image_width=640, image_height=480)
        self.assertTrue(res.valid)
        self.assertEqual(res.reasons, [])

    def test_02_zero_width(self):
        """2. Bbox with zero width (x_min == x_max)."""
        res = validate_bbox_coordinates(
            x_min=50.0, y_min=20.0, x_max=50.0, y_max=200.0,
            image_width=640, image_height=480,
        )
        self.assertFalse(res.valid)
        self.assertIn(BBoxFailureReason.ZERO_WIDTH.value, res.reasons)

    def test_03_zero_height(self):
        """3. Bbox with zero height (y_min == y_max)."""
        res = validate_bbox_coordinates(
            x_min=10.0, y_min=50.0, x_max=100.0, y_max=50.0,
            image_width=640, image_height=480,
        )
        self.assertFalse(res.valid)
        self.assertIn(BBoxFailureReason.ZERO_HEIGHT.value, res.reasons)

    def test_04_reversed_x_coordinates(self):
        """4. Bbox with reversed x coordinates (x_min > x_max). Coordinates not swapped."""
        x_min, x_max = 100.0, 10.0
        res = validate_bbox_coordinates(
            x_min=x_min, y_min=20.0, x_max=x_max, y_max=200.0,
            image_width=640, image_height=480,
        )
        self.assertFalse(res.valid)
        self.assertIn(BBoxFailureReason.REVERSED_X.value, res.reasons)
        self.assertIn(BBoxFailureReason.NEGATIVE_WIDTH.value, res.reasons)
        # Ensure values were not swapped
        self.assertEqual(x_min, 100.0)
        self.assertEqual(x_max, 10.0)

    def test_05_reversed_y_coordinates(self):
        """5. Bbox with reversed y coordinates (y_min > y_max). Coordinates not swapped."""
        y_min, y_max = 200.0, 20.0
        res = validate_bbox_coordinates(
            x_min=10.0, y_min=y_min, x_max=100.0, y_max=y_max,
            image_width=640, image_height=480,
        )
        self.assertFalse(res.valid)
        self.assertIn(BBoxFailureReason.REVERSED_Y.value, res.reasons)
        self.assertIn(BBoxFailureReason.NEGATIVE_HEIGHT.value, res.reasons)
        # Ensure values were not swapped
        self.assertEqual(y_min, 200.0)
        self.assertEqual(y_max, 20.0)

    def test_06_negative_dimensions(self):
        """6. Negative width and height simultaneously."""
        res = validate_bbox_coordinates(
            x_min=150.0, y_min=100.0, x_max=50.0, y_max=50.0,
            image_width=640, image_height=480,
        )
        self.assertFalse(res.valid)
        self.assertIn(BBoxFailureReason.NEGATIVE_WIDTH.value, res.reasons)
        self.assertIn(BBoxFailureReason.NEGATIVE_HEIGHT.value, res.reasons)

    def test_07_out_of_bounds_coordinates(self):
        """7. Coordinates out of image boundaries (negative and overflow). Coordinates not clamped."""
        # 7a. Negative x_min
        res_neg_x = validate_bbox_coordinates(
            x_min=-10.0, y_min=10.0, x_max=50.0, y_max=50.0,
            image_width=640, image_height=480,
        )
        self.assertFalse(res_neg_x.valid)
        self.assertIn(BBoxFailureReason.OUT_OF_BOUNDS.value, res_neg_x.reasons)

        # 7b. Negative y_min
        res_neg_y = validate_bbox_coordinates(
            x_min=10.0, y_min=-5.0, x_max=50.0, y_max=50.0,
            image_width=640, image_height=480,
        )
        self.assertFalse(res_neg_y.valid)
        self.assertIn(BBoxFailureReason.OUT_OF_BOUNDS.value, res_neg_y.reasons)

        # 7c. x_max exceeds image width
        res_overflow_x = validate_bbox_coordinates(
            x_min=10.0, y_min=10.0, x_max=700.0, y_max=50.0,
            image_width=640, image_height=480,
        )
        self.assertFalse(res_overflow_x.valid)
        self.assertIn(BBoxFailureReason.OUT_OF_BOUNDS.value, res_overflow_x.reasons)

        # 7d. y_max exceeds image height
        res_overflow_y = validate_bbox_coordinates(
            x_min=10.0, y_min=10.0, x_max=50.0, y_max=500.0,
            image_width=640, image_height=480,
        )
        self.assertFalse(res_overflow_y.valid)
        self.assertIn(BBoxFailureReason.OUT_OF_BOUNDS.value, res_overflow_y.reasons)

    def test_08_invalid_image_dimensions(self):
        """8. Invalid image width/height (<= 0)."""
        res_zero_w = validate_bbox_coordinates(
            x_min=10.0, y_min=10.0, x_max=50.0, y_max=50.0,
            image_width=0, image_height=480,
        )
        self.assertFalse(res_zero_w.valid)
        self.assertIn(BBoxFailureReason.INVALID_IMAGE_DIMENSIONS.value, res_zero_w.reasons)

        res_neg_h = validate_bbox_coordinates(
            x_min=10.0, y_min=10.0, x_max=50.0, y_max=50.0,
            image_width=640, image_height=-10,
        )
        self.assertFalse(res_neg_h.valid)
        self.assertIn(BBoxFailureReason.INVALID_IMAGE_DIMENSIONS.value, res_neg_h.reasons)

    def test_09_non_finite_coordinates(self):
        """9. Non-finite coordinates (NaN, Inf)."""
        res_nan = validate_bbox_coordinates(
            x_min=float("nan"), y_min=10.0, x_max=50.0, y_max=50.0,
            image_width=640, image_height=480,
        )
        self.assertFalse(res_nan.valid)
        self.assertIn(BBoxFailureReason.NON_FINITE_COORDINATES.value, res_nan.reasons)

        res_inf = validate_bbox_coordinates(
            x_min=10.0, y_min=10.0, x_max=float("inf"), y_max=50.0,
            image_width=640, image_height=480,
        )
        self.assertFalse(res_inf.valid)
        self.assertIn(BBoxFailureReason.NON_FINITE_COORDINATES.value, res_inf.reasons)

    def test_10_multiple_validation_failures(self):
        """10. Multiple validation failures on the same bbox are accumulated."""
        # x_min > x_max (reversed x, negative width) AND y_min == y_max (zero height) AND out_of_bounds
        res = validate_bbox_coordinates(
            x_min=700.0, y_min=-10.0, x_max=600.0, y_max=-10.0,
            image_width=640, image_height=480,
        )
        self.assertFalse(res.valid)
        self.assertIn(BBoxFailureReason.REVERSED_X.value, res.reasons)
        self.assertIn(BBoxFailureReason.NEGATIVE_WIDTH.value, res.reasons)
        self.assertIn(BBoxFailureReason.ZERO_HEIGHT.value, res.reasons)
        self.assertIn(BBoxFailureReason.OUT_OF_BOUNDS.value, res.reasons)
        self.assertGreaterEqual(len(res.reasons), 4)


# ═══════════════════════════════════════════════════════════════════════
# 2. Metadata Classification & Taxonomy Tests (Items 11 - 16)
# ═══════════════════════════════════════════════════════════════════════

class TestMetadataValidation(unittest.TestCase):
    """Test suite for the 4 metadata states and project taxonomies."""

    def test_11_known_weather(self):
        """11. Known weather values from taxonomy."""
        for val in ["clear", "rain", "fog", "overcast"]:
            res = validate_weather(val)
            self.assertEqual(res.state, MetadataState.KNOWN)
            self.assertEqual(res.value, val)
            self.assertEqual(res.original_value, val)

    def test_12_known_timeofday(self):
        """12. Known timeofday values from taxonomy."""
        for val in ["day", "night", "dawn_dusk"]:
            res = validate_timeofday(val)
            self.assertEqual(res.state, MetadataState.KNOWN)
            self.assertEqual(res.value, val)
            self.assertEqual(res.original_value, val)

    def test_13_unknown_metadata(self):
        """13. Explicit 'unknown' is classified as UNKNOWN."""
        res_w = validate_weather("unknown")
        self.assertEqual(res_w.state, MetadataState.UNKNOWN)
        self.assertEqual(res_w.value, "unknown")

        res_t = validate_timeofday("Unknown")
        self.assertEqual(res_t.state, MetadataState.UNKNOWN)
        self.assertEqual(res_t.value, "unknown")

    def test_14_missing_metadata(self):
        """14. Absent, None, or empty string is classified as MISSING."""
        res_none = validate_weather(None)
        self.assertEqual(res_none.state, MetadataState.MISSING)
        self.assertIsNone(res_none.value)

        res_empty = validate_timeofday("")
        self.assertEqual(res_empty.state, MetadataState.MISSING)
        self.assertIsNone(res_empty.value)

        res_spaces = validate_timeofday("   ")
        self.assertEqual(res_spaces.state, MetadataState.MISSING)
        self.assertIsNone(res_spaces.value)

    def test_15_invalid_metadata_preserves_original(self):
        """15. Value outside taxonomy is INVALID and preserves original value without converting."""
        res_sunny = validate_weather("sunny")
        self.assertEqual(res_sunny.state, MetadataState.INVALID)
        self.assertEqual(res_sunny.original_value, "sunny")
        self.assertNotEqual(res_sunny.value, "clear")

        res_noon = validate_timeofday("noon")
        self.assertEqual(res_noon.state, MetadataState.INVALID)
        self.assertEqual(res_noon.original_value, "noon")
        self.assertNotEqual(res_noon.value, "day")

    def test_16_metadata_states_remain_distinct(self):
        """16. Ensure known, unknown, missing, and invalid are strictly distinct."""
        states = {
            validate_weather("clear").state,
            validate_weather("unknown").state,
            validate_weather(None).state,
            validate_weather("stormy").state,
        }
        self.assertEqual(len(states), 4)
        self.assertEqual(
            states,
            {
                MetadataState.KNOWN,
                MetadataState.UNKNOWN,
                MetadataState.MISSING,
                MetadataState.INVALID,
            },
        )
        # Verify unknown != missing
        self.assertNotEqual(MetadataState.UNKNOWN, MetadataState.MISSING)
        # Verify unknown != known
        self.assertNotEqual(MetadataState.UNKNOWN, MetadataState.KNOWN)


# ═══════════════════════════════════════════════════════════════════════
# 3. Scene Info Duplicate vs Conflict Tests (Items 17 - 20)
# ═══════════════════════════════════════════════════════════════════════

class TestSceneTagValidation(unittest.TestCase):
    """Test suite for inspecting scene_info tags and conflict detection."""

    def test_17_one_normal_scene_info_tag(self):
        """17. Single valid scene_info tag."""
        tags = [{"timeofday": "day", "weather": "clear"}]
        res = validate_scene_tags(tags)
        self.assertFalse(res.has_conflict)
        self.assertFalse(res.is_duplicate)
        self.assertEqual(res.timeofday, "day")
        self.assertEqual(res.weather, "clear")

    def test_18_multiple_identical_scene_info_tags(self):
        """18. Multiple identical scene_info tags are not a conflict (duplicate recognized)."""
        tags = [
            {"timeofday": "day", "weather": "clear"},
            {"timeofday": "day", "weather": "clear"},
        ]
        res = validate_scene_tags(tags)
        self.assertFalse(res.has_conflict)
        self.assertTrue(res.is_duplicate)
        self.assertEqual(res.timeofday, "day")
        self.assertEqual(res.weather, "clear")

    def test_19_conflicting_scene_info_tags(self):
        """19. Differing scene_info tags must be detected as a conflict."""
        tags = [
            {"timeofday": "day", "weather": "clear"},
            {"timeofday": "night", "weather": "rain"},
        ]
        res = validate_scene_tags(tags)
        self.assertTrue(res.has_conflict)
        self.assertFalse(res.is_duplicate)
        self.assertIn("timeofday", res.conflicting_fields)
        self.assertIn("weather", res.conflicting_fields)
        # Neither value is silently chosen
        self.assertIsNone(res.timeofday)
        self.assertIsNone(res.weather)

    def test_20_conflict_detected_instead_of_silently_selecting(self):
        """20. Conflict on one attribute (weather) leaves weather unresolved without picking first/last."""
        tags = [
            {"timeofday": "day", "weather": "clear"},
            {"timeofday": "day", "weather": "rain"},
        ]
        res = validate_scene_tags(tags)
        self.assertTrue(res.has_conflict)
        self.assertIn("weather", res.conflicting_fields)
        self.assertNotIn("timeofday", res.conflicting_fields)
        self.assertIsNone(res.weather)
        # Consistent field is preserved
        self.assertEqual(res.timeofday, "day")
        # All tags are preserved
        self.assertEqual(len(res.tags), 2)


# ═══════════════════════════════════════════════════════════════════════
# 4. Parser Integration & Regression Tests (Items 21 - 25+)
# ═══════════════════════════════════════════════════════════════════════

class TestParserIntegrationAndRegression(unittest.TestCase):
    """Test suite for parser behavior with validation foundation."""

    def test_21_images_without_bboxes_preserved(self):
        """21. Images without bboxes are preserved."""
        xml = _wrap_cvat_xml("""
  <image id="0" name="empty.jpg" width="640" height="480">
  </image>
""")
        with tempfile.TemporaryDirectory() as tmp_dir:
            zip_path = _create_test_zip(Path(tmp_dir), xml)
            result = parse_cvat_zip(str(zip_path))
            self.assertEqual(len(result.images), 1)
            self.assertEqual(result.images[0].image_id, "0")
            self.assertEqual(len(result.objects), 0)
            self.assertEqual(len(result.valid_objects), 0)

    def test_22_valid_bboxes_parse_as_before(self):
        """22. Valid bboxes parse correctly into both objects (M) and valid_objects (M_valid)."""
        xml = _wrap_cvat_xml("""
  <image id="1" name="img1.jpg" width="640" height="480">
    <box label="car" occluded="0" xtl="10.0" ytl="20.0" xbr="100.0" ybr="200.0" />
    <box label="truck" occluded="1" xtl="150.0" ytl="160.0" xbr="250.0" ybr="300.0" />
  </image>
""")
        with tempfile.TemporaryDirectory() as tmp_dir:
            zip_path = _create_test_zip(Path(tmp_dir), xml)
            result = parse_cvat_zip(str(zip_path))
            self.assertEqual(len(result.objects), 2)
            self.assertEqual(len(result.valid_objects), 2)
            self.assertEqual(len(result.invalid_objects), 0)

    def test_23_unsupported_shapes_retained(self):
        """23. Unsupported shapes retain their current counting in skipped_shapes."""
        xml = _wrap_cvat_xml("""
  <image id="1" name="img1.jpg" width="640" height="480">
    <polygon label="car" points="10,20;30,40;50,60" />
    <polyline label="lane" points="0,0;100,100" />
  </image>
""")
        with tempfile.TemporaryDirectory() as tmp_dir:
            zip_path = _create_test_zip(Path(tmp_dir), xml)
            result = parse_cvat_zip(str(zip_path))
            self.assertEqual(result.skipped_shapes.get("polygon"), 1)
            self.assertEqual(result.skipped_shapes.get("polyline"), 1)

    def test_24_object_attributes_preserved(self):
        """24. Object attributes are properly parsed and preserved."""
        xml = _wrap_cvat_xml("""
  <image id="1" name="img1.jpg" width="640" height="480">
    <box label="car" occluded="0" xtl="10.0" ytl="20.0" xbr="100.0" ybr="200.0">
      <attribute name="color">red</attribute>
      <attribute name="type">sedan</attribute>
    </box>
  </image>
""")
        with tempfile.TemporaryDirectory() as tmp_dir:
            zip_path = _create_test_zip(Path(tmp_dir), xml)
            result = parse_cvat_zip(str(zip_path))
            self.assertEqual(len(result.objects), 1)
            obj = result.objects[0]
            self.assertEqual(obj.attributes, {"color": "red", "type": "sedan"})

    def test_25_occluded_values_preserved(self):
        """25. occluded='1' maps to True and occluded='0' maps to False."""
        xml = _wrap_cvat_xml("""
  <image id="1" name="img1.jpg" width="640" height="480">
    <box label="car" occluded="1" xtl="10.0" ytl="20.0" xbr="100.0" ybr="200.0" />
    <box label="pedestrian" occluded="0" xtl="110.0" ytl="120.0" xbr="130.0" ybr="180.0" />
  </image>
""")
        with tempfile.TemporaryDirectory() as tmp_dir:
            zip_path = _create_test_zip(Path(tmp_dir), xml)
            result = parse_cvat_zip(str(zip_path))
            self.assertTrue(result.objects[0].occluded)
            self.assertFalse(result.objects[1].occluded)

    def test_26_invalid_bboxes_not_lost_and_not_auto_fixed(self):
        """Invalid bboxes remain in objects (M) and invalid_objects, but not valid_objects (M_valid)."""
        xml = _wrap_cvat_xml("""
  <image id="1" name="img1.jpg" width="640" height="480">
    <!-- Valid box -->
    <box label="car" occluded="0" xtl="10.0" ytl="20.0" xbr="100.0" ybr="200.0" />
    <!-- Invalid box: reversed x, out of bounds -->
    <box label="truck" occluded="0" xtl="700.0" ytl="20.0" xbr="100.0" ybr="200.0" />
  </image>
""")
        with tempfile.TemporaryDirectory() as tmp_dir:
            zip_path = _create_test_zip(Path(tmp_dir), xml)
            result = parse_cvat_zip(str(zip_path))
            # M = 2
            self.assertEqual(len(result.objects), 2)
            # M_valid = 1
            self.assertEqual(len(result.valid_objects), 1)
            self.assertEqual(result.valid_objects[0].class_name, "car")
            # Invalid = 1
            self.assertEqual(len(result.invalid_objects), 1)
            inv = result.invalid_objects[0]
            self.assertEqual(inv.object.class_name, "truck")
            # Coordinates preserved without silent auto-fix
            self.assertEqual(inv.object.x_min, 700.0)
            self.assertEqual(inv.object.x_max, 100.0)
            self.assertIn("reversed_x", inv.reasons)
            self.assertIn("out_of_bounds", inv.reasons)

    def test_27_parser_detects_scene_conflict(self):
        """Conflicting scene_info tags on an image are flagged without silent selection."""
        xml = _wrap_cvat_xml("""
  <image id="1" name="img1.jpg" width="640" height="480">
    <tag label="scene_info">
      <attribute name="timeofday">day</attribute>
      <attribute name="weather">clear</attribute>
    </tag>
    <tag label="scene_info">
      <attribute name="timeofday">night</attribute>
      <attribute name="weather">rain</attribute>
    </tag>
  </image>
""")
        with tempfile.TemporaryDirectory() as tmp_dir:
            zip_path = _create_test_zip(Path(tmp_dir), xml)
            result = parse_cvat_zip(str(zip_path))
            self.assertEqual(len(result.images), 1)
            img = result.images[0]
            self.assertTrue(img.has_scene_conflict)
            self.assertIsNone(img.timeofday)
            self.assertIsNone(img.weather)
            self.assertEqual(len(img.scene_tags), 2)


if __name__ == "__main__":
    unittest.main()
