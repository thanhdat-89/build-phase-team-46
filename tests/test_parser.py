"""Unit tests for the CVAT Images 1.1 ZIP parser (parsers/cvat_images.py).

Uses small, synthetic, in-memory/temporary ZIP fixtures via zipfile.
No hardcoded local file paths, no real ZIP download dependency, no Streamlit.
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any

import pytest

from parsers.cvat_images import (
    CvatInvalidValueError,
    CvatMissingAttributeError,
    CvatMultipleXmlError,
    CvatParseResult,
    CvatXmlNotFoundError,
    CvatXmlSyntaxError,
    CvatZipError,
    parse_cvat_zip,
)


# ── Helpers ────────────────────────────────────────────────────────────


def _create_zip(
    dest_dir: Path,
    files: dict[str, str | bytes],
    zip_name: str = "test_export.zip",
) -> Path:
    """Helper to create a temporary ZIP archive containing the given files."""
    zip_path = dest_dir / zip_name
    with zipfile.ZipFile(zip_path, "w") as zf:
        for arcname, content in files.items():
            if isinstance(content, str):
                zf.writestr(arcname, content.encode("utf-8"))
            else:
                zf.writestr(arcname, content)
    return zip_path


def _build_cvat_xml(
    images_xml: str,
    version: str = "1.1",
) -> str:
    """Wrap image elements in minimal valid CVAT annotations XML."""
    return f"""<?xml version="1.0" encoding="utf-8"?>
<annotations>
  <version>{version}</version>
{images_xml}
</annotations>
"""


# ═══════════════════════════════════════════════════════════════════════
# 1. Dataset regression fixture (multi-image, multi-box, no-box, scene)
# ═══════════════════════════════════════════════════════════════════════


class TestCvatZipRegressionFixture:
    """Regression tests verifying overall parser behavior with a synthetic fixture."""

    @pytest.fixture
    def sample_zip(self, tmp_path: Path) -> Path:
        xml_content = _build_cvat_xml("""
  <image id="0" name="img0.jpg" width="640" height="640">
    <box label="GreenSM" occluded="0" xtl="10.0" ytl="20.0" xbr="100.0" ybr="200.0" />
    <box label="GreenSM" occluded="1" xtl="150.0" ytl="160.0" xbr="250.0" ybr="300.0" />
    <tag label="scene_info">
      <attribute name="timeofday">day</attribute>
      <attribute name="weather">clear</attribute>
    </tag>
  </image>
  <image id="1" name="img1.jpg" width="640" height="640">
    <!-- Image with no boxes, no scene_info -->
  </image>
  <image id="2" name="img2.jpg" width="640" height="640">
    <box label="Bus" occluded="0" xtl="50.0" ytl="50.0" xbr="80.0" ybr="90.0" />
    <tag label="scene_info">
      <attribute name="timeofday">unknown</attribute>
      <attribute name="weather">rain</attribute>
    </tag>
  </image>
""")
        return _create_zip(tmp_path, {"annotations.xml": xml_content})

    def test_overall_parsing(self, sample_zip: Path):
        result = parse_cvat_zip(str(sample_zip), dataset_id="ds_test")
        assert isinstance(result, CvatParseResult)
        assert len(result.images) == 3
        assert len(result.objects) == 3
        assert result.skipped_shapes == {}

        # Check dataset_id
        assert all(img.dataset_id == "ds_test" for img in result.images)

        # Check box counts per image
        img0_boxes = [o for o in result.objects if o.image_id == "0"]
        img1_boxes = [o for o in result.objects if o.image_id == "1"]
        img2_boxes = [o for o in result.objects if o.image_id == "2"]

        assert len(img0_boxes) == 2
        assert len(img1_boxes) == 0
        assert len(img2_boxes) == 1

        # Verify scene_info is not an object
        assert all(o.class_name != "scene_info" for o in result.objects)


# ═══════════════════════════════════════════════════════════════════════
# 2. Image parsing
# ═══════════════════════════════════════════════════════════════════════


class TestImageParsing:
    """Verify image record field mapping."""

    def test_image_attributes_mapped_correctly(self, tmp_path: Path):
        xml = _build_cvat_xml("""
  <image id="42" name="path/to/frame_042.jpg" width="1920" height="1080">
  </image>
