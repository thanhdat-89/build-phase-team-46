"""Integration projections preserve provenance, measured values and safe links."""
import copy
import csv
import io
import json
from dataclasses import replace

import pytest
from core.coverage_config import CoverageConfig, SliceDefinition
from core.coverage_export import METRICS_CSV_HEADERS, RECOMMENDATIONS_CSV_HEADERS, AFFECTED_IMAGES_CSV_HEADERS
from core.schema import ImageRecord, ObjectRecord
from ui.coverage import CoverageSnapshot, recalculate_coverage
from ui.reports import (import_provenance, synchronize_import, clear_import_state,
                        validate_mapping_sidecar, prepare_exports)


def fixture():
    images = [ImageRecord(dataset_id="ds", image_id="actual_parent", image_path="images/p.jpg", width=100, height=100, timeofday="night")]
    objects = [ObjectRecord(dataset_id="ds", object_id="misleading_obj1", image_id="actual_parent", class_name="person", x_min=0, y_min=0, x_max=10, y_max=10)]
    config = CoverageConfig(slices=[SliceDefinition(id="s", name="Persons", unit="object", filters={"class_name": "person", "timeofday": "night"}, target_count=2, weight=3)])
    _, version = import_provenance(images, objects)
    results, metrics, recs = recalculate_coverage(images, objects, config, dataset_version=version, include_skipped=True)
    return CoverageSnapshot(config, results, metrics, recs, version), images, objects


def rows(text):
    return list(csv.DictReader(io.StringIO(text)))


def test_bundle_headers_versions_parents_and_no_mutation():
    snapshot, images, objects = fixture()
    original = copy.deepcopy((snapshot, images, objects))
    url = "https://cvat.example/tasks/12/jobs/15?frame=7"
    bundle = prepare_exports(snapshot, images, objects, {images[0].image_key: {"confirmed": True, "url": url}})
    assert list(bundle.to_dict()) == ["metrics.csv", "recommendations.csv", "affected_images.csv", "config.json"]
    for text, headers in [(bundle.metrics_csv, METRICS_CSV_HEADERS), (bundle.recommendations_csv, RECOMMENDATIONS_CSV_HEADERS), (bundle.affected_images_csv, AFFECTED_IMAGES_CSV_HEADERS)]:
        assert next(csv.reader(io.StringIO(text))) == headers
        assert all(r["dataset_version"] == snapshot.dataset_version and r["config_version"] == snapshot.config.config_version for r in rows(text))
    affected = rows(bundle.affected_images_csv)
    assert affected and all(r["image_key"] == "ds:actual_parent" and r["image_path"] == "images/p.jpg" and r["cvat_url"] == url for r in affected)
    assert json.loads(bundle.config_json)["dataset_version"] == snapshot.dataset_version
    assert (snapshot, images, objects) == original
    skipped = [r for r in rows(bundle.recommendations_csv) if r["evidence_status"] == "not_available"]
    assert skipped and all(r["support"] == r["attainment"] == r["priority"] == "" for r in skipped)
    assert rows(bundle.metrics_csv)[0]["support"] == "1"


@pytest.mark.parametrize("kind", ["stale", "short", "unconfirmed", "invalid", "extra", "ambiguous"])
def test_mapping_sidecar_rejected(kind):
    snapshot, images, _ = fixture()
    raw = {"dataset_version": snapshot.dataset_version, "mappings": {images[0].image_key: {"confirmed": True, "url": "https://cvat.example/tasks/1?frame=0"}}}
    if kind == "stale": raw["dataset_version"] = "old"
    if kind == "short": raw["mappings"] = {"actual_parent": next(iter(raw["mappings"].values()))}
    if kind == "unconfirmed": raw["mappings"][images[0].image_key]["confirmed"] = False
    if kind == "invalid": raw["mappings"][images[0].image_key]["url"] = "https://cvat.example/"
    if kind == "extra": raw["mappings"][images[0].image_key]["unexpected"] = True
    if kind == "ambiguous": images = images * 2
    with pytest.raises(ValueError): validate_mapping_sidecar(raw, images, snapshot.dataset_version)


def test_valid_sidecar_and_fallbacks():
    snapshot, images, objects = fixture()
    mapping = {images[0].image_key: {"confirmed": True, "task_id": 1, "frame": 0, "base_url": "https://cvat.example"}}
    assert validate_mapping_sidecar({"dataset_version": snapshot.dataset_version, "mappings": mapping}, images, snapshot.dataset_version) == mapping
    for path in ["images/p.jpg", ""]:
        changed = [replace(images[0], image_path=path)]
        affected = rows(prepare_exports(snapshot, changed, objects, {images[0].image_key: {"confirmed": False}}).affected_images_csv)
        assert all(r["cvat_url"] == "" and r["image_path"] == (path or images[0].image_key) for r in affected)


def test_provenance_and_lifecycle():
    snapshot, images, objects = fixture()
    identity, version = import_provenance(images, objects)
    assert import_provenance(list(reversed(images)), objects)[1] == version
    assert import_provenance([replace(images[0], image_path="changed")], objects)[1] != version
    state = {"unrelated": 42}
    synchronize_import(state, identity, version)
    state["coverage_config"] = snapshot.config
    synchronize_import(state, identity, "revised")
    assert state["coverage_config"] is snapshot.config
    synchronize_import(state, ("other",), "new")
    assert "coverage_config" not in state
    state["coverage_recommendations"] = []
    clear_import_state(state)
    assert state == {"unrelated": 42}


def test_empty_explicit_recommendations_no_auto_generation():
    snapshot, _, _ = fixture()
    snapshot = replace(snapshot, slice_results={}, recommendations=[])
    bundle = prepare_exports(snapshot, [], [])
    assert rows(bundle.metrics_csv) == rows(bundle.recommendations_csv) == rows(bundle.affected_images_csv) == []

