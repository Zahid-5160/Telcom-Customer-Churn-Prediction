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

from retain.config import CATEGORICAL_FEATURES, NUMERIC_FEATURES

#: Rough monthly pay expected at each level, used to judge whether somebody is
#: paid fairly *for their grade* rather than in absolute terms.
_LEVEL_ORDER = {"Entry": 1, "Junior": 2, "Mid": 3, "Senior": 4, "Executive": 5}


def _tenure_band(years: float) -> str:
    if years < 2:
        return "Under 2 years"
    if years < 5:
        return "2-5 years"
    if years < 10:
        return "5-10 years"
    return "10+ years"


def engineer(df: pd.DataFrame) -> pd.DataFrame:
    """Add the derived columns the model is trained on.

    * ``CareerShare`` - the share of their whole working life spent here. A
      30-year veteran with 28 years at this company is a very different person
      from a 30-year veteran who joined last year, even though tenure alone
      cannot tell them apart.
    * ``PromotionGap`` - years since the last promotion, relative to time at the
      company. Three years without a move means little in year twenty and a
      great deal in year four.
    * ``PayPerLevel`` - monthly pay divided by job grade. Catches the person
      being underpaid *for their grade*, which absolute salary hides.
    """
    df = df.copy()

    total_years = df["TotalWorkingYears"].astype(float)
    years_here = df["YearsAtCompany"].astype(float)
    since_promo = df["YearsSinceLastPromotion"].astype(float)
    income = df["MonthlyIncome"].astype(float)

    df["CareerShare"] = np.where(total_years > 0, years_here / total_years.replace(0, np.nan), 1.0)
    df["CareerShare"] = df["CareerShare"].fillna(1.0).clip(0, 1).round(3)

    df["PromotionGap"] = np.where(
        years_here > 0, since_promo / years_here.replace(0, np.nan), since_promo
    )
    df["PromotionGap"] = df["PromotionGap"].fillna(0.0).clip(0, 5).round(3)

    level = df["JobLevel"].map(_LEVEL_ORDER).fillna(1).astype(float)
    df["PayPerLevel"] = (income / level).round(0)

    df["TenureBand"] = years_here.apply(_tenure_band)

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
    """Glue the preprocessor to an estimator so the two travel together."""
    return Pipeline([("preprocess", build_preprocessor()), ("model", estimator)])


def model_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Engineer features and keep only the columns the model expects."""
    engineered = engineer(df)
    return engineered[list(CATEGORICAL_FEATURES) + NUMERIC_FEATURES]
