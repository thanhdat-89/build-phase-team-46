"""Application integration and export projection; calculations live in coverage."""
from __future__ import annotations

import csv
import hashlib
import io
import json
from collections import Counter
from dataclasses import asdict, replace

import streamlit as st

from core.coverage_export import export_coverage_bundle
from ui.coverage import CoverageSnapshot
from ui.recommendations import affected_image_rows, ordered_recommendations, validated_cvat_url


def import_provenance(images, objects):
    """Fingerprint normalized records, independent of coverage configuration/order."""
    records = {"images": [asdict(x) for x in images], "objects": [asdict(x) for x in objects]}
    for values in records.values():
        values.sort(key=lambda x: json.dumps(x, sort_keys=True, ensure_ascii=False))
    payload = json.dumps(records, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    version = "normalized-sha256:" + hashlib.sha256(payload.encode()).hexdigest()
    identity = tuple(sorted({x.dataset_id for x in [*images, *objects]}))
    return identity, version


def clear_import_state(state):
    for key in list(state):
        if key.startswith(("coverage_", "target_input_", "weight_input_", "enabled_input_", "integration_", "cvat_sidecar_")) or key == "cov_edit_slice_select":
            del state[key]


def synchronize_import(state, identity, version):
    if state.get("integration_identity") != identity:
        clear_import_state(state)
    state["integration_identity"] = identity
    state["integration_version"] = version


def validate_mapping_sidecar(raw, images, dataset_version):
    """Atomic validation: reject stale, ambiguous, unconfirmed or unknown entries."""
    if not isinstance(raw, dict) or set(raw) != {"dataset_version", "mappings"}:
        raise ValueError("Mapping requires dataset_version and mappings only.")
    if raw["dataset_version"] != dataset_version:
        raise ValueError("Stale mapping: imported-record version does not match.")
    entries = raw["mappings"]
    if not isinstance(entries, dict):
        raise ValueError("mappings must be an object keyed by exact image keys.")
    counts = Counter(i.image_key for i in images)
    for key, entry in entries.items():
        if counts[key] != 1 or not isinstance(entry, dict):
            raise ValueError("Unknown or ambiguous canonical image key.")
        allowed = {"confirmed", "url"} if "url" in entry else {"confirmed", "base_url", "task_id", "job_id", "frame"}
        if set(entry) - allowed or not validated_cvat_url(key, entries):
            raise ValueError("Mapping must be explicitly confirmed and contain a valid CVAT destination.")
    return entries


def render_mapping_input(images, dataset_version):
    st.caption("Optional caller-confirmed mapping; no live CVAT verification. Default: image path/key.")
    st.code(json.dumps({"dataset_version": dataset_version, "mappings": {}}, indent=2), language="json")
    upload = st.file_uploader("CVAT mapping sidecar (JSON)", type=["json"], key="cvat_sidecar_" + dataset_version)
    if upload is None:
        return {}
    try:
        return validate_mapping_sidecar(json.loads(upload.getvalue()), images, dataset_version)
    except (ValueError, UnicodeError, TypeError) as error:
        st.warning(f"Mapping rejected; using paths/keys: {error}")
        return {}


def prepare_exports(snapshot: CoverageSnapshot, images, objects, mappings=None):
    """Project real parent records without altering engine evidence or recomputing."""
    counts = Counter(i.image_key for i in images)
    lookup = {i.image_key: i for i in images if counts[i.image_key] == 1}
    safe_urls = {k: validated_cvat_url(k, mappings) for k in lookup}
    recs = []
    for rec in ordered_recommendations(snapshot.recommendations):
        rows = affected_image_rows(rec, images, objects, snapshot.slice_results.get(rec.slice_id))
        keys = sorted({row["image_key"] for row in rows if row["mapping_status"] == "resolved"})
        recs.append(replace(rec, affected_image_keys=keys))
    config = asdict(snapshot.config)
    config["dataset_version"] = snapshot.dataset_version
    bundle = export_coverage_bundle(
        slice_results=snapshot.slice_results, recommendations=recs, config=config,
        images=lookup, cvat_mapping=lambda key: safe_urls.get(key, ""),
        dataset_version=snapshot.dataset_version, config_version=snapshot.config.config_version,
    )
    # Core serializes skipped placeholder numbers. Blank them in presentation only.
    def rewrite(content, transform):
        reader = csv.DictReader(io.StringIO(content))
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=reader.fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in reader:
            transform(row)
            writer.writerow(row)
        return output.getvalue()
    unavailable = {r.recommendation_id for r in recs if r.status in {"skipped", "not_available"} or r.evidence_status == "not_available"}
    def rec_transform(row):
        if row["recommendation_id"] in unavailable:
            for name in ("support", "target", "gap", "attainment", "priority"):
                row[name] = ""
    def metric_transform(row):
        if not (images if row["unit"] == "image" else objects):
            row["metadata_availability"] = ""
    bundle.recommendations_csv = rewrite(bundle.recommendations_csv, rec_transform)
    bundle.metrics_csv = rewrite(bundle.metrics_csv, metric_transform)
    return bundle


def render_reports(snapshot, images, objects, mappings=None):
    st.header("Reports & Exports")
    st.caption("Current shared snapshot. Blank CSV values are unavailable, not measured zero. Affected CSV contains uniquely resolved existing image records; roles and mapping issues remain in the panel.")
    bundle = prepare_exports(snapshot, images, objects, mappings)
    for filename, content in bundle.to_dict().items():
        st.download_button(filename, content.encode("utf-8"), file_name=filename,
                           mime="application/json" if filename.endswith("json") else "text/csv",
                           key="download_" + filename)
    return bundle
