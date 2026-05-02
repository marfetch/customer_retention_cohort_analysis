from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path
from typing import BinaryIO

import numpy as np
import pandas as pd


SUPPORTED_RAW_EXTENSIONS = {".csv", ".xlsx", ".xls", ".zip"}
EXPECTED_COLUMNS = {
    "invoice",
    "stock_code",
    "description",
    "quantity",
    "invoice_date",
    "price",
    "customer_id",
    "country",
}


def find_raw_data_file(raw_path: str | Path = "data/raw") -> Path:
    """Find the first supported Online Retail II source file in raw_path."""
    raw_dir = Path(raw_path)

    if not raw_dir.exists():
        raise FileNotFoundError(
            f"Raw data directory does not exist: {raw_dir}. "
            "Download the Kaggle Online Retail II UCI dataset manually and place "
            "the CSV, Excel, or ZIP file into data/raw/."
        )

    candidates = [
        path
        for path in raw_dir.iterdir()
        if path.is_file()
        and path.name != ".gitkeep"
        and path.suffix.lower() in SUPPORTED_RAW_EXTENSIONS
    ]

    if not candidates:
        raise FileNotFoundError(
            "No supported raw data file was found in data/raw/. "
            "Download the Kaggle Online Retail II UCI dataset manually from "
            "https://www.kaggle.com/datasets/mashlyn/online-retail-ii-uci/data "
            "and place a CSV, XLSX, XLS, or ZIP file into data/raw/."
        )

    def sort_key(path: Path) -> tuple[int, int, str]:
        name = path.name.lower()
        online_retail_priority = 0 if "online" in name and "retail" in name else 1
        extension_priority = {".csv": 0, ".xlsx": 1, ".xls": 2, ".zip": 3}.get(
            path.suffix.lower(),
            9,
        )
        return online_retail_priority, extension_priority, name

    return sorted(candidates, key=sort_key)[0]


