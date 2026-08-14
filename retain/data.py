"""Loading and cleaning of the employee dataset."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from retain.config import EXCLUDED_FROM_MODEL, ID_COLUMN, RAW_DATA_FILE, RAW_NUMERIC, TARGET


def load_raw(path: Path | str = RAW_DATA_FILE) -> pd.DataFrame:
    """Read the CSV exactly as delivered, without any cleaning.

    ``keep_default_na`` matters more than it looks. Pandas treats the literal
    text ``None`` as a missing value by default, and two columns here use
    ``None`` as a real category - no equity grant, and no business travel.
    Left alone, a quarter of the workforce would silently vanish from those
    breakdowns. Only a genuinely empty cell counts as missing.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"Dataset not found at {path}. Expected the employee attrition CSV in data/raw/."
        )
    return pd.read_csv(path, keep_default_na=False, na_values=[""])


def clean(df: pd.DataFrame) -> pd.DataFrame:
    """Return a tidy copy of the dataset.

    The source file is already well formed, so this mostly guards against the
    ways a hand-edited HR export goes wrong: stray whitespace, numbers stored as
    text, and duplicated employee IDs after two exports are concatenated.
    """
    df = df.copy()

    for column in df.columns:
        if pd.api.types.is_string_dtype(df[column]):
            df[column] = df[column].str.strip()

    for column in RAW_NUMERIC:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce").fillna(0)

    if ID_COLUMN in df.columns:
        df = df.drop_duplicates(subset=ID_COLUMN, keep="first")

    return df.reset_index(drop=True)


def split_features_target(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """Split a cleaned frame into features and a 1/0 attrition target.

    The employee ID and any protected characteristic are dropped here, so they
    physically cannot reach the model even by accident.
    """
    target = (df[TARGET].str.lower() == "yes").astype(int)
    drop = [TARGET, ID_COLUMN, *EXCLUDED_FROM_MODEL]
    features = df.drop(columns=[c for c in drop if c in df.columns])
    return features, target


def load_clean(path: Path | str = RAW_DATA_FILE) -> pd.DataFrame:
    """Convenience wrapper: load the CSV and clean it in one call."""
    return clean(load_raw(path))
