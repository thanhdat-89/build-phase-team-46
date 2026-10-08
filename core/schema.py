
"""Normalized data schema for the CVAT annotation dashboard demo."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ImageRecord:
    """Represents a single image and its scene-level metadata."""

    dataset_id: str
    image_id: str
    image_path: str
    width: int
    height: int
    timeofday: str | None = None
    weather: str | None = None
    metadata_source: str | None = None
    has_scene_conflict: bool = False
    scene_tags: list[dict[str, str | None]] = field(default_factory=list)

    @property
    def image_key(self) -> str:
        """Composite identifier for the image across datasets."""
        return f"{self.dataset_id}:{self.image_id}"


@dataclass
class ObjectRecord:
    """Represents a single annotated object (bounding box) within an image."""

    object_id: str
    image_id: str
    class_name: str
    x_min: float
    y_min: float
    x_max: float
    y_max: float
    occluded: bool = False
    attributes: dict[str, str] = field(default_factory=dict)
    dataset_id: str = "default"

    @property
    def image_key(self) -> str:
        """Composite identifier for the parent image across datasets."""
        return f"{self.dataset_id}:{self.image_id}"

    @property
    def object_key(self) -> str:
        """Composite identifier for the object across datasets."""
        return f"{self.dataset_id}:{self.object_id}"

    @property
    def width(self) -> float:
        """Calculated bounding-box width."""
        return self.x_max - self.x_min

    @property
    def height(self) -> float:
        """Calculated bounding-box height."""
        return self.y_max - self.y_min
