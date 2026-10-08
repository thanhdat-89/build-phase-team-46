"""File upload component for CVAT Images 1.1 ZIP exports."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Optional

import streamlit as st

from parsers.cvat_images import CvatParseError, CvatParseResult, parse_cvat_zip


def render_upload() -> Optional[CvatParseResult]:
    """Render a file uploader widget and parse the selected ZIP file.

    Returns
    -------
    Optional[CvatParseResult]
        Parsed result containing images, objects, and skipped_shapes,
        or None if no file was uploaded or parsing failed.
    """
    uploaded_file = st.file_uploader(
        "Tải lên file ZIP xuất từ CVAT (CVAT for images 1.1)",
        type=["zip"],
        help="Chọn file ZIP chứa file XML chú thích và thư mục ảnh.",
    )

    if uploaded_file is None:
        return None

    dataset_id = Path(uploaded_file.name).stem

    # Save uploaded file into a temporary file on disk for zipfile reading
    tmp_path: Optional[str] = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp_file:
            tmp_file.write(uploaded_file.getbuffer())
            tmp_path = tmp_file.name

        result = parse_cvat_zip(tmp_path, dataset_id=dataset_id)
        st.success(f"Đã tải và xử lý thành công dataset: **{dataset_id}**")
        return result

    except CvatParseError as exc:
        st.error(f"Lỗi khi đọc file CVAT ZIP: {exc}")
        return None
    except Exception as exc:
        st.error(f"Đã xảy ra lỗi không xác định khi xử lý file: {exc}")
        return None
    finally:
        if tmp_path is not None:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except OSError:
                pass
