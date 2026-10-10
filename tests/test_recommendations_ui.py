"""Phase 4.3 presentation contract tests; no application integration required."""
from copy import deepcopy
from dataclasses import replace

import pytest
from streamlit.testing.v1 import AppTest

from core.coverage_config import CoverageConfig, SliceDefinition
from core.recommendations import Recommendation, recommend
from core.schema import ImageRecord, ObjectRecord
from core.slice_engine import measure_slices
from ui.recommendations import (
    affected_image_rows, display_value, ordered_recommendations,
    recommendation_evidence, validated_cvat_url,
)


def rec(**kwargs):
    values = dict(recommendation_id="r1", slice_id="s1", rule_ids=["R02"],
                  category="collection_gap", severity="planning", evidence_status="observed_annotation",
                  support=1, target=5, gap=4, attainment=.2, priority=2.4, unit="image",
                  title="Review samples", actions=["Verify metadata", "Collect if confirmed"],
                  remeasure=["support", "gap"], limitations=["Observed labels only"],
                  affected_image_keys=["ds:i1"], config_version="7", dataset_version="export-8",
                  target_reason="Approved risk requirement")
    values.update(kwargs)
    return Recommendation(**values)


def img(key="i1", path="frames/real.png"):
    return ImageRecord("ds", key, path, 100, 100, timeofday="night")


def obj(key="unrelated_object_name", parent="i1"):
    return ObjectRecord(key, parent, "person", 1, 1, 10, 10, dataset_id="ds")


def config(unit="image", target=5, weight=1):
    return CoverageConfig(config_version="7", slices=[SliceDefinition(
        "s1", "Night", unit, {"timeofday": "night"}, target, weight=weight,
        target_reason="Approved risk requirement")])


def render_app(recs, **context):
    def script():
        import streamlit as st
        from ui.recommendations import render_recommendations
        render_recommendations(st.session_state.test_recs, **st.session_state.test_context)
    app = AppTest.from_function(script)
    app.session_state.test_recs = recs
    app.session_state.test_context = context
    return app.run(timeout=20)


def texts(app):
    return "\n".join(e.value for kind in ("text", "caption", "warning", "info", "subheader") for e in app.get(kind))


def test_sort_severity_priority_ties_and_no_mutation():
    records = [rec(severity=s, priority=p, slice_id=k, recommendation_id=i)
               for s, p, k, i in [("info", 99, "a", "i"), ("planning", 9, "b", "p"),
                                 ("blocker", 0, "a", "b"), ("review_required", 1, "a", "r"),
                                 ("planning", 9, "a", "z"), ("planning", 9, "a", "a"),
                                 ("planning", 1, "a", "low")]]
    before = deepcopy(records)
    ordered = ordered_recommendations(records)
    assert [r.recommendation_id for r in ordered] == ["b", "r", "a", "z", "p", "low", "i"]
    assert records == before
    assert all(any(item is original for original in records) for item in ordered)
    assert ordered_recommendations(list(reversed(records))) == ordered


@pytest.mark.parametrize("value", [None, float("nan"), float("inf"), ""])
def test_unavailable_values(value):
    assert display_value(value) == "N/A"
    assert display_value(value, percent=True) == "N/A"


def test_real_zero_is_preserved_and_skipped_placeholders_are_na():
    assert display_value(0) == "0"
    assert display_value(0, percent=True) == "0.0%"
    assert set(recommendation_evidence(rec(status="not_available", support=0)).values()) == {"N/A"}
    assert recommendation_evidence(rec(support=None))["support"] == "N/A"


@pytest.mark.parametrize("state,meaning", [
    ("observed_annotation", "không phải ground truth đã kiểm toán"),
    ("provisional", "cần xác minh dữ liệu chưa rõ"),
    ("unresolved_metadata", "cần bổ sung hoặc xác minh metadata"),
    ("audited_quality", "không chứng minh đã hoàn thành kiểm toán"),
    ("not_available", "không phải kết quả bằng không"),
])
def test_evidence_states_and_merged_content_render(state, meaning):
    record = rec(evidence_status=state, rule_ids=["R02", "R06", "R11"])
    before = deepcopy(record)
    app = render_app([record])
    assert not app.exception
    output = texts(app)
    for expected in [state, meaning, "R02, R06, R11", *record.actions,
                     *record.limitations, record.target_reason, "export-8", "Config: 7", "support:", "gap:"]:
        assert expected in output
    assert record == before


