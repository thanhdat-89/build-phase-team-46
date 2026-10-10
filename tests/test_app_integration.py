"""Headless tests exercise the real application entrypoint and reruns."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from streamlit.testing.v1 import AppTest
from test_reports_ui import fixture, rows

ROOT = Path(__file__).resolve().parents[1]


def test_application_shared_snapshot_edit_revision_removal():
    snapshot, images, objects = fixture()
    result = SimpleNamespace(images=images, objects=objects, valid_objects=objects)
    from ui.coverage import recalculate_coverage
    from ui.reports import render_reports
    with patch("ui.upload.render_upload", return_value=result) as upload, patch("ui.overview.render_overview") as overview, patch("ui.coverage.recalculate_coverage", wraps=recalculate_coverage) as calculate, patch("ui.reports.render_reports", wraps=render_reports) as reports:
        at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=15).run()
        assert not at.exception
        assert [t.label for t in at.tabs] == ["Overview", "Coverage & Recommendations", "Reports & Exports"]
        overview.assert_called_with(images=images, valid_objects=objects)
        assert calculate.call_count == 1
        assert len(at.get("download_button")) == 4
        shared = reports.call_args.args[0]
        assert shared.recommendations is at.session_state["coverage_recommendations"]
        at.run()
        assert calculate.call_count == 1
        at.number_input(key="target_input_person_night_rain").set_value(75)
        at.button(key="btn_apply_config").click().run()
        assert not at.exception
        assert at.session_state["coverage_config"].config_version == "2"
        assert calculate.call_count == 2
        latest = reports.call_args.args[0]
        assert latest.config.config_version == "2"
        from ui.reports import prepare_exports
        bundle = prepare_exports(latest, images, objects)
        assert rows(bundle.metrics_csv)[0]["config_version"] == "2"
        assert all(r["config_version"] == "2" for r in rows(bundle.recommendations_csv))
        images[0].image_path = "revised.jpg"
        at.run()
        assert not at.exception and calculate.call_count == 3
        assert at.session_state["coverage_config"].config_version == "2"
        upload.return_value = None
        at.run()
        assert not at.exception and len(at.get("download_button")) == 0
        assert "coverage_config" not in at.session_state


def test_empty_successful_import():
    with patch("ui.upload.render_upload", return_value=SimpleNamespace(images=[], objects=[], valid_objects=[])):
        at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=15).run()
    assert not at.exception
    assert next(m for m in at.metric if m.label == "Độ bao phủ quan sát").value == "N/A"
    assert len(at.get("download_button")) == 4
    assert any("Empty successful import" in x.value for x in at.info)
    assert not at.session_state["coverage_slice_results"]

def test_mapping_only_rerun_refreshes_panel_and_export_without_calculation():
    snapshot, images, objects = fixture()
    result = SimpleNamespace(images=images, objects=objects, valid_objects=objects)
    from ui.coverage import recalculate_coverage
    from ui.reports import render_reports, prepare_exports
    url = "https://cvat.example/tasks/12/jobs/15?frame=7"
    with patch("ui.upload.render_upload", return_value=result), patch("ui.overview.render_overview"), patch("ui.reports.render_mapping_input", return_value={}) as mapping, patch("ui.coverage.recalculate_coverage", wraps=recalculate_coverage) as calculate, patch("ui.reports.render_reports", wraps=render_reports) as reports:
        at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=15).run()
        mapping.return_value = {images[0].image_key: {"confirmed": True, "url": url}}
        at.run()
        assert not at.exception and calculate.call_count == 1
        assert at.get("link_button") and all(link.proto.url == url for link in at.get("link_button"))
        latest, passed_images, passed_objects, maps = reports.call_args.args
        assert all(r["cvat_url"] == url for r in rows(prepare_exports(latest, passed_images, passed_objects, maps).affected_images_csv))
        mapping.return_value = {images[0].image_key: {"confirmed": False, "url": url}}
        at.run()
        assert not at.exception and calculate.call_count == 1 and not at.get("link_button")
        assert any("images/p.jpg" in text.value for text in at.text)


def test_new_identity_resets_edits_and_parse_failure_hides_downloads():
    snapshot, images, objects = fixture()
    result = SimpleNamespace(images=images, objects=objects, valid_objects=objects)
    with patch("ui.upload.render_upload", return_value=result) as upload, patch("ui.overview.render_overview"):
        at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=15).run()
        at.number_input(key="target_input_person_night_rain").set_value(75)
        at.button(key="btn_apply_config").click().run()
        images[0].dataset_id = objects[0].dataset_id = "other"
        at.run()
        assert not at.exception
        assert at.session_state["coverage_config"].config_version == "1"
        assert at.number_input(key="target_input_person_night_rain").value == 50
        # The unchanged upload renderer returns None on parse errors as on removal.
        upload.return_value = None
        at.run()
        assert not at.exception and not at.get("download_button")
        assert "coverage_slice_results" not in at.session_state


def test_weight_and_target_edits_update_visible_evidence_and_download_payloads():
    import csv
    import io
    import json
    import streamlit as st
    snapshot, images, objects = fixture()
    result = SimpleNamespace(images=images, objects=objects, valid_objects=objects)
    with patch("ui.upload.render_upload", return_value=result), patch("ui.overview.render_overview"), patch("streamlit.download_button", wraps=st.download_button) as download:
        at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=15).run()
        download.reset_mock()
        at.number_input(key="target_input_person_night_rain").set_value(75)
        at.number_input(key="weight_input_person_night_rain").set_value(4.5)
        at.button(key="btn_apply_config").click().run()
        assert not at.exception
        payloads = {c.kwargs["file_name"]: c.args[1].decode() for c in download.call_args_list}
        metric = next(r for r in rows(payloads["metrics.csv"]) if r["slice_id"] == "person_night_rain")
        rec = next(r for r in rows(payloads["recommendations.csv"]) if r["slice_id"] == "person_night_rain")
        cfg = json.loads(payloads["config.json"])
        definition = next(s for s in cfg["slices"] if s["id"] == "person_night_rain")
        assert definition["target_count"] == 75 and definition["weight"] == 4.5
        assert metric["target_count"] == rec["target"] == "75"
        assert metric["weight"] == metric["priority"] == rec["priority"] == "4.5"
        assert cfg["config_version"] == metric["config_version"] == rec["config_version"] == "2"
        assert metric["dataset_version"] == rec["dataset_version"] == cfg["dataset_version"]
        assert any("target: 75" in t.value and "priority: 4.5" in t.value for t in at.text)
        assert any("Config: 2" in t.value for t in at.text)


def test_geometry_exclusion_and_r12_caution_rendered_and_exported():
    import json
    import streamlit as st
    from dataclasses import replace
    from core.coverage_config import CoverageConfig, SliceDefinition
    snapshot, images, objects = fixture()
    objects.append(replace(objects[0], object_id="invalid", x_max=-1))
    config = CoverageConfig(slices=[SliceDefinition(id="s", name="Size", unit="object",
                           filters={"class_name": "person", "timeofday": "night", "area_ratio_max": 0.02},
                           target_count=1, weight=1)])
    result = SimpleNamespace(images=images, objects=objects, valid_objects=objects[:1])
    with patch("ui.upload.render_upload", return_value=result), patch("ui.overview.render_overview"), patch("streamlit.download_button", wraps=st.download_button) as download:
        at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=15)
        at.session_state["integration_identity"] = ("ds",)
        at.session_state["coverage_config"] = config
        at.run()
    assert not at.exception
    assert any("Excluded geometry: 1" in t.value for t in at.text)
    assert any("không chứng minh đã hoàn thành kiểm toán" in t.value for t in at.text)
    assert any("không xác nhận kiểm toán đã hoàn thành" in w.value for w in at.warning)
    assert any("R12" in t.value for t in at.text)
    payloads = {c.kwargs["file_name"]: c.args[1].decode() for c in download.call_args_list}
    metric = rows(payloads["metrics.csv"])[0]
    assert metric["support"] == "1" and metric["excluded_invalid_geometry_count"] == "1"
    rec = next(r for r in rows(payloads["recommendations.csv"]) if r["slice_id"] == "s")
    assert rec["rule_ids"] == "R12" and rec["evidence_status"] == "audited_quality"
    assert "audited_quality" in rec["remeasure"]


def test_real_upload_parse_failure_clears_previous_results():
    import io
    snapshot, images, objects = fixture()
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=15)
    with patch("ui.upload.render_upload", return_value=SimpleNamespace(images=images, objects=objects, valid_objects=objects)):
        at.run()
    assert not at.exception and len(at.get("download_button")) == 4
    bad_zip = io.BytesIO(b"not a ZIP archive")
    bad_zip.name = "broken.zip"
    # Exercise real upload handling, temporary ZIP writing, and parser failure.
    with patch("streamlit.file_uploader", return_value=bad_zip):
        at.run()
    assert not at.exception
    assert at.error and any("file CVAT ZIP" in e.value or "lỗi" in e.value for e in at.error)
    assert not at.get("download_button")
    assert "coverage_slice_results" not in at.session_state
    assert "coverage_recommendations" not in at.session_state
