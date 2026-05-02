from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def plot_retention_heatmap(
    retention_matrix: pd.DataFrame,
    title: str = "Monthly Retention Heatmap",
    save_path: str | Path | None = None,
):
    """Plot a monthly retention heatmap with matplotlib."""
    matrix = retention_matrix.copy()
    fig_width = max(8, min(18, 0.7 * len(matrix.columns) + 4))
    fig_height = max(5, min(14, 0.45 * len(matrix.index) + 2))
    fig, ax = plt.subplots(figsize=(fig_width, fig_height))

    image = ax.imshow(matrix.values, aspect="auto")
    fig.colorbar(image, ax=ax, label="Retention, %")

    ax.set_title(title)
    ax.set_xlabel("Months since first purchase")
    ax.set_ylabel("Cohort month")
    ax.set_xticks(np.arange(len(matrix.columns)))
    ax.set_xticklabels(matrix.columns)
    ax.set_yticks(np.arange(len(matrix.index)))
    ax.set_yticklabels([pd.to_datetime(value).strftime("%Y-%m") for value in matrix.index])

    if matrix.size <= 144:
        for row_index in range(matrix.shape[0]):
            for column_index in range(matrix.shape[1]):
                value = matrix.iat[row_index, column_index]
                if pd.notna(value):
                    ax.text(
                        column_index,
                        row_index,
                        f"{value:.0f}",
                        ha="center",
                        va="center",
                        fontsize=8,
                    )

    return _save_or_return(fig, ax, save_path)


def plot_retention_heatmap_without_m0(
    retention_matrix: pd.DataFrame,
    title: str = "Monthly Retention Heatmap without M0",
    save_path: str | Path | None = None,
):
    """Plot a monthly retention heatmap excluding month 0."""
    matrix = retention_matrix.copy()
    m0_columns = [column for column in matrix.columns if str(column) == "0"]

    if not m0_columns:
        raise ValueError("Retention matrix does not contain an M0 column named 0.")

    matrix = matrix.drop(columns=m0_columns)
    if matrix.empty:
        raise ValueError("Retention matrix without M0 is empty.")

    return plot_retention_heatmap(matrix, title=title, save_path=save_path)


def plot_d7_d30_d90_by_cohort(
    retention_df: pd.DataFrame,
    save_path: str | Path | None = None,
):
    """Plot D7, D30, and D90 retention by cohort month."""
    data = retention_df.copy()
    data["cohort_month"] = pd.to_datetime(data["cohort_month"])

    fig, ax = plt.subplots(figsize=(10, 5))
    for column in ["d7_retention", "d30_retention", "d90_retention"]:
        if column in data.columns:
            ax.plot(data["cohort_month"], data[column], marker="o", label=column.upper())

    ax.set_title("D7 / D30 / D90 Retention by Cohort")
    ax.set_xlabel("Cohort month")
    ax.set_ylabel("Retention, %")
    ax.legend()
    ax.tick_params(axis="x", rotation=45)
    return _save_or_return(fig, ax, save_path)


def plot_retention_by_channel(
    channel_df: pd.DataFrame,
    save_path: str | Path | None = None,
):
    """Plot grouped bars for D7, D30, and D90 retention by channel."""
    data = channel_df.sort_values("acquisition_channel").copy()
    x = np.arange(len(data))
    width = 0.25

    fig, ax = plt.subplots(figsize=(10, 5))
    for offset, column in zip(
        [-width, 0, width],
        ["d7_retention", "d30_retention", "d90_retention"],
        strict=False,
    ):
        ax.bar(x + offset, data[column], width=width, label=column.upper())

    ax.set_title("D7 / D30 / D90 Retention by Acquisition Channel")
    ax.set_xlabel("Acquisition channel")
    ax.set_ylabel("Retention, %")
    ax.set_xticks(x)
    ax.set_xticklabels(data["acquisition_channel"], rotation=35, ha="right")
    ax.legend()
    return _save_or_return(fig, ax, save_path)


def plot_cohort_size(
    cohort_size_df: pd.DataFrame,
    save_path: str | Path | None = None,
):
    """Plot cohort sizes by month."""
    data = cohort_size_df.copy()
    data["cohort_month"] = pd.to_datetime(data["cohort_month"])

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.bar(data["cohort_month"].dt.strftime("%Y-%m"), data["cohort_size"])
    ax.set_title("Cohort Size by Month")
    ax.set_xlabel("Cohort month")
    ax.set_ylabel("Customers")
    ax.tick_params(axis="x", rotation=45)
    return _save_or_return(fig, ax, save_path)


def plot_revenue_per_customer_by_channel(
    channel_df: pd.DataFrame,
    save_path: str | Path | None = None,
):
    """Plot revenue per customer by acquisition channel."""
    data = channel_df.sort_values("revenue_per_customer", ascending=False).copy()

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.bar(data["acquisition_channel"], data["revenue_per_customer"])
    ax.set_title("Revenue per Customer by Acquisition Channel")
    ax.set_xlabel("Acquisition channel")
    ax.set_ylabel("Revenue per customer")
    ax.tick_params(axis="x", rotation=35)
    return _save_or_return(fig, ax, save_path)


def save_dataframe(df: pd.DataFrame, path: str | Path) -> None:
    """Save DataFrame to CSV and create parent directory if needed."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)


def _save_or_return(fig, ax, save_path: str | Path | None):
    fig.tight_layout()
    if save_path is not None:
        output_path = Path(save_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_path, dpi=160, bbox_inches="tight")
    return ax