def test_zero_denominator_export_versus_valid_measured_zero():
    snapshot, images, _ = fixture()
    cfg = snapshot.config
    results, dataset, recs = recalculate_coverage(images, [], cfg, include_skipped=True)
    empty_objects = CoverageSnapshot(cfg, results, dataset, recs, snapshot.dataset_version)
    exported = rows(prepare_exports(empty_objects, images, []).metrics_csv)[0]
    assert exported["support"] == "0" and exported["metadata_availability"] == ""
    unknown_images = [replace(images[0], timeofday=None)]
    _, _, objects = fixture()
    results, dataset, recs = recalculate_coverage(unknown_images, objects, cfg, include_skipped=True)
    provisional = CoverageSnapshot(cfg, results, dataset, recs, snapshot.dataset_version)
    exported = rows(prepare_exports(provisional, unknown_images, objects).metrics_csv)[0]
    assert json.loads(exported["metadata_availability"])["timeofday"] == 0.0
    assert exported["unresolved_count"] == "1" and not dataset.targets_met


def test_rendered_downloads_exact_names_mime_and_payload():
    from unittest.mock import patch
    from streamlit.testing.v1 import AppTest
    from ui.reports import render_reports
    import streamlit as st
    def script():
        from test_reports_ui import fixture
        from ui.reports import render_reports
        snapshot, images, objects = fixture()
        render_reports(snapshot, images, objects)
    with patch("streamlit.download_button", wraps=st.download_button) as download:
        at = AppTest.from_function(script).run()
    assert not at.exception
    assert [call.kwargs["file_name"] for call in download.call_args_list] == ["metrics.csv", "recommendations.csv", "affected_images.csv", "config.json"]
    for call in download.call_args_list:
        name = call.kwargs["file_name"]
        assert call.kwargs["mime"] == ("application/json" if name.endswith("json") else "text/csv")
        payload = call.args[1].decode("utf-8")
        if name == "config.json": assert json.loads(payload)["dataset_version"].startswith("normalized-sha256:")
        else: assert "dataset_version" in next(csv.reader(io.StringIO(payload)))

@pytest.mark.parametrize("payload", [b'{bad json', b'{"dataset_version":"stale","mappings":{}}', b'{"unexpected":true}'])
def test_actual_mapping_renderer_rejects_invalid_sidecars_with_safe_downloads(payload):
    from unittest.mock import patch
    from streamlit.testing.v1 import AppTest
    import streamlit as st
    def script():
        from test_reports_ui import fixture
        from ui.reports import render_mapping_input, render_reports
        from ui.recommendations import render_recommendations
        snapshot, images, objects = fixture()
        mappings = render_mapping_input(images, snapshot.dataset_version)
        render_recommendations(snapshot.recommendations, images=images, objects=objects,
                               slice_results=snapshot.slice_results, config=snapshot.config, cvat_mapping=mappings)
        render_reports(snapshot, images, objects, mappings)
    with patch("streamlit.file_uploader", return_value=io.BytesIO(payload)), patch("streamlit.download_button", wraps=st.download_button) as download:
        at = AppTest.from_function(script).run()
    assert not at.exception
    assert any("Mapping rejected; using paths/keys" in warning.value for warning in at.warning)
    assert not at.get("link_button")
    assert any("images/p.jpg" in text.value for text in at.text)
    affected = next(c.args[1].decode() for c in download.call_args_list if c.kwargs["file_name"] == "affected_images.csv")
    exported = rows(affected)
    assert exported and all(r["cvat_url"] == "" and r["image_path"] == "images/p.jpg" for r in exported)


def test_ambiguous_parent_exports_excluded_without_mutation():
    snapshot, images, objects = fixture()
    second_image = replace(images[0], image_id="second", image_path="images/second.jpg")
    ambiguous_objects = objects + [replace(objects[0], image_id="second")]
    original = copy.deepcopy((snapshot, images, ambiguous_objects))
    bundle = prepare_exports(snapshot, images + [second_image], ambiguous_objects)
    assert rows(bundle.affected_images_csv) == []
    assert all(r["affected_image_keys"] == "" for r in rows(bundle.recommendations_csv))
    assert (snapshot, images, ambiguous_objects) == original


def test_empty_objects_shared_ui_and_export_evidence():
    from streamlit.testing.v1 import AppTest
    def script():
        from test_reports_ui import fixture
        from ui.coverage import render_coverage
        from ui.recommendations import render_recommendations
        from ui.reports import render_reports
        example, images, _ = fixture()
        current = render_coverage(images, objects=[], config=example.config,
                                  dataset_version=example.dataset_version)
        render_recommendations(current.recommendations, images=images, objects=[],
                               slice_results=current.slice_results, config=current.config)
        render_reports(current, images, [])
    at = AppTest.from_function(script).run()
    assert not at.exception
    assert at.dataframe[0].value.iloc[0]["metadata_availability"] == "N/A"
    assert any("Metadata availability: N/A" in text.value for text in at.text)
    assert not any("R06" in text.value for text in at.text)
    snapshot, images, _ = fixture()
    results, dataset, recs = recalculate_coverage(images, [], snapshot.config)
    snapshot = replace(snapshot, slice_results=results, dataset_result=dataset, recommendations=recs)
    bundle = prepare_exports(snapshot, images, [])
    assert rows(bundle.metrics_csv)[0]["metadata_availability"] == ""
    assert all("R06" not in row["rule_ids"] and row["evidence_status"] != "unresolved_metadata" for row in rows(bundle.recommendations_csv))