""")
        zip_path = _create_zip(tmp_path, {"annotations.xml": xml})
        result = parse_cvat_zip(str(zip_path), dataset_id="custom_dataset")

        assert len(result.images) == 1
        img = result.images[0]
        assert img.dataset_id == "custom_dataset"
        assert img.image_id == "42"
        assert img.image_path == "path/to/frame_042.jpg"
        assert img.width == 1920
        assert img.height == 1080


# ═══════════════════════════════════════════════════════════════════════
# 3. Box parsing
# ═══════════════════════════════════════════════════════════════════════


class TestBoxParsing:
    """Verify box record field mapping."""

    def test_box_attributes_mapped_correctly(self, tmp_path: Path):
        xml = _build_cvat_xml("""
  <image id="10" name="sample.jpg" width="640" height="480">
    <box label="Car" occluded="0" xtl="12.5" ytl="34.0" xbr="56.75" ybr="78.25">
      <attribute name="color">red</attribute>
    </box>
    <box label="Pedestrian" occluded="1" xtl="1.0" ytl="2.0" xbr="3.0" ybr="4.0" />
  </image>
""")
        zip_path = _create_zip(tmp_path, {"annotations.xml": xml})
        result = parse_cvat_zip(str(zip_path))

        assert len(result.objects) == 2

        b1 = result.objects[0]
        assert b1.class_name == "Car"
        assert b1.image_id == "10"
        assert b1.x_min == 12.5
        assert b1.y_min == 34.0
        assert b1.x_max == 56.75
        assert b1.y_max == 78.25
        assert b1.occluded is False
        assert b1.attributes == {"color": "red"}

        b2 = result.objects[1]
        assert b2.class_name == "Pedestrian"
        assert b2.image_id == "10"
        assert b2.occluded is True
        assert b2.attributes == {}


# ═══════════════════════════════════════════════════════════════════════
# 4. Object ID generation & preservation
# ═══════════════════════════════════════════════════════════════════════


class TestObjectId:
    """Verify deterministic generation of object_id and preservation of existing id."""

    def test_generated_object_ids_are_deterministic(self, tmp_path: Path):
        xml = _build_cvat_xml("""
  <image id="imgA" name="a.jpg" width="100" height="100">
    <box label="GreenSM" xtl="0" ytl="0" xbr="1" ybr="1" />
    <box label="GreenSM" xtl="2" ytl="2" xbr="3" ybr="3" />
  </image>
""")
        zip_path = _create_zip(tmp_path, {"annotations.xml": xml})

        res1 = parse_cvat_zip(str(zip_path))
        res2 = parse_cvat_zip(str(zip_path))

        ids1 = [obj.object_id for obj in res1.objects]
        ids2 = [obj.object_id for obj in res2.objects]

        assert ids1 == ["imgA_obj0", "imgA_obj1"]
        assert ids1 == ids2

    def test_two_boxes_in_same_image_have_distinct_ids(self, tmp_path: Path):
        xml = _build_cvat_xml("""
  <image id="1" name="a.jpg" width="100" height="100">
    <box label="GreenSM" xtl="0" ytl="0" xbr="1" ybr="1" />
    <box label="GreenSM" xtl="2" ytl="2" xbr="3" ybr="3" />
  </image>
""")
        zip_path = _create_zip(tmp_path, {"annotations.xml": xml})
        result = parse_cvat_zip(str(zip_path))

        assert len(result.objects) == 2
        assert result.objects[0].object_id != result.objects[1].object_id

    def test_explicit_box_id_preserved(self, tmp_path: Path):
        xml = _build_cvat_xml("""
  <image id="1" name="a.jpg" width="100" height="100">
    <box id="box_999" label="GreenSM" xtl="0" ytl="0" xbr="1" ybr="1" />
  </image>
