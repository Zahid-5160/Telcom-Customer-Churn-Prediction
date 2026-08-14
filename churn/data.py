"""Loading and cleaning of the raw telco dataset.

The raw file ships with two quirks that every downstream step depends on being
fixed: ``TotalCharges`` is text (blank for brand-new customers) and
``SeniorCitizen`` is stored as 0/1 rather than No/Yes.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from churn.config import ID_COLUMN, RAW_DATA_FILE, TARGET


def load_raw(path: Path | str = RAW_DATA_FILE) -> pd.DataFrame:
    """Read the CSV exactly as delivered, without any cleaning."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"Dataset not found at {path}. Expected the telco churn CSV in data/raw/."
        )
    return pd.read_csv(path)


def clean(df: pd.DataFrame) -> pd.DataFrame:
    """Return a tidy copy of the dataset.

    * ``TotalCharges`` becomes a float; the 11 blank rows all have ``tenure == 0``
      (customers who joined this month and have not been billed yet), so 0 is the
      factually correct fill rather than a mean/median guess.
    * ``SeniorCitizen`` becomes No/Yes so it reads like every other flag column.
    * Duplicate customer IDs are dropped, keeping the first occurrence.
    """
    df = df.copy()

    df["TotalCharges"] = pd.to_numeric(
        df["TotalCharges"].astype(str).str.strip().replace("", "0"), errors="coerce"
    ).fillna(0.0)

    if df["SeniorCitizen"].dtype != object:
        df["SeniorCitizen"] = df["SeniorCitizen"].map({0: "No", 1: "Yes"})

    # Trim stray whitespace from every text column. Selecting by dtype name is
    # avoided because pandas 2 calls these "object" and pandas 3 calls them "str".
    for column in df.columns:
        if pd.api.types.is_string_dtype(df[column]):
            df[column] = df[column].str.strip()

    if ID_COLUMN in df.columns:
        df = df.drop_duplicates(subset=ID_COLUMN, keep="first")

    return df.reset_index(drop=True)


def split_features_target(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """Split a cleaned frame into features and a 1/0 churn target."""
    target = (df[TARGET].str.lower() == "yes").astype(int)
    features = df.drop(columns=[c for c in (TARGET, ID_COLUMN) if c in df.columns])
    return features, target


def load_clean(path: Path | str = RAW_DATA_FILE) -> pd.DataFrame:
    """Convenience wrapper: load the CSV and clean it in one call."""
    return clean(load_raw(path))
