"""Minimal Streamlit application entry point.

N2-05B - Dashboard phân bố class và thuộc tính dữ liệu
"""

from __future__ import annotations

import streamlit as st

from ui.overview import render_overview
from ui.upload import render_upload


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
        render_overview(images=result.images, objects=result.objects)
    else:
        st.info("👆 Vui lòng tải lên file ZIP export từ CVAT để bắt đầu phân tích dữ liệu.")


if __name__ == "__main__":
    main()