""")
        zip_path = _create_zip(tmp_path, {"annotations.xml": xml})
        result = parse_cvat_zip(str(zip_path))

        assert result.objects[0].object_id == "box_999"


# ═══════════════════════════════════════════════════════════════════════
# 5. Scene info metadata
# ═══════════════════════════════════════════════════════════════════════


class TestSceneInfo:
    """Verify scene_info extraction for timeofday and weather."""

    def test_scene_info_variants(self, tmp_path: Path):
        xml = _build_cvat_xml("""
  <image id="0" name="0.jpg" width="100" height="100">
    <tag label="scene_info">
      <attribute name="timeofday">day</attribute>
      <attribute name="weather">clear</attribute>
    </tag>
  </image>
  <image id="1" name="1.jpg" width="100" height="100">
    <tag label="scene_info">
      <attribute name="timeofday">night</attribute>
      <attribute name="weather">rain</attribute>
    </tag>
  </image>
  <image id="2" name="2.jpg" width="100" height="100">
    <tag label="scene_info">
      <attribute name="timeofday">unknown</attribute>
      <attribute name="weather">unknown</attribute>
    </tag>
  </image>
  <image id="3" name="3.jpg" width="100" height="100">
    <!-- Tag entirely missing -->
  </image>
  <image id="4" name="4.jpg" width="100" height="100">
    <tag label="scene_info">
      <!-- Only timeofday present -->
      <attribute name="timeofday">dawn_dusk</attribute>
    </tag>
  </image>
""")
        zip_path = _create_zip(tmp_path, {"annotations.xml": xml})
        result = parse_cvat_zip(str(zip_path))

        img0, img1, img2, img3, img4 = result.images

        assert img0.timeofday == "day"
        assert img0.weather == "clear"

        assert img1.timeofday == "night"
        assert img1.weather == "rain"

        # Explicit unknown remains unknown
        assert img2.timeofday == "unknown"
        assert img2.weather == "unknown"

        # Missing tag -> None
        assert img3.timeofday is None
        assert img3.weather is None

        # Missing attribute -> None
        assert img4.timeofday == "dawn_dusk"
        assert img4.weather is None


# ═══════════════════════════════════════════════════════════════════════
# 6. ZIP validation
# ═══════════════════════════════════════════════════════════════════════


class TestZipValidation:
    """Verify validation of ZIP input and structure."""

    def test_non_zip_file_raises_error(self, tmp_path: Path):
        fake_file = tmp_path / "not_a_zip.zip"
        fake_file.write_text("This is not a zip file.")
        with pytest.raises(CvatZipError, match="Not a valid ZIP file"):
            parse_cvat_zip(str(fake_file))

    def test_non_existent_file_raises_error(self, tmp_path: Path):
        missing = tmp_path / "does_not_exist.zip"
        with pytest.raises(CvatZipError, match="File not found"):
            parse_cvat_zip(str(missing))

    def test_zip_with_no_xml_raises_error(self, tmp_path: Path):
        zip_path = _create_zip(tmp_path, {"images/img.jpg": b"\xff\xd8\xff"})
        with pytest.raises(CvatXmlNotFoundError, match="does not contain any XML files"):
            parse_cvat_zip(str(zip_path))

    def test_zip_with_multiple_xmls_raises_error(self, tmp_path: Path):
        zip_path = _create_zip(
            tmp_path,
            {
                "annotations1.xml": "<annotations></annotations>",
                "annotations2.xml": "<annotations></annotations>",
            },
        )
        with pytest.raises(CvatMultipleXmlError, match="contains 2 XML files"):
            parse_cvat_zip(str(zip_path))

    def test_macosx_resource_fork_xml_ignored(self, tmp_path: Path):
        """__MACOSX/._annotations.xml should not trigger multiple XML error."""
        xml = _build_cvat_xml('<image id="0" name="a.jpg" width="10" height="10"/>')
        zip_path = _create_zip(
            tmp_path,
            {
                "annotations.xml": xml,
                "__MACOSX/._annotations.xml": b"dummy_resource_fork",
            },
        )
        result = parse_cvat_zip(str(zip_path))
        assert len(result.images) == 1


# ═══════════════════════════════════════════════════════════════════════
# 7. Malformed XML
# ═══════════════════════════════════════════════════════════════════════


class TestMalformedXml:
    """Verify proper exception handling for syntax-corrupted XML."""

    def test_unclosed_xml_tag_raises_syntax_error(self, tmp_path: Path):
        corrupt_xml = "<annotations><image id='0' name='a.jpg'"
        zip_path = _create_zip(tmp_path, {"annotations.xml": corrupt_xml})
        with pytest.raises(CvatXmlSyntaxError, match="Malformed XML"):
            parse_cvat_zip(str(zip_path))


# ═══════════════════════════════════════════════════════════════════════
# 8. Missing and invalid attributes
# ═══════════════════════════════════════════════════════════════════════


class TestInvalidAttributes:
    """Verify strict validation of mandatory attributes and data types."""

    def test_missing_image_id_raises_missing_attribute(self, tmp_path: Path):
        xml = _build_cvat_xml('<image name="a.jpg" width="100" height="100" />')
        zip_path = _create_zip(tmp_path, {"annotations.xml": xml})
        with pytest.raises(CvatMissingAttributeError, match="Missing required attribute 'id'"):
            parse_cvat_zip(str(zip_path))

    def test_missing_image_name_raises_missing_attribute(self, tmp_path: Path):
        xml = _build_cvat_xml('<image id="0" width="100" height="100" />')
        zip_path = _create_zip(tmp_path, {"annotations.xml": xml})
        with pytest.raises(CvatMissingAttributeError, match="Missing required attribute 'name'"):
            parse_cvat_zip(str(zip_path))

    def test_non_integer_image_width_raises_invalid_value(self, tmp_path: Path):
        xml = _build_cvat_xml('<image id="0" name="a.jpg" width="bad_int" height="100" />')
        zip_path = _create_zip(tmp_path, {"annotations.xml": xml})
        with pytest.raises(CvatInvalidValueError, match="Invalid integer value 'bad_int'"):
            parse_cvat_zip(str(zip_path))

    def test_missing_box_label_raises_missing_attribute(self, tmp_path: Path):
        xml = _build_cvat_xml("""
  <image id="0" name="a.jpg" width="100" height="100">
    <box xtl="0" ytl="0" xbr="10" ybr="10" />
  </image>
