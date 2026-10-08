"""Parser for CVAT Images 1.1 ZIP exports.

Reads a ZIP file containing a single CVAT XML annotation file and
(optionally) an images/ folder.  Returns lists of ``ImageRecord`` and
``ObjectRecord`` ready for consumption by ``core.statistics``.

Security
--------
* Uses **defusedxml** to parse XML (mitigates XML bombs / XXE).
* Reads the XML member directly from the ZIP; never extracts to disk.
* Does not execute anything from the ZIP.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from defusedxml.ElementTree import fromstring, ParseError

from core.schema import ImageRecord, ObjectRecord


# ── Exceptions ─────────────────────────────────────────────────────────


class CvatParseError(Exception):
    """Base exception for all CVAT parsing errors."""


class CvatZipError(CvatParseError):
    """The file is not a valid ZIP or cannot be opened."""


class CvatXmlNotFoundError(CvatParseError):
    """No XML file was found inside the ZIP."""


class CvatMultipleXmlError(CvatParseError):
    """Multiple XML files found; caller must choose one."""


class CvatXmlSyntaxError(CvatParseError):
    """The XML file is not well-formed."""


class CvatMissingAttributeError(CvatParseError):
    """A required XML attribute is missing from an element."""


class CvatInvalidValueError(CvatParseError):
    """A numeric attribute has an invalid (non-numeric) value."""


# ── Result container ───────────────────────────────────────────────────


@dataclass
class CvatParseResult:
    """Minimal container returned by the CVAT ZIP parser.

    Attributes
    ----------
    images : list[ImageRecord]
        One record per ``<image>`` element in the XML.
    objects : list[ObjectRecord]
        One record per ``<box>`` element.
    skipped_shapes : dict[str, int]
        Counts of unsupported annotation shapes that were silently
        skipped (e.g. ``{"polygon": 3, "polyline": 1}``).
    """

    images: list[ImageRecord] = field(default_factory=list)
    objects: list[ObjectRecord] = field(default_factory=list)
    skipped_shapes: dict[str, int] = field(default_factory=dict)


# ── Shape element names recognised by CVAT but NOT parsed here ─────────

_UNSUPPORTED_SHAPES = frozenset({
    "polygon",
    "polyline",
    "points",
    "ellipse",
    "mask",
    "cuboid",
    "skeleton",
})

# "box" is the only supported shape.
# "tag" is image-level metadata, not a shape annotation.


# ── Internal helpers ───────────────────────────────────────────────────


def _require_attr(element: Any, attr: str, context: str) -> str:
    """Return the string value of *attr* on *element*, or raise."""
    value = element.get(attr)
    if value is None:
        raise CvatMissingAttributeError(
            f"Missing required attribute '{attr}' on {context}"
        )
    return value


def _parse_float(value: str, attr: str, context: str) -> float:
    """Convert *value* to float or raise with a clear message."""
    try:
        return float(value)
    except (ValueError, TypeError) as exc:
        raise CvatInvalidValueError(
            f"Invalid numeric value '{value}' for attribute '{attr}' "
            f"on {context}"
        ) from exc


def _parse_int(value: str, attr: str, context: str) -> int:
    """Convert *value* to int or raise with a clear message."""
    try:
        return int(value)
    except (ValueError, TypeError) as exc:
        raise CvatInvalidValueError(
            f"Invalid integer value '{value}' for attribute '{attr}' "
            f"on {context}"
        ) from exc


def _find_single_xml(zf: zipfile.ZipFile) -> str:
    """Return the member name of the single XML inside *zf*.

    Raises
    ------
    CvatXmlNotFoundError
        If the ZIP contains no ``.xml`` files.
    CvatMultipleXmlError
        If the ZIP contains more than one ``.xml`` file.
    """
    xml_names = [
        name
        for name in zf.namelist()
        if PurePosixPath(name).suffix.lower() == ".xml"
        and not name.startswith("__MACOSX")  # skip macOS resource forks
    ]

    if len(xml_names) == 0:
        raise CvatXmlNotFoundError(
            "The ZIP file does not contain any XML files."
        )

    if len(xml_names) > 1:
        listing = ", ".join(sorted(xml_names))
        raise CvatMultipleXmlError(
            f"The ZIP file contains {len(xml_names)} XML files: {listing}. "
            "Please specify which XML file to parse."
        )

    return xml_names[0]


def _extract_scene_info(
    image_elem: Any,
) -> tuple[str | None, str | None]:
    """Extract ``timeofday`` and ``weather`` from a ``<tag label="scene_info">``
    child of *image_elem*.

    Returns ``(timeofday, weather)`` where each value is:
    * the attribute text if present,
    * ``None`` if the tag or the attribute is missing entirely.
    """
    timeofday: str | None = None
    weather: str | None = None

    for tag_elem in image_elem.findall("tag"):
        if tag_elem.get("label") != "scene_info":
            continue

        for attr_elem in tag_elem.findall("attribute"):
            attr_name = attr_elem.get("name")
            if attr_name == "timeofday":
                timeofday = (attr_elem.text or "").strip() or None
            elif attr_name == "weather":
                weather = (attr_elem.text or "").strip() or None

        # Only use the first scene_info tag.
        break

    return timeofday, weather


def _parse_box(
    box_elem: Any,
    image_id: str,
    box_index: int,
) -> ObjectRecord:
    """Parse a single ``<box>`` element into an ``ObjectRecord``."""
    context = f"<box> #{box_index} in image '{image_id}'"

    # Object ID: use the @id attribute if present, else generate one.
    raw_id = box_elem.get("id")
    if raw_id is not None:
        object_id = raw_id
    else:
        object_id = f"{image_id}_obj{box_index}"

    class_name = _require_attr(box_elem, "label", context)

    x_min = _parse_float(_require_attr(box_elem, "xtl", context), "xtl", context)
    y_min = _parse_float(_require_attr(box_elem, "ytl", context), "ytl", context)
    x_max = _parse_float(_require_attr(box_elem, "xbr", context), "xbr", context)
    y_max = _parse_float(_require_attr(box_elem, "ybr", context), "ybr", context)

    occluded_raw = box_elem.get("occluded", "0")
    occluded = occluded_raw == "1"

    # Collect object-level <attribute> children (if any).
    attributes: dict[str, str] = {}
    for attr_elem in box_elem.findall("attribute"):
        attr_name = attr_elem.get("name")
        if attr_name is not None:
            attributes[attr_name] = (attr_elem.text or "").strip()

    return ObjectRecord(
        object_id=object_id,
        image_id=image_id,
        class_name=class_name,
        x_min=x_min,
        y_min=y_min,
        x_max=x_max,
        y_max=y_max,
        occluded=occluded,
        attributes=attributes,
    )


# ── Public API ─────────────────────────────────────────────────────────


def parse_cvat_zip(
    zip_path: str,
    dataset_id: str = "default",
) -> CvatParseResult:
    """Parse a CVAT Images 1.1 ZIP export.

    Parameters
    ----------
    zip_path : str
        Filesystem path to the ``.zip`` file.
    dataset_id : str
        Identifier assigned to every ``ImageRecord.dataset_id``.

    Returns
    -------
    CvatParseResult
        Contains ``images``, ``objects``, and ``skipped_shapes``.

    Raises
    ------
    CvatZipError
        If *zip_path* is not a valid ZIP.
    CvatXmlNotFoundError
        If the ZIP contains no XML files.
    CvatMultipleXmlError
        If the ZIP contains multiple XML files.
    CvatXmlSyntaxError
        If the XML is malformed.
    CvatMissingAttributeError
        If a required attribute is missing from an ``<image>`` or ``<box>``.
    CvatInvalidValueError
        If a numeric attribute cannot be parsed.
    """
    # 1. Open the ZIP safely.
    try:
        zf = zipfile.ZipFile(zip_path, "r")
    except zipfile.BadZipFile as exc:
        raise CvatZipError(f"Not a valid ZIP file: {zip_path}") from exc
    except FileNotFoundError as exc:
        raise CvatZipError(f"File not found: {zip_path}") from exc

    with zf:
        # 2. Locate the single XML member.
        xml_member = _find_single_xml(zf)

        # 3. Read & parse the XML.
        raw_xml = zf.read(xml_member)

    try:
        root = fromstring(raw_xml)
    except ParseError as exc:
        raise CvatXmlSyntaxError(
            f"Malformed XML in '{xml_member}': {exc}"
        ) from exc

    # 4. Iterate over <image> elements.
    images: list[ImageRecord] = []
    objects: list[ObjectRecord] = []
    skipped_shapes: dict[str, int] = {}

    for image_elem in root.findall("image"):
        context = f"<image id='{image_elem.get('id', '?')}'>"

        image_id = _require_attr(image_elem, "id", context)
        image_name = _require_attr(image_elem, "name", context)
        width = _parse_int(
            _require_attr(image_elem, "width", context), "width", context
        )
        height = _parse_int(
            _require_attr(image_elem, "height", context), "height", context
        )

        # Scene-level metadata.
        timeofday, weather = _extract_scene_info(image_elem)

        images.append(
            ImageRecord(
                dataset_id=dataset_id,
                image_id=image_id,
                image_path=image_name,
                width=width,
                height=height,
                timeofday=timeofday,
                weather=weather,
            )
        )

        # Parse child annotations.
        box_index = 0
        for child in image_elem:
            if child.tag == "box":
                objects.append(_parse_box(child, image_id, box_index))
                box_index += 1
            elif child.tag == "tag":
                # Image-level tags (e.g. scene_info) are NOT objects.
                pass
            elif child.tag in _UNSUPPORTED_SHAPES:
                skipped_shapes[child.tag] = (
                    skipped_shapes.get(child.tag, 0) + 1
                )

    return CvatParseResult(
        images=images,
        objects=objects,
        skipped_shapes=skipped_shapes,
    )
