"""Minimal Streamlit application entry point.

N2-05B - Dashboard phân bố class và thuộc tính dữ liệu
"""

from __future__ import annotations

import streamlit as st

from ui.overview import render_overview
from ui.upload import render_upload
from ui.coverage import render_coverage
from ui.recommendations import render_recommendations
from ui.reports import (clear_import_state, import_provenance, synchronize_import,
                        render_mapping_input, render_reports)


def main() -> None:
    """Main application loop."""
    st.set_page_config(
        page_title="N2-05B - Dashboard phân bố class và thuộc tính dữ liệu",
        page_icon="📊",
        layout="wide",
    )

    st.title("N2-05B - Dashboard phân bố class và thuộc tính dữ liệu")
    st.caption("Khám phá và phân tích phân bố lớp đối tượng cùng thuộc tính bối cảnh từ CVAT XML export.")

    st.divider()

    # Step 1: Upload & parse CVAT ZIP
    result = render_upload()

    # Step 2: Render overview dashboard if parsing succeeded
    if result is not None:
        st.divider()
        identity, version = import_provenance(result.images, result.objects)
        synchronize_import(st.session_state, identity, version)
        st.caption(f"Imported-record version (normalized fingerprint, not CVAT server export version): {version}")
        if not result.images and not result.objects:
            st.info("Empty successful import: no eligible records; measurement is unavailable.")
        overview_tab, coverage_tab, reports_tab = st.tabs(["Overview", "Coverage & Recommendations", "Reports & Exports"])
        with overview_tab:
            render_overview(images=result.images, valid_objects=result.valid_objects)
        with coverage_tab:
            snapshot = render_coverage(images=result.images, objects=result.objects,
                                       dataset_version=version, dataset_id="|".join(identity) or "empty-import",
                                       include_skipped=True)
            mappings = render_mapping_input(result.images, version)
            if snapshot is not None:
                render_recommendations(snapshot.recommendations, images=result.images,
                                       objects=result.objects, slice_results=snapshot.slice_results,
                                       config=snapshot.config, cvat_mapping=mappings)
        with reports_tab:
            if snapshot is not None:
                render_reports(snapshot, result.images, result.objects, mappings)
            else:
                st.info("Exports unavailable until configuration is valid.")
    else:
        clear_import_state(st.session_state)
        st.info("👆 Vui lòng tải lên file ZIP export từ CVAT để bắt đầu phân tích dữ liệu.")


if __name__ == "__main__":
    main()