@pytest.mark.parametrize("rule,target,weight,missing", [
    ("R01", 5, 1, False), ("R02", 5, 1, False), ("R06", 5, 1, True),
    ("R11", 5, 3, False), ("R12", 1, 1, False),
])
def test_actual_engine_rule_presentation(rule, target, weight, missing):
    images = [] if rule == "R01" else [replace(img(), timeofday=None if missing else "night")]
    cfg = config(target=target, weight=weight)
    results = measure_slices(images, [], cfg)
    records = recommend(results, config=cfg, images=images, dataset_version="export-8")
    assert any(rule in r.rule_ids for r in records)
    app = render_app(records, images=images, config=cfg, slice_results=results)
    assert not app.exception
    output = texts(app)
    assert "chưa phải kết quả đo mới" in output
    for record in records:
        for value in record.actions + record.limitations + record.remeasure:
            assert value in output
    if rule == "R12":
        assert "không chứng minh đã hoàn thành kiểm toán" in output
        assert "không xác nhận kiểm toán đã hoàn thành" in output
    if rule == "R06":
        assert "Mẫu số availability" in output
        assert "Independent source support: N/A" in output
    if rule == "R01":
        assert "Không có ảnh liên quan" in output


def test_object_resolution_uses_real_parent_and_separates_roles():
    images = [img(), replace(img("i2"), timeofday=None)]
    objects = [obj(), obj("other", "i1"), obj("unknown", "i2")]
    cfg = config("object")
    results = measure_slices(images, objects, cfg)
    record = rec(unit="object", rule_ids=["R02", "R06"], affected_image_keys=["wrong:lossy"])
    before = deepcopy((record, images, objects, results))
    rows = affected_image_rows(record, images, objects, results["s1"])
    assert {(r["image_key"], r["role"]) for r in rows} == {
        ("ds:i1", "existing_support"), ("ds:i2", "metadata_correction")}
    assert len(rows) == 2
    assert all(r["mapping_status"] == "resolved" for r in rows)
    assert (record, images, objects, results) == before


def test_missing_and_ambiguous_object_parents_are_explicit():
    record = rec(unit="object", affected_image_keys=["ds:unrelated_object_name"])
    assert affected_image_rows(record, [img()])[0]["mapping_status"] == "missing_object_mapping"
    rows = affected_image_rows(record, [img()], [obj(), obj(parent="other")])
    assert rows[0]["mapping_status"] == "ambiguous_object_mapping"
    assert rows[0]["cvat_url"] == ""
    rows = affected_image_rows(record, [], [obj()])
    assert rows[0]["image_key"] == "ds:i1"
    assert rows[0]["mapping_status"] == "missing_image_record"


def test_canonical_image_key_resolves_directly_without_slice_results():
    record = rec(unit="object", affected_image_keys=["ds:i1"])
    # An object-key collision cannot override an explicit affected image key.
    row = affected_image_rows(record, [img(), img("i2")], [obj("i1", "i2")])[0]
    assert row["mapping_status"] == "resolved"
    assert row["image_key"] == "ds:i1"
    assert row["image_path"] == "frames/real.png"


def test_original_slice_object_key_resolves_parent_despite_image_key_collision():
    images = [img(), img("i2", "parent.png")]
    objects = [obj("i1", "i2")]
    result = measure_slices(images, objects, config("object"))["s1"]
    row = affected_image_rows(rec(unit="object"), images, objects, result)[0]
    assert row["image_key"] == "ds:i2" and row["image_path"] == "parent.png"


def test_image_path_key_fallback_dedup_and_ambiguity():
    record = rec(affected_image_keys=["ds:i1", "ds:i1"])
    rows = affected_image_rows(record, [img()])
    assert len(rows) == 1 and rows[0]["display"] == "frames/real.png"
    assert affected_image_rows(record, [img(path="")])[0]["display"] == "ds:i1"
    assert affected_image_rows(record)[0]["display"] == "ds:i1"
    ambiguous = affected_image_rows(record, [img(), img(path="other.png")])[0]
    assert ambiguous["mapping_status"] == "ambiguous_image_mapping"
    assert ambiguous["display"] == "ds:i1"


@pytest.mark.parametrize("entry", [
    {"confirmed": True, "url": "https://cvat.local/tasks/1/jobs/2?frame=0"},
    {"confirmed": True, "base_url": "http://localhost:8080", "task_id": 1, "job_id": 2, "frame": 0},
    {"confirmed": True, "base_url": "https://cvat.local", "task_id": 1, "frame": 3},
])
def test_confirmed_valid_mapping(entry):
    mapping = {"ds:i1": entry}
    assert validated_cvat_url("ds:i1", mapping)
    assert affected_image_rows(rec(), [img()], cvat_mapping=mapping)[0]["cvat_url"]


