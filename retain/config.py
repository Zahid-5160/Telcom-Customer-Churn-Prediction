"""Central configuration: paths, column groups and business constants.

Everything another module needs to agree on lives here, so there is one place to
change a path, a category list or a risk band.
"""

from __future__ import annotations

from pathlib import Path

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent

DATA_DIR = PROJECT_ROOT / "data"
RAW_DATA_FILE = DATA_DIR / "raw" / "employee_attrition.csv"

MODELS_DIR = PROJECT_ROOT / "models"
MODEL_FILE = MODELS_DIR / "attrition_model.joblib"
METRICS_FILE = MODELS_DIR / "metrics.json"

REPORTS_DIR = PROJECT_ROOT / "reports"
INSIGHTS_FILE = REPORTS_DIR / "insights.json"
HISTORY_DB = REPORTS_DIR / "predictions.db"

WEB_DIR = PACKAGE_DIR / "web"

# --------------------------------------------------------------------------- #
# Currency
# --------------------------------------------------------------------------- #
CURRENCY = "INR"
CURRENCY_SYMBOL = "₹"

#: The published dataset records pay on a US scale. Every figure here has been
#: multiplied by 20 to land on a realistic Indian monthly salary range
#: (about 31,000 to 397,000 rupees). Multiplying every row by the same constant
#: cannot change which employees the model ranks as at risk - it only makes the
#: rupee figures mean something to an Indian HR team.
SALARY_SCALE_FACTOR = 20

# --------------------------------------------------------------------------- #
# Schema
# --------------------------------------------------------------------------- #
TARGET = "Attrition"
ID_COLUMN = "EmployeeID"

#: Numeric columns taken straight from the source file.
RAW_NUMERIC = [
    "Age",
    "MonthlyIncome",
    "DistanceFromHome",
    "PercentSalaryHike",
    "TrainingTimesLastYear",
    "NumCompaniesWorked",
    "TotalWorkingYears",
    "YearsAtCompany",
    "YearsInCurrentRole",
    "YearsSinceLastPromotion",
]

#: Numeric columns built by :mod:`retain.features`.
ENGINEERED_NUMERIC = ["CareerShare", "PromotionGap", "PayPerLevel"]

NUMERIC_FEATURES = RAW_NUMERIC + ENGINEERED_NUMERIC

#: Categorical columns and their allowed values. The form, the API validator and
#: the model all read this, so the three can never drift apart.
CATEGORICAL_FEATURES: dict[str, list[str]] = {
    "Department": ["Human Resources", "Research and Development", "Sales"],
    "JobRole": [
        "Healthcare Representative",
        "Human Resources",
        "Laboratory Technician",
        "Manager",
        "Manufacturing Director",
        "Research Director",
        "Research Scientist",
        "Sales Executive",
        "Sales Representative",
    ],
    "JobLevel": ["Entry", "Junior", "Mid", "Senior", "Executive"],
    "BusinessTravel": ["None", "Rare", "Frequent"],
    "OverTime": ["No", "Yes"],
    "MaritalStatus": ["Divorced", "Married", "Single"],
    "StockOptionLevel": ["None", "Basic", "Standard", "Premium"],
    "JobSatisfaction": ["Low", "Medium", "High", "Very High"],
    "EnvironmentSatisfaction": ["Low", "Medium", "High", "Very High"],
    "WorkLifeBalance": ["Low", "Medium", "High", "Very High"],
    "JobInvolvement": ["Low", "Medium", "High", "Very High"],
    "PerformanceRating": ["Meets expectations", "Exceeds expectations"],
    "TenureBand": ["Under 2 years", "2-5 years", "5-10 years", "10+ years"],
}

#: Recorded and reported on, but deliberately kept out of the model.
#:
#: Gender is a protected characteristic. Training on it would let the model
#: learn "women in this team leave more often" and then quietly price retention
#: offers by sex - unlawful in most jurisdictions and indefensible in all of
#: them. It stays in the data so HR can *monitor* attrition fairness, which is a
#: legitimate and different job from predicting with it.
EXCLUDED_FROM_MODEL = ["Gender"]

#: Fields a user fills in on the form (engineered ones are derived from these).
FORM_FIELDS = [c for c in CATEGORICAL_FEATURES if c != "TenureBand"]

# --------------------------------------------------------------------------- #
# Business rules
# --------------------------------------------------------------------------- #
#: Probability cut-offs that turn a score into something a manager can act on.
RISK_BANDS = [
    (0.00, 0.25, "Low", "Settled. Keep doing what you are doing."),
    (0.25, 0.50, "Moderate", "Worth a check-in at the next one-to-one."),
    (0.50, 0.75, "High", "Book a stay interview this month."),
    (0.75, 1.01, "Critical", "Escalate to HR and the line manager this week."),
]

#: What it costs to replace somebody, as a multiple of their monthly pay.
#: Six months of salary is the widely used mid-range estimate once recruitment,
#: notice period, onboarding and lost productivity are counted.
REPLACEMENT_COST_MONTHS = 6

RANDOM_STATE = 42

#: 50 employees is too few for a hold-out test set, so every employee is scored
#: by models that never saw them. See ``retain/train.py``.
CV_FOLDS = 5
CV_REPEATS = 10


def risk_band(probability: float) -> tuple[str, str]:
    """Return the ``(label, advice)`` pair for an attrition probability."""
    for low, high, label, advice in RISK_BANDS:
        if low <= probability < high:
            return label, advice
    return RISK_BANDS[-1][2], RISK_BANDS[-1][3]