""")
        zip_path = _create_zip(tmp_path, {"annotations.xml": xml})
        with pytest.raises(CvatMissingAttributeError, match="Missing required attribute 'label'"):
            parse_cvat_zip(str(zip_path))

    def test_non_numeric_box_coord_raises_invalid_value(self, tmp_path: Path):
        xml = _build_cvat_xml("""
  <image id="0" name="a.jpg" width="100" height="100">
    <box label="Car" xtl="not_a_float" ytl="0" xbr="10" ybr="10" />
  </image>
""")
        zip_path = _create_zip(tmp_path, {"annotations.xml": xml})
        with pytest.raises(CvatInvalidValueError, match="Invalid numeric value 'not_a_float'"):
            parse_cvat_zip(str(zip_path))


# ═══════════════════════════════════════════════════════════════════════
# 9. Unsupported shapes
# ═══════════════════════════════════════════════════════════════════════


class TestUnsupportedShapes:
    """Verify that unsupported shape types are skipped and counted without crash."""

    def test_polygon_and_polyline_are_skipped(self, tmp_path: Path):
        xml = _build_cvat_xml("""
  <image id="0" name="a.jpg" width="100" height="100">
    <box label="Car" xtl="0" ytl="0" xbr="10" ybr="10" />
    <polygon label="Building" points="0,0;10,0;10,10;0,10" />
    <polygon label="Building" points="5,5;15,5;15,15" />
    <polyline label="Road" points="0,0;100,100" />
  </image>
""")
        zip_path = _create_zip(tmp_path, {"annotations.xml": xml})
        result = parse_cvat_zip(str(zip_path))

        assert len(result.objects) == 1
        assert result.objects[0].class_name == "Car"
        assert result.skipped_shapes == {"polygon": 2, "polyline": 1}


# ═══════════════════════════════════════════════════════════════════════
# 10. Direct ZIP reading & subdirectories
# ═══════════════════════════════════════════════════════════════════════


class TestDirectZipReading:
    """Verify XML can be in a subfolder within the ZIP and parsed directly."""

    def test_nested_xml_member_detected_and_parsed(self, tmp_path: Path):
        xml = _build_cvat_xml("""
  <image id="100" name="sample.png" width="300" height="200">
    <box label="Bike" xtl="1" ytl="2" xbr="3" ybr="4" />
  </image>
""")
        zip_path = _create_zip(tmp_path, {"nested/folder/cvat_export.xml": xml})
        result = parse_cvat_zip(str(zip_path))

        assert len(result.images) == 1
        assert result.images[0].image_id == "100"
        assert len(result.objects) == 1
        assert result.objects[0].class_name == "Bike"
