from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd


RETENTION_WINDOWS = (7, 30, 90)


def calculate_monthly_retention(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate monthly cohort retention matrix in percentages."""
    transactions = _ensure_cohort_columns(df)

    cohort_sizes = calculate_cohort_size(transactions).set_index("cohort_month")[
        "cohort_size"
    ]
    active_customers = transactions.groupby(
        ["cohort_month", "months_since_first_purchase"]
    )["customer_id"].nunique()

    max_order_month = transactions["order_month"].max().to_period("M")
    max_age = int(transactions["months_since_first_purchase"].max())
    matrix = pd.DataFrame(
        index=cohort_sizes.index.sort_values(),
        columns=range(max_age + 1),
        dtype=float,
    )

    for cohort_month, cohort_size in cohort_sizes.items():
        cohort_period = pd.Period(cohort_month, freq="M")
        observable_age = (
            (max_order_month.year - cohort_period.year) * 12
            + (max_order_month.month - cohort_period.month)
        )

        for month_number in range(observable_age + 1):
            active = active_customers.get((cohort_month, month_number), 0)
            matrix.loc[cohort_month, month_number] = active / cohort_size * 100

    matrix[0] = 100.0
    matrix.index.name = "cohort_month"
    matrix.columns.name = "months_since_first_purchase"
    return matrix


def calculate_d7_d30_d90_retention(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate D7, D30, and D90 repeat-purchase retention by cohort."""
    transactions = _ensure_cohort_columns(df)
    cohort_sizes = calculate_cohort_size(transactions).set_index("cohort_month")
    repeated = _repeat_transactions(transactions)

    summary = cohort_sizes.copy()
    for window in RETENTION_WINDOWS:
        retained = (
            repeated[repeated["days_after_first_purchase"] <= window]
            .groupby("cohort_month")["customer_id"]
            .nunique()
        )
        summary[f"d{window}_retention"] = (
            retained.reindex(summary.index, fill_value=0)
            / summary["cohort_size"]
            * 100
        )

    return summary.reset_index().sort_values("cohort_month")


def calculate_channel_retention(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate retention and commercial metrics by acquisition channel."""
    transactions = _ensure_cohort_columns(df)
    if "acquisition_channel" not in transactions.columns:
        raise ValueError("Column acquisition_channel is required for channel analysis.")

    customer_base = transactions[["customer_id", "acquisition_channel"]].drop_duplicates()
    summary = customer_base.groupby("acquisition_channel")["customer_id"].nunique()
    summary = summary.rename("customers_count").to_frame()

    order_metrics = transactions.groupby("acquisition_channel").agg(
        orders_count=("invoice", "nunique"),
        revenue=("revenue", "sum"),
    )
    summary = summary.join(order_metrics)
    summary["revenue_per_customer"] = _safe_divide(
        summary["revenue"],
        summary["customers_count"],
    )
    summary["average_order_value"] = _safe_divide(
        summary["revenue"],
        summary["orders_count"],
    )

    repeated = _repeat_transactions(transactions)
    for window in RETENTION_WINDOWS:
        retained = (
            repeated[repeated["days_after_first_purchase"] <= window]
            .groupby("acquisition_channel")["customer_id"]
            .nunique()
        )
        summary[f"d{window}_retention"] = (
            retained.reindex(summary.index, fill_value=0)
            / summary["customers_count"]
            * 100
        )

    return summary.reset_index().sort_values("acquisition_channel")


def calculate_cohort_size(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate unique customer count for each cohort month."""
    transactions = _ensure_cohort_columns(df)
    cohort_size = (
        transactions.groupby("cohort_month")["customer_id"]
        .nunique()
        .rename("cohort_size")
        .reset_index()
        .sort_values("cohort_month")
    )
    return cohort_size


def calculate_country_retention(df: pd.DataFrame, top_n: int = 10) -> pd.DataFrame:
    """Calculate D30 and D90 retention for countries with the largest customer bases."""
    transactions = _ensure_cohort_columns(df)
    top_countries = (
        transactions.groupby("country")["customer_id"]
        .nunique()
        .sort_values(ascending=False)
        .head(top_n)
        .index
    )
    filtered = transactions[transactions["country"].isin(top_countries)].copy()

    summary = filtered.groupby("country").agg(
        customers_count=("customer_id", "nunique"),
        orders_count=("invoice", "nunique"),
        revenue=("revenue", "sum"),
    )

    repeated = _repeat_transactions(filtered)
    for window in (30, 90):
        retained = (
            repeated[repeated["days_after_first_purchase"] <= window]
            .groupby("country")["customer_id"]
            .nunique()
        )
        summary[f"d{window}_retention"] = (
            retained.reindex(summary.index, fill_value=0)
            / summary["customers_count"]
            * 100
        )

    summary["revenue_per_customer"] = _safe_divide(
        summary["revenue"],
        summary["customers_count"],
    )
    return summary.reset_index().sort_values("customers_count", ascending=False)


def calculate_channel_monthly_retention(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate aggregated monthly retention by acquisition channel."""
    transactions = _ensure_cohort_columns(df)
    if "acquisition_channel" not in transactions.columns:
        raise ValueError("Column acquisition_channel is required for channel analysis.")

    channel_sizes = transactions.groupby("acquisition_channel")["customer_id"].nunique()
    active = (
        transactions.groupby(["acquisition_channel", "months_since_first_purchase"])[
            "customer_id"
        ]
        .nunique()
        .rename("active_customers")
        .reset_index()
    )
    active["channel_customers"] = active["acquisition_channel"].map(channel_sizes)
    active["retention_rate"] = _safe_divide(
        active["active_customers"],
        active["channel_customers"],
    ) * 100

    return active.sort_values(["acquisition_channel", "months_since_first_purchase"])


def generate_product_hypotheses(
    cohort_summary: pd.DataFrame | None,
    channel_summary: pd.DataFrame | None,
) -> list[str]:
    """Generate product hypotheses without inventing exact numeric results."""
    hypotheses = [
        "Проверить, отличаются ли onboarding-цепочки для когорт с относительно высоким и низким D30 retention.",
        "Проанализировать, какие товарные категории чаще приводят к повторной покупке в первые 30 дней.",
        "Протестировать CRM-коммуникации для клиентов без повторной покупки в первые 7 дней после первого заказа.",
    ]

    if cohort_summary is not None and not cohort_summary.empty:
        if "d30_retention" in cohort_summary.columns:
            best_cohort = _label_from_max(cohort_summary, "d30_retention", "cohort_month")
            worst_cohort = _label_from_min(cohort_summary, "d30_retention", "cohort_month")
            if best_cohort and worst_cohort and best_cohort != worst_cohort:
                hypotheses.append(
                    "Сравнить ассортимент, промо и сезонность для когорт "
                    f"{best_cohort} и {worst_cohort}: различия могут подсказать, "
                    "какие факторы связаны с ранним удержанием."
                )

    if channel_summary is not None and not channel_summary.empty:
        if {"acquisition_channel", "d30_retention"}.issubset(channel_summary.columns):
            best_channel = _label_from_max(
                channel_summary,
                "d30_retention",
                "acquisition_channel",
            )
            if best_channel:
                hypotheses.append(
                    f"Изучить клиентский путь канала {best_channel}: его механики "
                    "могут быть полезны для улучшения удержания в других каналах."
                )
        if {"acquisition_channel", "revenue_per_customer"}.issubset(
            channel_summary.columns
        ):
            revenue_channel = _label_from_max(
                channel_summary,
                "revenue_per_customer",
                "acquisition_channel",
            )
            if revenue_channel:
                hypotheses.append(
                    f"Проверить, почему канал {revenue_channel} дает более высокую "
                    "выручку на клиента: это может быть связано с составом аудитории "
                    "или типом первой покупки."
                )

    return hypotheses


def _ensure_cohort_columns(df: pd.DataFrame) -> pd.DataFrame:
    transactions = df.copy()
    transactions["invoice_date"] = pd.to_datetime(transactions["invoice_date"])

    if "order_month" not in transactions.columns:
        transactions["order_month"] = (
            transactions["invoice_date"].dt.to_period("M").dt.to_timestamp()
        )
    else:
        transactions["order_month"] = pd.to_datetime(transactions["order_month"])

    if "first_purchase_date" not in transactions.columns:
        transactions["first_purchase_date"] = transactions.groupby("customer_id")[
            "invoice_date"
        ].transform("min")
    else:
        transactions["first_purchase_date"] = pd.to_datetime(
            transactions["first_purchase_date"]
        )

    if "cohort_month" not in transactions.columns:
        transactions["cohort_month"] = (
            transactions["first_purchase_date"].dt.to_period("M").dt.to_timestamp()
        )
    else:
        transactions["cohort_month"] = pd.to_datetime(transactions["cohort_month"])

    if "months_since_first_purchase" not in transactions.columns:
        order_period = transactions["order_month"].dt.to_period("M")
        cohort_period = transactions["cohort_month"].dt.to_period("M")
        transactions["months_since_first_purchase"] = (
            (order_period.dt.year - cohort_period.dt.year) * 12
            + (order_period.dt.month - cohort_period.dt.month)
        )

    if "days_since_first_purchase" not in transactions.columns:
        transactions["days_since_first_purchase"] = (
            transactions["invoice_date"].dt.normalize()
            - transactions["first_purchase_date"].dt.normalize()
        ).dt.days

    return transactions


def _repeat_transactions(df: pd.DataFrame) -> pd.DataFrame:
    repeated = df[df["invoice_date"] > df["first_purchase_date"]].copy()
    repeated["days_after_first_purchase"] = (
        repeated["invoice_date"].dt.normalize()
        - repeated["first_purchase_date"].dt.normalize()
    ).dt.days
    repeated = repeated[repeated["days_after_first_purchase"] >= 0]
    return repeated


def _safe_divide(numerator: Iterable[float], denominator: Iterable[float]) -> np.ndarray:
    numerator_array = np.asarray(numerator, dtype=float)
    denominator_array = np.asarray(denominator, dtype=float)
    return np.divide(
        numerator_array,
        denominator_array,
        out=np.zeros_like(numerator_array, dtype=float),
        where=denominator_array != 0,
    )


def _label_from_max(df: pd.DataFrame, value_column: str, label_column: str) -> str | None:
    valid = df.dropna(subset=[value_column])
    if valid.empty:
        return None
    value = valid.loc[valid[value_column].idxmax(), label_column]
    return _format_label(value)


def _label_from_min(df: pd.DataFrame, value_column: str, label_column: str) -> str | None:
    valid = df.dropna(subset=[value_column])
    if valid.empty:
        return None
    value = valid.loc[valid[value_column].idxmin(), label_column]
    return _format_label(value)


def _format_label(value: object) -> str:
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m")
    return str(value)
