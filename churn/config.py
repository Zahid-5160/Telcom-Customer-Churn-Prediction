"""Central configuration: paths, column groups and business constants.

Everything that another module might need to agree on lives here, so there is a
single place to change a path or a category list.
"""

from __future__ import annotations

from pathlib import Path

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent

DATA_DIR = PROJECT_ROOT / "data"
RAW_DATA_FILE = DATA_DIR / "raw" / "customer_churn.csv"

MODELS_DIR = PROJECT_ROOT / "models"
MODEL_FILE = MODELS_DIR / "churn_model.joblib"
METRICS_FILE = MODELS_DIR / "metrics.json"

REPORTS_DIR = PROJECT_ROOT / "reports"
INSIGHTS_FILE = REPORTS_DIR / "insights.json"

WEB_DIR = PACKAGE_DIR / "web"
HISTORY_DB = REPORTS_DIR / "predictions.db"

# --------------------------------------------------------------------------- #
# Schema
# --------------------------------------------------------------------------- #
TARGET = "Churn"
ID_COLUMN = "customerID"

#: Numeric columns present in the raw file.
RAW_NUMERIC = ["tenure", "MonthlyCharges", "TotalCharges"]

#: Engineered numeric columns produced by :mod:`churn.features`.
ENGINEERED_NUMERIC = ["NumServices", "AvgMonthlySpend", "ChargeRatio"]

NUMERIC_FEATURES = RAW_NUMERIC + ENGINEERED_NUMERIC

#: Categorical columns and their allowed values. The UI form and the API
#: validator are both generated from this mapping, so they can never drift.
CATEGORICAL_FEATURES: dict[str, list[str]] = {
    "gender": ["Female", "Male"],
    "SeniorCitizen": ["No", "Yes"],
    "Partner": ["No", "Yes"],
    "Dependents": ["No", "Yes"],
    "PhoneService": ["No", "Yes"],
    "MultipleLines": ["No", "No phone service", "Yes"],
    "InternetService": ["DSL", "Fiber optic", "No"],
    "OnlineSecurity": ["No", "No internet service", "Yes"],
    "OnlineBackup": ["No", "No internet service", "Yes"],
    "DeviceProtection": ["No", "No internet service", "Yes"],
    "TechSupport": ["No", "No internet service", "Yes"],
    "StreamingTV": ["No", "No internet service", "Yes"],
    "StreamingMovies": ["No", "No internet service", "Yes"],
    "Contract": ["Month-to-month", "One year", "Two year"],
    "PaperlessBilling": ["No", "Yes"],
    "PaymentMethod": [
        "Bank transfer (automatic)",
        "Credit card (automatic)",
        "Electronic check",
        "Mailed check",
    ],
    "TenureBand": ["0-6 months", "6-12 months", "1-2 years", "2-4 years", "4+ years"],
}

#: Add-on services counted by the ``NumServices`` feature.
SERVICE_COLUMNS = [
    "PhoneService",
    "MultipleLines",
    "InternetService",
    "OnlineSecurity",
    "OnlineBackup",
    "DeviceProtection",
    "TechSupport",
    "StreamingTV",
    "StreamingMovies",
]

#: Fields a user actually fills in on the form (engineered ones are derived).
FORM_FIELDS = [c for c in CATEGORICAL_FEATURES if c != "TenureBand"]

# --------------------------------------------------------------------------- #
# Business rules
# --------------------------------------------------------------------------- #
#: Probability cut-offs that turn a score into a human-readable risk band.
RISK_BANDS = [
    (0.00, 0.25, "Low", "Healthy relationship - keep serving well."),
    (0.25, 0.50, "Moderate", "Worth watching at the next renewal window."),
    (0.50, 0.75, "High", "Reach out proactively with a retention offer."),
    (0.75, 1.01, "Critical", "Escalate to a retention specialist today."),
]

RANDOM_STATE = 42

#: This project ships a deliberately small 50-customer dataset, so a single
#: hold-out split would leave ~10 test rows and produce meaningless scores.
#: Instead every customer is scored by a model that never saw them, using
#: repeated stratified cross-validation. See ``churn/train.py``.
CV_FOLDS = 5
CV_REPEATS = 10


def risk_band(probability: float) -> tuple[str, str]:
    """Return the ``(label, advice)`` pair for a churn probability."""
    for low, high, label, advice in RISK_BANDS:
        if low <= probability < high:
            return label, advice
    return RISK_BANDS[-1][2], RISK_BANDS[-1][3]