@pytest.mark.parametrize("entry", [
    None, "https://cvat.local/tasks/1?frame=0", {"url": "https://cvat.local/tasks/1?frame=0"},
    {"confirmed": False, "url": "https://cvat.local/tasks/1?frame=0"},
    {"confirmed": True, "url": "javascript:alert(1)"},
    {"confirmed": True, "url": "https://cvat.local/not-an-image"},
    {"confirmed": True, "url": "https:///tasks/1?frame=0"},
    {"confirmed": True, "url": "https://user:pass@cvat.local/tasks/1?frame=0"},
    {"confirmed": True, "url": "https://cvat.local/tasks/1?frame=-1"},
    {"confirmed": True, "url": "https://cvat.local/tasks/1?frame=0&frame=1"},
    {"confirmed": True, "url": "https://cvat.local/tasks/1?frame=0#fragment"},
    {"confirmed": True, "base_url": "https://cvat.local", "task_id": 1},
    {"confirmed": True, "base_url": "https://cvat.local", "task_id": True, "frame": 0},
    {"confirmed": True, "base_url": "https://cvat.local", "task_id": 1, "frame": -1},
])
def test_invalid_or_unconfirmed_mapping_falls_back(entry):
    mapping = {"ds:i1": entry}
    assert validated_cvat_url("ds:i1", mapping) == ""
    row = affected_image_rows(rec(), [img()], cvat_mapping=mapping)[0]
    assert row["display"] == "frames/real.png" and not row["cvat_url"]


def test_callable_mapping_is_not_executed_or_assumed_confirmed():
    def untrusted(key):
        raise AssertionError("Must not execute caller function")
    assert validated_cvat_url("ds:i1", untrusted) == ""


def test_empty_skipped_zero_support_and_ui_order():
    app = render_app([])
    assert not app.exception
    assert "không xác nhận" in texts(app)
    records = [rec(severity="info", status="skipped", evidence_status="not_available", skip_reason="No logs", affected_image_keys=[], remeasure=[]),
               rec(severity="blocker", recommendation_id="block", support=0, affected_image_keys=[])]
    app = render_app(records)
    assert not app.exception
    assert app.subheader[0].value.startswith("blocker")
    assert "No logs" in texts(app) and "support: N/A" in texts(app)
    assert "Không có ảnh liên quan" in texts(app)


def test_render_fallback_paths_links_and_incompatible_context():
    mapping = {"ds:i1": {"confirmed": True, "url": "https://cvat.local/tasks/1?frame=0"}}
    app = render_app([rec()], images=[img()], cvat_mapping=mapping)
    assert not app.exception and len(app.get("link_button")) == 1
    assert app.get("link_button")[0].proto.url == "https://cvat.local/tasks/1?frame=0"
    assert "frames/real.png" in texts(app)
    cfg = config()
    cfg.config_version = "different"
    results = measure_slices([img()], [], cfg)
    app = render_app([rec()], images=[img()], config=cfg, slice_results=results)
    assert not app.exception
    assert "Phiên bản cấu hình không khớp" in texts(app)
    assert "Metadata availability:" not in texts(app)


@pytest.mark.parametrize("with_slice,unit", [(False, "object"), (True, "image"), (True, "object")])
def test_canonical_image_key_fallback_is_visible(with_slice, unit):
    images = [img()]
    objects = [obj()] if unit == "object" else []
    results = measure_slices(images, objects, config(unit)) if with_slice else None
    app = render_app([rec(unit=unit)], images=images, objects=objects, slice_results=results)
    assert not app.exception
    assert "frames/real.png | ds:i1 | resolved" in texts(app)
    assert not app.get("link_button")


@pytest.mark.parametrize("with_slice", [False, True])
def test_original_object_key_parent_path_is_visible(with_slice):
    images, objects = [img()], [obj()]
    results = measure_slices(images, objects, config("object")) if with_slice else None
    record = rec(unit="object", affected_image_keys=[objects[0].object_key])
    app = render_app([record], images=images, objects=objects, slice_results=results)
    assert not app.exception
    assert "frames/real.png | ds:i1 | resolved" in texts(app)
    assert "missing_object_mapping" not in texts(app)