def load_online_retail_data(raw_path: str | Path = "data/raw") -> pd.DataFrame:
    """Load Online Retail II data from CSV, Excel, or ZIP without exact filename assumptions."""
    file_path = find_raw_data_file(raw_path)
    return _read_supported_file(file_path)


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize source column names to snake_case."""
    normalized = df.copy()
    normalized.columns = [_to_snake_case(column) for column in normalized.columns]

    rename_map = {
        "customer_i_d": "customer_id",
        "customerid": "customer_id",
        "invoice_date": "invoice_date",
        "invoicedate": "invoice_date",
        "stock_code": "stock_code",
        "stockcode": "stock_code",
    }
    normalized = normalized.rename(columns=rename_map)
    return normalized


def clean_transactions(df: pd.DataFrame) -> pd.DataFrame:
    """Clean raw transaction rows and create revenue."""
    transactions = df.copy()
    missing_columns = sorted(EXPECTED_COLUMNS - set(transactions.columns))
    if missing_columns:
        raise ValueError(
            "The dataset is missing required columns after normalization: "
            f"{missing_columns}. Check that the file contains Online Retail II data."
        )

    transactions["customer_id"] = transactions["customer_id"].apply(_format_customer_id)
    transactions = transactions[
        transactions["customer_id"].notna()
        & (transactions["customer_id"].astype(str).str.strip() != "")
    ]

    transactions["invoice_date"] = pd.to_datetime(
        transactions["invoice_date"],
        errors="coerce",
    )
    transactions = transactions[transactions["invoice_date"].notna()]

    transactions = transactions[
        ~transactions["invoice"].astype(str).str.strip().str.upper().str.startswith("C")
    ]

    transactions["quantity"] = pd.to_numeric(transactions["quantity"], errors="coerce")
    transactions["price"] = pd.to_numeric(transactions["price"], errors="coerce")
    transactions = transactions[
        (transactions["quantity"] > 0)
        & (transactions["price"] > 0)
        & transactions["quantity"].notna()
        & transactions["price"].notna()
    ]

    transactions = transactions.drop_duplicates().copy()
    transactions["revenue"] = transactions["quantity"] * transactions["price"]

    return transactions.reset_index(drop=True)


def add_synthetic_acquisition_channel(
    df: pd.DataFrame,
    random_state: int = 42,
) -> pd.DataFrame:
    """Assign one synthetic acquisition channel per customer."""
    transactions = df.copy()
    channels = np.array(
        [
            "organic_search",
            "paid_search",
            "social_media",
            "email",
            "referral",
            "direct",
        ]
    )
    probabilities = np.array([0.30, 0.20, 0.15, 0.15, 0.10, 0.10])

    customers = sorted(transactions["customer_id"].dropna().astype(str).unique())
    rng = np.random.default_rng(random_state)
    customer_channels = rng.choice(channels, size=len(customers), p=probabilities)
    channel_map = dict(zip(customers, customer_channels, strict=False))

    transactions["customer_id"] = transactions["customer_id"].astype(str)
    transactions["acquisition_channel"] = transactions["customer_id"].map(channel_map)

    return transactions


def prepare_transactions(
    raw_path: str | Path = "data/raw",
    processed_path: str | Path = "data/processed",
) -> pd.DataFrame:
    """Load, clean, enrich, and save prepared transaction data."""
    raw_df = load_online_retail_data(raw_path)
    transactions = normalize_columns(raw_df)
    transactions = clean_transactions(transactions)
    transactions = add_synthetic_acquisition_channel(transactions)
    transactions = add_cohort_features(transactions)

    processed_dir = Path(processed_path)
    processed_dir.mkdir(parents=True, exist_ok=True)
    transactions.to_csv(processed_dir / "transactions_prepared.csv", index=False)

    return transactions


def add_cohort_features(df: pd.DataFrame) -> pd.DataFrame:
    """Create reusable date and cohort features for retention analysis."""
    transactions = df.copy()
    transactions["invoice_date"] = pd.to_datetime(
        transactions["invoice_date"],
        errors="coerce",
    )
    transactions = transactions[transactions["invoice_date"].notna()].copy()

    transactions["order_date"] = transactions["invoice_date"].dt.date
    transactions["order_month"] = (
        transactions["invoice_date"].dt.to_period("M").dt.to_timestamp()
    )
    transactions["first_purchase_date"] = transactions.groupby("customer_id")[
        "invoice_date"
    ].transform("min")
    transactions["cohort_month"] = (
        transactions["first_purchase_date"].dt.to_period("M").dt.to_timestamp()
    )
    transactions["days_since_first_purchase"] = (
        transactions["invoice_date"].dt.normalize()
        - transactions["first_purchase_date"].dt.normalize()
    ).dt.days

    order_period = transactions["order_month"].dt.to_period("M")
    cohort_period = transactions["cohort_month"].dt.to_period("M")
    transactions["months_since_first_purchase"] = (
        (order_period.dt.year - cohort_period.dt.year) * 12
        + (order_period.dt.month - cohort_period.dt.month)
    )

    return transactions.reset_index(drop=True)


def _read_supported_file(file_path: Path) -> pd.DataFrame:
    suffix = file_path.suffix.lower()
    if suffix == ".csv":
        return _read_csv(file_path)
    if suffix in {".xlsx", ".xls"}:
        return _read_excel(file_path)
    if suffix == ".zip":
        return _read_zip(file_path)
    raise ValueError(f"Unsupported file extension: {file_path.suffix}")


def _read_zip(file_path: Path) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []

    with zipfile.ZipFile(file_path) as archive:
        members = [
            name
            for name in archive.namelist()
            if not name.endswith("/")
            and Path(name).suffix.lower() in {".csv", ".xlsx", ".xls"}
        ]

        if not members:
            raise FileNotFoundError(
                f"No CSV or Excel files were found inside ZIP archive: {file_path}"
            )

        members = sorted(
            members,
            key=lambda name: (
                0 if "online" in name.lower() and "retail" in name.lower() else 1,
                name.lower(),
            ),
        )

        for member in members:
            suffix = Path(member).suffix.lower()
            content = archive.read(member)
            if suffix == ".csv":
                frames.append(_read_csv(io.BytesIO(content)))
            else:
                frames.append(_read_excel(io.BytesIO(content)))

    return pd.concat(frames, ignore_index=True)


def _read_csv(source: str | Path | BinaryIO | io.BytesIO) -> pd.DataFrame:
    encodings = ["utf-8", "utf-8-sig", "latin1", "cp1252"]
    last_error: Exception | None = None

    for encoding in encodings:
        try:
            if isinstance(source, io.BytesIO):
                source.seek(0)
            return pd.read_csv(source, encoding=encoding, low_memory=False)
        except UnicodeDecodeError as error:
            last_error = error

    raise UnicodeDecodeError(
        "utf-8",
        b"",
        0,
        1,
        f"Could not decode CSV file. Last error: {last_error}",
    )


def _read_excel(source: str | Path | BinaryIO | io.BytesIO) -> pd.DataFrame:
    sheets = pd.read_excel(source, sheet_name=None)
    frames = [
        sheet_df
        for sheet_df in sheets.values()
        if not sheet_df.empty and not sheet_df.dropna(how="all").empty
    ]

    if not frames:
        raise ValueError("Excel file does not contain non-empty sheets.")

    return pd.concat(frames, ignore_index=True)


def _to_snake_case(value: object) -> str:
    text = str(value).strip()
    text = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", text)
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", text)
    text = re.sub(r"[^0-9a-zA-Z]+", "_", text)
    text = re.sub(r"_+", "_", text)
    return text.strip("_").lower()


def _format_customer_id(value: object) -> str | float:
    if pd.isna(value):
        return np.nan

    if isinstance(value, float) and value.is_integer():
        return str(int(value))

    text = str(value).strip()
    text = re.sub(r"\.0$", "", text)
    if text.lower() in {"nan", "none", "nat"}:
        return np.nan
    return text
