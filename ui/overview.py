"""Overview dashboard view displaying dataset statistics."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from core.schema import ImageRecord, ObjectRecord
from core.statistics import (
    class_distribution,
    class_image_distribution,
    dataset_summary,
    timeofday_distribution,
    weather_distribution,
)


def render_overview(
    images: list[ImageRecord],
    valid_objects: list[ObjectRecord] | None = None,
    objects: list[ObjectRecord] | None = None,
) -> None:
    """Render high-level dataset metrics and attribute distributions.

    Parameters
    ----------
    images : list[ImageRecord]
        List of parsed image records.
    valid_objects : list[ObjectRecord] | None
        List of valid object records (M_valid).
    objects : list[ObjectRecord] | None
        Legacy alias for valid_objects.
    """
    target_objects = valid_objects if valid_objects is not None else (objects or [])

    # -----------------------------------------------------------------------
    # A. Dataset Summary
    # -----------------------------------------------------------------------
    st.subheader("1. Tổng quan Dataset (Dataset Summary)")
    summary = dataset_summary(images, target_objects)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Tổng số ảnh", summary["total_images"])
    c2.metric("Tổng số đối tượng", summary["total_objects"])
    c3.metric("Số lớp đối tượng", summary["total_classes"])
    c4.metric("Ảnh có nhãn (≥1)", summary["annotated_images"])
    c5.metric("Ảnh không nhãn (0)", summary["unannotated_images"])

    st.divider()

    # -----------------------------------------------------------------------
    # B. Class Distribution
    # -----------------------------------------------------------------------
    st.subheader("2. Phân bố Class (Class Distribution)")
    class_dist = class_distribution(target_objects)

    if class_dist:
        df_class = pd.DataFrame(class_dist)
        col_table, col_chart = st.columns([1, 1])

        with col_table:
            st.dataframe(
                df_class,
                column_config={
                    "class_name": "Tên class",
                    "object_count": "Số lượng đối tượng",
                    "image_count": "Số lượng ảnh chứa",
                    "percentage": st.column_config.NumberColumn(
                        "Tỷ lệ (%)", format="%.2f%%"
                    ),
                },
                use_container_width=True,
                hide_index=True,
            )

        with col_chart:
            fig = px.bar(
                df_class,
                x="class_name",
                y="object_count",
                labels={"class_name": "Class", "object_count": "Số lượng đối tượng"},
                title="Số lượng đối tượng theo Class",
                text="object_count",
            )
            fig.update_layout(xaxis_title="Class", yaxis_title="Số lượng đối tượng")
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Không có đối tượng (bounding box) nào trong dataset.")

    st.divider()

    # -----------------------------------------------------------------------
    # C & D. Scene Info: Time-of-day & Weather
    # -----------------------------------------------------------------------
    col_tod, col_weather = st.columns(2)

    with col_tod:
        st.subheader("3. Phân bố Thời gian (Time of Day)")
        tod_dist = timeofday_distribution(images)
        df_tod = pd.DataFrame(
            list(tod_dist.items()), columns=["timeofday", "image_count"]
        )
        st.dataframe(
            df_tod,
            column_config={
                "timeofday": "Khung thời gian",
                "image_count": "Số lượng ảnh",
            },
            use_container_width=True,
            hide_index=True,
        )

        fig_tod = px.bar(
            df_tod,
            x="timeofday",
            y="image_count",
            labels={"timeofday": "Khung giờ", "image_count": "Số ảnh"},
            text="image_count",
        )
        st.plotly_chart(fig_tod, use_container_width=True)

    with col_weather:
        st.subheader("4. Phân bố Thời tiết (Weather)")
        weather_dist = weather_distribution(images)
        df_weather = pd.DataFrame(
            list(weather_dist.items()), columns=["weather", "image_count"]
        )
        st.dataframe(
            df_weather,
            column_config={
                "weather": "Điều kiện thời tiết",
                "image_count": "Số lượng ảnh",
            },
            use_container_width=True,
            hide_index=True,
        )

        fig_weather = px.bar(
            df_weather,
            x="weather",
            y="image_count",
            labels={"weather": "Thời tiết", "image_count": "Số ảnh"},
            text="image_count",
        )
        st.plotly_chart(fig_weather, use_container_width=True)

    st.divider()

    # -----------------------------------------------------------------------
    # E. Class Image Distribution
    # -----------------------------------------------------------------------
    st.subheader("5. Phân bố Class theo Số lượng Ảnh (Class-Image Distribution)")
    class_img_dist = class_image_distribution(target_objects)

    if class_img_dist:
        df_class_img = pd.DataFrame(class_img_dist)
        st.dataframe(
            df_class_img,
            column_config={
                "class_name": "Tên class",
                "object_count": "Số lượng đối tượng",
                "image_count": "Số lượng ảnh chứa",
            },
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("Không có dữ liệu class-image.")
