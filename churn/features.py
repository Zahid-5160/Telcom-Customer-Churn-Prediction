"""Feature engineering and the scikit-learn preprocessing pipeline.

The same :func:`engineer` function runs at training time and at prediction time,
which is what keeps a live request looking exactly like a training row.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from churn.config import CATEGORICAL_FEATURES, NUMERIC_FEATURES, SERVICE_COLUMNS

#: Values that mean "the customer does not have this service".
_NEGATIVE = {"no", "no internet service", "no phone service"}


def _tenure_band(months: float) -> str:
    if months < 6:
        return "0-6 months"
    if months < 12:
        return "6-12 months"
    if months < 24:
        return "1-2 years"
    if months < 48:
        return "2-4 years"
    return "4+ years"


def engineer(df: pd.DataFrame) -> pd.DataFrame:
    """Add the derived columns the model is trained on.

    * ``NumServices`` - how many of the nine add-ons the customer actually uses.
      Bundled customers are stickier, so the count carries real signal.
    * ``AvgMonthlySpend`` - lifetime spend divided by tenure, i.e. what the
      customer has historically paid per month.
    * ``ChargeRatio`` - today's bill versus that historical average. A value well
      above 1 means the customer was recently upsold or repriced.
    * ``TenureBand`` - tenure bucketed the way a retention team talks about it.
    """
    df = df.copy()

    services = [c for c in SERVICE_COLUMNS if c in df.columns]
    df["NumServices"] = (
        df[services]
        .apply(lambda col: ~col.astype(str).str.strip().str.lower().isin(_NEGATIVE))
        .sum(axis=1)
        .astype(int)
    )

    tenure = df["tenure"].astype(float)
    monthly = df["MonthlyCharges"].astype(float)
    total = df["TotalCharges"].astype(float)

    # A brand-new customer has no history, so fall back to the current bill.
    df["AvgMonthlySpend"] = np.where(tenure > 0, total / tenure.replace(0, np.nan), monthly)
    df["AvgMonthlySpend"] = df["AvgMonthlySpend"].fillna(monthly).round(2)

    df["ChargeRatio"] = (monthly / df["AvgMonthlySpend"].replace(0, np.nan)).fillna(1.0)
    df["ChargeRatio"] = df["ChargeRatio"].clip(0, 5).round(3)

    df["TenureBand"] = tenure.apply(_tenure_band)

    return df


def build_preprocessor() -> ColumnTransformer:
    """One-hot encode the categoricals and standardise the numerics."""
    return ColumnTransformer(
        transformers=[
            (
                "categorical",
                OneHotEncoder(handle_unknown="ignore", sparse_output=False),
                list(CATEGORICAL_FEATURES),
            ),
            ("numeric", StandardScaler(), NUMERIC_FEATURES),
        ],
        remainder="drop",
        verbose_feature_names_out=False,
    )


def build_pipeline(estimator) -> Pipeline:
    """Glue the preprocessor to an estimator so both travel together."""
    return Pipeline([("preprocess", build_preprocessor()), ("model", estimator)])


def model_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Engineer features and keep only the columns the model expects."""
    engineered = engineer(df)
    return engineered[list(CATEGORICAL_FEATURES) + NUMERIC_FEATURES]