@pytest.mark.parametrize("images", [[], [img(path="")]])
def test_key_fallback_is_visible(images):
    app = render_app([rec(unit="object")], images=images)
    assert not app.exception
    assert "| ds:i1 | ds:i1 |" in texts(app)
    assert "frames/real.png" not in texts(app)
    assert not app.get("link_button")


def test_render_image_roles_and_deduplication_without_mutating_inputs():
    images = [img(), replace(img("i2", "needs-metadata.png"), timeofday=None)]
    objects = [obj(), obj("another", "i1"), obj("unresolved", "i2")]
    cfg = config("object")
    results = measure_slices(images, objects, cfg)
    records = recommend(results, config=cfg, images=images, dataset_version="export-8")
    mappings = {"ds:i1": {"confirmed": True, "url": "https://cvat.local/tasks/1/jobs/2?frame=0"}}
    before = deepcopy((records, images, objects, cfg, results, mappings))
    record_ids = [id(r) for r in records]
    app = render_app(records, images=images, objects=objects, config=cfg,
                     slice_results=results, cvat_mapping=mappings)
    assert not app.exception
    visible = [e.value for e in app.text]
    supporting = "Ảnh hỗ trợ hiện có | frames/real.png | ds:i1 | resolved"
    correction = "Metadata cần xác minh/bổ sung | needs-metadata.png | ds:i2 | resolved"
    assert visible.count(supporting) == 1
    assert visible.count(correction) == 1
    assert "Điều kiện tìm mẫu mới (không phải ảnh đã có):" in texts(app)
    assert app.get("link_button")[0].proto.url == "https://cvat.local/tasks/1/jobs/2?frame=0"
    assert (records, images, objects, cfg, results, mappings) == before
    assert [id(r) for r in records] == record_ids


def test_all_severities_and_priorities_are_visible_in_order():
    records = [rec(severity=s, priority=p, slice_id=k, recommendation_id=k)
               for s, p, k in [("info", 99, "info"), ("planning", 1, "planning-low"),
                               ("review_required", .1, "review"), ("planning", 9, "planning-high"),
                               ("blocker", 0, "blocker")]]
    before = deepcopy(records)
    app = render_app(records)
    assert not app.exception
    assert [e.value for e in app.subheader] == [
        "blocker · blocker", "review_required · review", "planning · planning-high",
        "planning · planning-low", "info · info"]
    assert records == before


@pytest.mark.parametrize("unit,nonempty", [("image", False), ("image", True),
                                         ("object", False), ("object", True)])
def test_empty_and_valid_zero_availability_are_visible(unit, nonempty):
    images = [replace(img(), timeofday=None)] if nonempty else []
    objects = [obj()] if nonempty and unit == "object" else []
    if not nonempty:
        # A non-empty sequence of the other unit must not supply the denominator.
        if unit == "object":
            images = [img()]
        else:
            objects = [obj()]
    cfg = config(unit)
    results = measure_slices(images, objects, cfg)
    assert results["s1"].metadata_availability["timeofday"] == 0.0
    records = recommend(results, config=cfg, images=images)
    app = render_app(records, images=images, objects=objects, config=cfg, slice_results=results)
    assert not app.exception
    availability = [e.value for e in app.text if e.value.startswith("Metadata availability:")]
    assert availability == ["Metadata availability: timeofday: " + ("0.0%" if nonempty else "N/A")]


@pytest.mark.parametrize("unit", ["image", "object"])
def test_omitted_availability_denominator_is_not_guessed(unit):
    results = measure_slices([img()], [obj()], config(unit))
    app = render_app([rec(unit=unit)], slice_results=results)
    assert not app.exception
    assert "Metadata availability: timeofday: N/A" in texts(app)
    assert "100.0%" not in texts(app)


@pytest.mark.parametrize("value,expected", [(1234567, "1,234,567"),
                                            (1234567.0, "1,234,567"),
                                            (0, "0"), (2.4, "2.4")])
def test_exact_count_and_noninteger_formatting(value, expected):
    assert display_value(value) == expected


def test_large_support_target_gap_unresolved_counts_are_visible_exactly():
    images = [img()]
    results = measure_slices(images, [], config())
    results["s1"] = replace(results["s1"], unresolved_count=1234567)
    record = rec(support=1234567, target=2469134, gap=1234567)
    app = render_app([record], images=images, slice_results=results)
    assert not app.exception
    output = texts(app)
    assert "support: 1,234,567 | target: 2,469,134 | gap: 1,234,567" in output
    assert "Unresolved: 1,234,567" in output
    assert "e+06" not in output
