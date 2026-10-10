"""Deterministic unit tests for Phase 4.1 Coverage Export Layer.

Verifies specification requirements and acceptance criteria from:
- FEEDBACK/Recommended-solution_DAT/Coverage_Recommendation_Engine_Coding_Spec_N2-05B.md §8, §9
- FEEDBACK/Recommended-solution_DAT/Co_so_ly_thuyet_Data_Quality_Coverage_N2-05B.md §6, §12

Test coverage:
1. Exact headers for all CSV artifacts
2. Empty exports handling (preserving headers, 0 data rows, valid JSON)
3. Version metadata propagation (config_version, dataset_version)
4. Unit field presence and accuracy in applicable CSV records
5. Missing optional inputs safety (images=None, cvat_mapping=None, etc.)
6. Image-path and image-key fallback when CVAT links are unavailable
7. Valid CVAT mappings (task/job/frame, direct url, custom base_url, functions)
8. Never fabricating image records or CVAT links on zero support
9. Deterministic output across multiple runs
10. Overlapping slices: never summing slice gaps into a total collection number
11. Directory export and bundle serialization
12. End-to-end integration with Phase 1-3 components
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pytest

from core.coverage_config import CoverageConfig, MetadataPolicy, SliceDefinition
from core.coverage_export import (
    AFFECTED_IMAGES_CSV_HEADERS,
    METRICS_CSV_HEADERS,
    RECOMMENDATIONS_CSV_HEADERS,
    CoverageExportBundle,
    export_affected_images_csv,
    export_config_json,
    export_coverage_bundle,
    export_metrics_csv,
    export_recommendations_csv,
    resolve_cvat_url,
)
from core.coverage_metrics import calculate_dataset_coverage, calculate_slice_metrics
from core.recommendations import Recommendation, recommend
from core.schema import ImageRecord, ObjectRecord
from core.slice_engine import SliceEvaluationResult, evaluate_slice


# ---------------------------------------------------------------------------
# Test Fixture Helpers
# ---------------------------------------------------------------------------

def _slice(
    slice_id: str = "s1",
    name: str = "Slice 1",
    unit: str = "image",
    filters: dict | None = None,
    target_count: int = 50,
    weight: float = 1.0,
    enabled: bool = True,
    feasibility: str = "confirmed",
) -> SliceDefinition:
    return SliceDefinition(
        id=slice_id,
        name=name,
        unit=unit,
        filters=filters or {"contains_class": "person"},
        target_count=target_count,
        weight=weight,
        enabled=enabled,
        feasibility=feasibility,
        target_reason="Test target reason",
    )


def _eval_result(
    slice_id: str = "s1",
    slice_name: str = "Slice 1",
    unit: str = "image",
    support: int = 10,
    target_count: int = 50,
    weight: float = 1.0,
    matched_keys: list[str] | None = None,
    unresolved_count: int = 0,
    unresolved_keys: list[str] | None = None,
    source_support: int | None = None,
    source_support_status: str = "not_available",
    metadata_availability: dict[str, float] | None = None,
    status: str = "below_target",
) -> SliceEvaluationResult:
    gap = max(0, target_count - support)
    attainment = min(support / target_count, 1.0) if target_count > 0 else 1.0
    priority = weight * (1.0 - attainment)
    return SliceEvaluationResult(
        slice_id=slice_id,
        slice_name=slice_name,
        unit=unit,
        support=support,
        target_count=target_count,
        weight=weight,
        gap=gap,
        attainment=attainment,
        priority=priority,
        matched_keys=matched_keys if matched_keys is not None else [f"ds1:img_{i}" for i in range(support)],
        unresolved_count=unresolved_count,
        unresolved_keys=unresolved_keys if unresolved_keys is not None else [f"ds1:unres_{i}" for i in range(unresolved_count)],
        source_support=source_support,
        source_support_status=source_support_status,
        metadata_availability=metadata_availability or {},
        status=status,
    )


def _img(
    img_id: str = "img1",
    dataset_id: str = "ds1",
    timeofday: str | None = "day",
    weather: str | None = "clear",
    image_path: str | None = None,
) -> ImageRecord:
    return ImageRecord(
        dataset_id=dataset_id,
        image_id=img_id,
        image_path=image_path or f"/data/{dataset_id}/{img_id}.jpg",
        width=1920,
        height=1080,
        timeofday=timeofday,
        weather=weather,
    )


def _parse_csv_lines(csv_text: str) -> list[list[str]]:
    reader = csv.reader(io.StringIO(csv_text))
    return list(reader)


# ===========================================================================
# 1. Exact Headers Tests
# ===========================================================================

class TestExactHeaders:
    """Verifies that each CSV artifact produces the exact expected headers."""

    def test_metrics_csv_exact_headers(self):
        csv_text = export_metrics_csv()
        rows = _parse_csv_lines(csv_text)
        assert len(rows) == 1  # Only header row
        assert rows[0] == METRICS_CSV_HEADERS
        assert "unit" in rows[0]
        assert "config_version" in rows[0]
        assert "dataset_version" in rows[0]

    def test_recommendations_csv_exact_headers(self):
        csv_text = export_recommendations_csv()
        rows = _parse_csv_lines(csv_text)
        assert len(rows) == 1
        assert rows[0] == RECOMMENDATIONS_CSV_HEADERS
        assert "unit" in rows[0]
        assert "config_version" in rows[0]
        assert "dataset_version" in rows[0]

    def test_affected_images_csv_exact_headers(self):
        csv_text = export_affected_images_csv()
        rows = _parse_csv_lines(csv_text)
        assert len(rows) == 1
        assert rows[0] == AFFECTED_IMAGES_CSV_HEADERS
        assert "unit" in rows[0]
        assert "config_version" in rows[0]
        assert "dataset_version" in rows[0]
        assert "image_key" in rows[0]
        assert "image_path" in rows[0]
        assert "cvat_url" in rows[0]


# ===========================================================================
# 2. Empty Exports Tests
# ===========================================================================

class TestEmptyExports:
    """Verifies safe handling of empty data across all four artifacts."""

    def test_empty_metrics_csv(self):
        csv_text = export_metrics_csv(slice_results=[])
        rows = _parse_csv_lines(csv_text)
        assert len(rows) == 1
        assert rows[0] == METRICS_CSV_HEADERS

    def test_empty_recommendations_csv(self):
        csv_text = export_recommendations_csv([])
        rows = _parse_csv_lines(csv_text)
        assert len(rows) == 1
        assert rows[0] == RECOMMENDATIONS_CSV_HEADERS

    def test_empty_affected_images_csv(self):
        csv_text = export_affected_images_csv([])
        rows = _parse_csv_lines(csv_text)
        assert len(rows) == 1
        assert rows[0] == AFFECTED_IMAGES_CSV_HEADERS

    def test_empty_config_json(self):
        json_text = export_config_json(None)
        data = json.loads(json_text)
        assert data["definition_version"] == "1.0"
        assert data["config_version"] == "1"
        assert data["slices"] == []
        assert isinstance(data["metadata_policy"], dict)

    def test_empty_bundle_export(self):
        bundle = export_coverage_bundle(
            slice_results=[],
            recommendations=[],
            config=None,
        )
        assert len(_parse_csv_lines(bundle.metrics_csv)) == 1
        assert len(_parse_csv_lines(bundle.recommendations_csv)) == 1
        assert len(_parse_csv_lines(bundle.affected_images_csv)) == 1
        cfg_data = json.loads(bundle.config_json)
        assert cfg_data["slices"] == []


# ===========================================================================
# 3. Version Metadata Propagation
# ===========================================================================

class TestVersionMetadata:
    """Verifies config_version and dataset_version propagation across all outputs."""

    def test_version_metadata_in_all_artifacts(self):
        s = _slice("s1", target_count=50)
        res = _eval_result("s1", support=10, target_count=50)
        cfg = CoverageConfig(config_version="v3.2", slices=[s])

        bundle = export_coverage_bundle(
            slice_results={"s1": res},
            config=cfg,
            dataset_version="export_2026_10_09",
        )

        # 1. metrics.csv
        m_rows = _parse_csv_lines(bundle.metrics_csv)
        assert len(m_rows) == 2
        m_dict = dict(zip(m_rows[0], m_rows[1]))
        assert m_dict["config_version"] == "v3.2"
        assert m_dict["dataset_version"] == "export_2026_10_09"

        # 2. recommendations.csv
        r_rows = _parse_csv_lines(bundle.recommendations_csv)
        assert len(r_rows) >= 2
        r_dict = dict(zip(r_rows[0], r_rows[1]))
        assert r_dict["config_version"] == "v3.2"
        assert r_dict["dataset_version"] == "export_2026_10_09"

        # 3. affected_images.csv
        a_rows = _parse_csv_lines(bundle.affected_images_csv)
        assert len(a_rows) >= 2
        a_dict = dict(zip(a_rows[0], a_rows[1]))
        assert a_dict["config_version"] == "v3.2"
        assert a_dict["dataset_version"] == "export_2026_10_09"

        # 4. config.json
        cfg_data = json.loads(bundle.config_json)
        assert cfg_data["config_version"] == "v3.2"

    def test_explicit_config_version_override(self):
        s = _slice("s1")
        res = _eval_result("s1")
        cfg = CoverageConfig(config_version="original_v1", slices=[s])

        bundle = export_coverage_bundle(
            slice_results={"s1": res},
            config=cfg,
            config_version="override_v2",
            dataset_version="ds_snap_42",
        )

        m_rows = _parse_csv_lines(bundle.metrics_csv)
        assert m_rows[1][m_rows[0].index("config_version")] == "override_v2"
        assert m_rows[1][m_rows[0].index("dataset_version")] == "ds_snap_42"


# ===========================================================================
# 4. Unit Field Presence
# ===========================================================================

class TestUnitField:
    """Verifies that unit ('image' or 'object') is properly preserved in all CSVs."""

    def test_image_and_object_units_preserved(self):
        s_img = _slice("s_image", unit="image", target_count=10)
        res_img = _eval_result("s_image", unit="image", support=5, target_count=10)

        s_obj = _slice("s_obj", unit="object", target_count=20)
        res_obj = _eval_result("s_obj", unit="object", support=8, target_count=20)

        cfg = CoverageConfig(slices=[s_img, s_obj])

        bundle = export_coverage_bundle(
            slice_results={"s_image": res_img, "s_obj": res_obj},
            config=cfg,
        )

        # In metrics.csv
        m_rows = _parse_csv_lines(bundle.metrics_csv)
        assert len(m_rows) == 3
        unit_idx = m_rows[0].index("unit")
        slice_idx = m_rows[0].index("slice_id")
        units_by_slice = {row[slice_idx]: row[unit_idx] for row in m_rows[1:]}
        assert units_by_slice["s_image"] == "image"
        assert units_by_slice["s_obj"] == "object"

        # In recommendations.csv
        r_rows = _parse_csv_lines(bundle.recommendations_csv)
        r_unit_idx = r_rows[0].index("unit")
        r_slice_idx = r_rows[0].index("slice_id")
        r_units = {row[r_slice_idx]: row[r_unit_idx] for row in r_rows[1:]}
        assert r_units["s_image"] == "image"
        assert r_units["s_obj"] == "object"

        # In affected_images.csv
        a_rows = _parse_csv_lines(bundle.affected_images_csv)
        a_unit_idx = a_rows[0].index("unit")
        a_slice_idx = a_rows[0].index("slice_id")
        a_units = {row[a_slice_idx]: row[a_unit_idx] for row in a_rows[1:]}
        assert a_units["s_image"] == "image"
        assert a_units["s_obj"] == "object"


# ===========================================================================
# 5. Missing Optional Inputs Safety
# ===========================================================================

class TestOptionalInputsSafety:
    """Verifies that missing optional inputs do not crash and produce safe outputs."""

    def test_all_optional_inputs_omitted_or_none(self):
        bundle = export_coverage_bundle()
        assert isinstance(bundle, CoverageExportBundle)
        assert bundle.metrics_csv.startswith("slice_id,")
        assert bundle.recommendations_csv.startswith("recommendation_id,")
        assert bundle.affected_images_csv.startswith("recommendation_id,")
        assert json.loads(bundle.config_json)["slices"] == []

    def test_images_none_safely_falls_back(self):
        rec = Recommendation(
            recommendation_id="rec1",
            slice_id="s1",
            rule_ids=["R02"],
            category="collection_gap",
            severity="planning",
            evidence_status="observed_annotation",
            support=1,
            target=10,
            gap=9,
            attainment=0.1,
            priority=0.9,
            unit="image",
            title="Title",
            actions=["Action"],
            remeasure=["support"],
            limitations=[],
            affected_image_keys=["ds1:img_fallback_1"],
        )

        csv_text = export_affected_images_csv(
            recommendations=[rec],
            images=None,  # Missing optional input
            cvat_mapping=None,  # Missing optional input
        )
        rows = _parse_csv_lines(csv_text)
        assert len(rows) == 2
        row_dict = dict(zip(rows[0], rows[1]))
        assert row_dict["image_key"] == "ds1:img_fallback_1"
        assert row_dict["image_path"] == "ds1:img_fallback_1"  # Safely fell back to image_key
        assert row_dict["cvat_url"] == ""

    def test_dataset_coverage_result_input_supported(self):
        s = _slice("s1", target_count=10)
        res = _eval_result("s1", support=5, target_count=10)
        ds_cov = calculate_dataset_coverage([res])

        csv_text = export_metrics_csv(slice_results=ds_cov)
        rows = _parse_csv_lines(csv_text)
        assert len(rows) == 2
        assert rows[1][rows[0].index("slice_id")] == "s1"
        assert rows[1][rows[0].index("support")] == "5"

    def test_preformatted_metric_dict_input_supported(self):
        """Preformatted metric dictionaries conforming to slice metrics are safely exported."""
        dict_metrics = {
            "s_preformatted": {
                "slice_id": "s_preformatted",
                "slice_name": "Preformatted Slice",
                "unit": "image",
                "support": 15,
                "target_count": 20,
                "weight": 2.0,
                "gap": 5,
                "attainment": 0.75,
                "priority": 0.5,
                "unresolved_count": 0,
                "source_support": 3,
                "source_support_status": "available",
                "metadata_availability": {"timeofday": 1.0},
                "excluded_invalid_geometry_count": 0,
                "status": "below_target",
            }
        }
        csv_text = export_metrics_csv(slice_results=dict_metrics)
        rows = _parse_csv_lines(csv_text)
        assert len(rows) == 2
        d = dict(zip(rows[0], rows[1]))
        assert d["slice_id"] == "s_preformatted"
        assert d["support"] == "15"
        assert d["target_count"] == "20"
        assert d["gap"] == "5"
        assert d["attainment"] == "0.75"
        assert d["priority"] == "0.5"

        # Also list of dicts
        list_metrics = [dict_metrics["s_preformatted"]]
        csv_text_list = export_metrics_csv(slice_results=list_metrics)
        assert csv_text == csv_text_list


# ===========================================================================
# 6. CVAT Mapping and Image-Path Fallback
# ===========================================================================

class TestCvatMappingAndFallback:
    """Verifies that CVAT links are never fabricated and valid mappings are resolved."""

    def test_valid_task_job_frame_dict_mapping(self):
        mapping = {
            "ds1:img_1": {
                "task_id": 42,
                "job_id": 108,
                "frame": 15,
                "base_url": "https://cvat.custom-domain.org",
            }
        }
        url = resolve_cvat_url("ds1:img_1", cvat_mapping=mapping)
        assert url == "https://cvat.custom-domain.org/tasks/42/jobs/108?frame=15"

    def test_valid_task_frame_without_job_mapping(self):
        mapping = {
            "ds1:img_2": {
                "task_id": 42,
                "frame": 7,
                "base_url": "https://app.cvat.ai",
            }
        }
        url = resolve_cvat_url("ds1:img_2", cvat_mapping=mapping)
        assert url == "https://app.cvat.ai/tasks/42?frame=7"

    def test_direct_url_string_mapping(self):
        mapping = {
            "ds1:img_3": "https://cvat.org/tasks/99/jobs/100?frame=0"
        }
        url = resolve_cvat_url("ds1:img_3", cvat_mapping=mapping)
        assert url == "https://cvat.org/tasks/99/jobs/100?frame=0"

    def test_callable_cvat_mapping(self):
        def _mapper(k: str) -> str | None:
            if k == "ds1:img_4":
                return "https://cvat.org/tasks/1/jobs/1?frame=4"
            return None

        url = resolve_cvat_url("ds1:img_4", cvat_mapping=_mapper)
        assert url == "https://cvat.org/tasks/1/jobs/1?frame=4"

        url_missing = resolve_cvat_url("ds1:unknown", cvat_mapping=_mapper)
        assert url_missing == ""

    def test_incomplete_mapping_never_fabricates_link(self):
        # Missing task_id or frame
        bad_mappings = [
            {"ds1:img_bad": {"job_id": 10}},  # No task_id, no frame
            {"ds1:img_bad": {"task_id": 10}},  # No frame
            {"ds1:img_bad": "not-a-valid-http-url"},  # Invalid URL string
            {"ds1:img_bad": {"url": "ftp://bad-proto"}},
        ]
        for bm in bad_mappings:
            url = resolve_cvat_url("ds1:img_bad", cvat_mapping=bm)
            assert url == "", f"Should not fabricate URL for bad mapping: {bm}"

    def test_fallback_to_actual_image_path(self):
        img = _img("img_foo", dataset_id="ds1", image_path="/data/storage/night/img_foo.png")
        rec = Recommendation(
            recommendation_id="rec_foo",
            slice_id="s_foo",
            rule_ids=["R02"],
            category="collection_gap",
            severity="planning",
            evidence_status="observed_annotation",
            support=1,
            target=5,
            gap=4,
            attainment=0.2,
            priority=0.8,
            unit="image",
            title="Title",
            actions=["Action"],
            remeasure=["support"],
            limitations=[],
            affected_image_keys=["ds1:img_foo"],
        )

        csv_text = export_affected_images_csv(
            recommendations=[rec],
            images=[img],
            cvat_mapping=None,  # No mapping available
        )
        rows = _parse_csv_lines(csv_text)
        assert len(rows) == 2
        d = dict(zip(rows[0], rows[1]))
        assert d["image_key"] == "ds1:img_foo"
        assert d["image_path"] == "/data/storage/night/img_foo.png"  # Uses actual image_path!
        assert d["cvat_url"] == ""  # Never fabricated

    def test_missing_cvat_base_url_never_assumes_cloud_and_falls_back(self):
        """When CVAT host is unknown/unspecified, never assume cloud cvat.ai; return empty URL and fallback."""
        mapping_without_base = {
            "ds1:img_local": {
                "task_id": 12,
                "job_id": 34,
                "frame": 5,
                # Explicitly omitting base_url
            }
        }
        url = resolve_cvat_url("ds1:img_local", cvat_mapping=mapping_without_base)
        assert url == ""  # Does NOT silently default to https://app.cvat.ai!

        # Also verify affected images CSV exports empty cvat_url and keeps image_path
        img = _img("img_local", dataset_id="ds1", image_path="/local/store/img_local.png")
        rec = Recommendation(
            recommendation_id="rec_local",
            slice_id="s_local",
            rule_ids=["R02"],
            category="collection_gap",
            severity="planning",
            evidence_status="observed_annotation",
            support=1,
            target=5,
            gap=4,
            attainment=0.2,
            priority=0.8,
            unit="image",
            title="Title",
            actions=["Action"],
            remeasure=["support"],
            limitations=[],
            affected_image_keys=["ds1:img_local"],
        )
        csv_text = export_affected_images_csv(
            recommendations=[rec],
            images=[img],
            cvat_mapping=mapping_without_base,
        )
        rows = _parse_csv_lines(csv_text)
        d = dict(zip(rows[0], rows[1]))
        assert d["cvat_url"] == ""
        assert d["image_path"] == "/local/store/img_local.png"

    def test_local_onpremise_cvat_base_url_supported(self):
        """Local on-premise CVAT hosts (e.g. http://localhost:8080) are properly formatted."""
        # 1. Via mapping dict base_url
        mapping_local = {
            "ds1:img_local": {
                "task_id": 12,
                "job_id": 34,
                "frame": 5,
                "base_url": "http://localhost:8080",
            }
        }
        url = resolve_cvat_url("ds1:img_local", cvat_mapping=mapping_local)
        assert url == "http://localhost:8080/tasks/12/jobs/34?frame=5"

        # 2. Via base_url parameter
        mapping_no_base = {
            "ds1:img_local2": {
                "task_id": 99,
                "frame": 10,
            }
        }
        url2 = resolve_cvat_url("ds1:img_local2", cvat_mapping=mapping_no_base, base_url="http://192.168.1.50:8080")
        assert url2 == "http://192.168.1.50:8080/tasks/99?frame=10"


# ===========================================================================
# 7. Zero Support Never Fabricates Image Records
# ===========================================================================

class TestZeroSupportNoFabrication:
    """Verifies that R01 / zero support slices emit zero fake affected image records."""

    def test_zero_support_affected_images_empty(self):
        s = _slice("s_zero", target_count=50, weight=3.0)
        res = _eval_result("s_zero", support=0, target_count=50, weight=3.0, matched_keys=[])
        cfg = CoverageConfig(slices=[s])

        bundle = export_coverage_bundle(
            slice_results={"s_zero": res},
            config=cfg,
        )

        r_rows = _parse_csv_lines(bundle.recommendations_csv)
        assert len(r_rows) == 2  # Has recommendation for s_zero
        assert r_rows[1][r_rows[0].index("support")] == "0"
        assert r_rows[1][r_rows[0].index("affected_image_keys")] == ""

        # affected_images.csv must NOT fabricate fake records
        a_rows = _parse_csv_lines(bundle.affected_images_csv)
        assert len(a_rows) == 1  # Only header row, 0 data rows!


# ===========================================================================
# 8. Deterministic Output Tests
# ===========================================================================

class TestDeterministicOutput:
    """Verifies that export output is 100% deterministic and ordered."""

    def test_deterministic_bundle_output(self):
        s1 = _slice("z_slice", target_count=20)
        s2 = _slice("a_slice", target_count=30)
        res1 = _eval_result("z_slice", support=10, target_count=20)
        res2 = _eval_result("a_slice", support=5, target_count=30)

        cfg = CoverageConfig(slices=[s1, s2])

        bundle_1 = export_coverage_bundle(
            slice_results={"z_slice": res1, "a_slice": res2},
            config=cfg,
            dataset_version="v1",
        )
        bundle_2 = export_coverage_bundle(
            slice_results={"z_slice": res1, "a_slice": res2},
            config=cfg,
            dataset_version="v1",
        )

        assert bundle_1.metrics_csv == bundle_2.metrics_csv
        assert bundle_1.recommendations_csv == bundle_2.recommendations_csv
        assert bundle_1.affected_images_csv == bundle_2.affected_images_csv
        assert bundle_1.config_json == bundle_2.config_json

    def test_metrics_csv_sorted_by_slice_id(self):
        s_c = _slice("slice_c")
        s_a = _slice("slice_a")
        s_b = _slice("slice_b")
        res_c = _eval_result("slice_c")
        res_a = _eval_result("slice_a")
        res_b = _eval_result("slice_b")

        csv_text = export_metrics_csv(slice_results=[res_c, res_a, res_b])
        rows = _parse_csv_lines(csv_text)
        slice_ids = [r[0] for r in rows[1:]]
        assert slice_ids == ["slice_a", "slice_b", "slice_c"]


# ===========================================================================
# 9. Overlapping Slices & Never Summing Gaps
# ===========================================================================

class TestOverlappingSlices:
    """Verifies that overlapping slice gaps are never summed into a collection total."""

    def test_overlapping_slice_gaps_never_summed(self):
        # Slice A: person + night (gap = 40)
        s_a = _slice("person_night", target_count=50, weight=2.0)
        res_a = _eval_result(
            "person_night",
            support=10,
            target_count=50,
            matched_keys=[f"img_{i}" for i in range(10)],
        )

        # Slice B: person + rain (gap = 20)
        # Slices overlap because images can be both night and rain!
        s_b = _slice("person_rain", target_count=30, weight=2.0)
        res_b = _eval_result(
            "person_rain",
            support=10,
            target_count=30,
            # 5 images overlap between the two slices
            matched_keys=[f"img_{i}" for i in range(5, 15)],
        )

        cfg = CoverageConfig(slices=[s_a, s_b])
        bundle = export_coverage_bundle(
            slice_results={"person_night": res_a, "person_rain": res_b},
            config=cfg,
        )

        # In metrics.csv, each slice reports its own gap (40 and 20)
        m_rows = _parse_csv_lines(bundle.metrics_csv)
        gap_idx = m_rows[0].index("gap")
        slice_idx = m_rows[0].index("slice_id")
        gaps = {row[slice_idx]: int(row[gap_idx]) for row in m_rows[1:]}
        assert gaps["person_night"] == 40
        assert gaps["person_rain"] == 20

        # Verify no summary row sums overlapping gaps to 60!
        all_row_texts = [",".join(row) for row in m_rows[1:]]
        for t in all_row_texts:
            assert "total" not in t.lower()
            assert "sum" not in t.lower()

        # In affected_images.csv:
        # Unique affected images across the two slices is |{0..9} union {5..14}| = 15 images
        a_rows = _parse_csv_lines(bundle.affected_images_csv)
        image_key_idx = a_rows[0].index("image_key")
        unique_image_keys = set(row[image_key_idx] for row in a_rows[1:])
        assert len(unique_image_keys) == 15  # 15 distinct images, NOT 40 + 20 = 60!


# ===========================================================================
# 10. File Writing and Bundle Directory Export
# ===========================================================================

class TestDirectoryWriting:
    """Verifies that bundle.write_to_directory creates all 4 files accurately."""

    def test_write_to_directory(self, tmp_path: Path):
        s = _slice("s1")
        res = _eval_result("s1")
        cfg = CoverageConfig(slices=[s])

        out_dir = tmp_path / "coverage_export_test"
        bundle = export_coverage_bundle(
            slice_results={"s1": res},
            config=cfg,
            output_dir=out_dir,
        )

        expected_files = ["metrics.csv", "recommendations.csv", "affected_images.csv", "config.json"]
        for f in expected_files:
            file_path = out_dir / f
            assert file_path.exists(), f"File {f} was not written to disk"
            content = file_path.read_text(encoding="utf-8")
            assert content == bundle.to_dict()[f]


# ===========================================================================
# 11. End-to-End Integration with Phase 1-3
# ===========================================================================

class TestEndToEndPhase1To3Integration:
    """Validates full pipeline from raw ImageRecord/ObjectRecord to exported bundle."""

    def test_end_to_end_pipeline(self, tmp_path: Path):
        # 1. Prepare raw records
        images = [
            _img("img1", timeofday="night", weather="rain", image_path="/imgs/img1.jpg"),
            _img("img2", timeofday="night", weather="clear", image_path="/imgs/img2.jpg"),
            _img("img3", timeofday="day", weather="rain", image_path="/imgs/img3.jpg"),
        ]
        objects = [
            ObjectRecord(
                object_id="o1",
                image_id="img1",
                class_name="person",
                x_min=10,
                y_min=10,
                x_max=50,
                y_max=50,
                dataset_id="ds1",
            ),
            ObjectRecord(
                object_id="o2",
                image_id="img2",
                class_name="person",
                x_min=20,
                y_min=20,
                x_max=60,
                y_max=60,
                dataset_id="ds1",
            ),
        ]

        # 2. Slice configuration
        s_night_rain = SliceDefinition(
            id="person_night_rain",
            name="Person Night Rain",
            unit="image",
            filters={"contains_class": "person", "timeofday": "night", "weather": "rain"},
            target_count=5,
            weight=3.0,
        )
        s_person = SliceDefinition(
            id="person_all",
            name="All Person",
            unit="image",
            filters={"contains_class": "person"},
            target_count=2,
            weight=1.0,
        )
        cfg = CoverageConfig(
            config_version="v1.0",
            slices=[s_night_rain, s_person],
        )

        # 3. Evaluate slices (Phase 2)
        res_nr = evaluate_slice(s_night_rain, images, objects)
        res_all = evaluate_slice(s_person, images, objects)
        slice_results = {"person_night_rain": res_nr, "person_all": res_all}

        # 4. CVAT mapping
        cvat_map = {
            "ds1:img1": {"task_id": 100, "job_id": 200, "frame": 1, "base_url": "https://cvat.team.ai"},
        }

        # 5. Export bundle (Phase 4.1)
        bundle = export_coverage_bundle(
            slice_results=slice_results,
            config=cfg,
            images=images,
            cvat_mapping=cvat_map,
            dataset_version="export_2026_10_09",
            output_dir=tmp_path / "exported",
        )

        # Check metrics.csv
        m_rows = _parse_csv_lines(bundle.metrics_csv)
        assert len(m_rows) == 3
        m_dict_nr = dict(zip(m_rows[0], m_rows[1]))
        assert m_dict_nr["slice_id"] == "person_all"  # Alphabetical sort
        assert m_dict_nr["support"] == "2"
        assert m_dict_nr["target_count"] == "2"
        assert m_dict_nr["gap"] == "0"

        m_dict_all = dict(zip(m_rows[0], m_rows[2]))
        assert m_dict_all["slice_id"] == "person_night_rain"
        assert m_dict_all["support"] == "1"
        assert m_dict_all["target_count"] == "5"
        assert m_dict_all["gap"] == "4"

        # Check recommendations.csv
        r_rows = _parse_csv_lines(bundle.recommendations_csv)
        assert len(r_rows) >= 2

        # Check affected_images.csv
        a_rows = _parse_csv_lines(bundle.affected_images_csv)
        assert len(a_rows) >= 2
        # img1 should have CVAT URL
        rows_with_img1 = [row for row in a_rows[1:] if row[a_rows[0].index("image_key")] == "ds1:img1"]
        assert len(rows_with_img1) > 0
        assert rows_with_img1[0][a_rows[0].index("cvat_url")] == "https://cvat.team.ai/tasks/100/jobs/200?frame=1"
        assert rows_with_img1[0][a_rows[0].index("image_path")] == "/imgs/img1.jpg"

        # Check config.json
        cfg_out = json.loads(bundle.config_json)
        assert len(cfg_out["slices"]) == 2
        assert cfg_out["config_version"] == "v1.0"

@pytest.mark.parametrize("destination", ["url", "task_frame"])
@pytest.mark.parametrize("lookup", ["canonical", "path", "short", "callable"])
@pytest.mark.parametrize("confirmation", [False, None, "true", 1],
                         ids=["false", "null", "string_true", "integer_one"])
def test_explicitly_unconfirmed_cvat_mapping_never_exported(destination, lookup, confirmation):
    import copy
    image = ImageRecord(dataset_id="ds1", image_id="img", image_path="actual/path.jpg", width=100, height=100)
    entry = ({"confirmed": confirmation, "url": "https://cvat.example/tasks/1?frame=0"} if destination == "url"
             else {"confirmed": confirmation, "base_url": "https://cvat.example", "task_id": 1, "frame": 0})
    mapping = (lambda key: entry) if lookup == "callable" else {
        {"canonical": image.image_key, "path": image.image_path, "short": image.image_id}[lookup]: entry}
    original = copy.deepcopy(entry)
    assert resolve_cvat_url(image.image_key, image.image_path, mapping) == ""
    cfg = CoverageConfig(slices=[_slice(target_count=2)])
    evaluation = _eval_result(support=1, target_count=2, matched_keys=[image.image_key])
    recs = recommend({"s1": evaluation}, config=cfg, images=[image])
    assert recs and recs[0].affected_image_keys == [image.image_key]
    bundle = export_coverage_bundle(slice_results={"s1": evaluation}, recommendations=recs,
                                   config=cfg, images=[image], cvat_mapping=mapping,
                                   dataset_version="test-version")
    affected = list(csv.DictReader(io.StringIO(bundle.affected_images_csv)))
    assert affected and all(row["cvat_url"] == "" and row["image_path"] == image.image_path for row in affected)
    assert next(csv.reader(io.StringIO(bundle.affected_images_csv))) == AFFECTED_IMAGES_CSV_HEADERS
    assert entry == original
    entry["confirmed"] = True
    assert resolve_cvat_url(image.image_key, image.image_path, mapping) == "https://cvat.example/tasks/1?frame=0"
