"""Scoring an employee, and explaining why the model scored them that way.

Two explanations accompany every prediction, both produced by asking the model
"what if?" rather than by reading its internals - which means they work
identically whichever of the three candidate models happened to win.

* **Drivers** - swap one attribute for the typical employee's value and see how
  far the risk moves. That isolates what makes *this* person unusual.
* **Actions** - try every alternative for each attribute a manager can actually
  influence, and keep the single change that lowers the risk most.
"""

from __future__ import annotations

import threading
from functools import lru_cache
from typing import Any

import joblib
import pandas as pd

from retain.config import (
    CATEGORICAL_FEATURES,
    MODEL_FILE,
    NUMERIC_FEATURES,
    RAW_NUMERIC,
    REPLACEMENT_COST_MONTHS,
    risk_band,
)
from retain.features import engineer

#: What a manager or HR can realistically change, and how to describe it.
#: Several of these are *measurements* rather than dials - you cannot decree
#: that somebody feels satisfied - so the wording describes the intervention,
#: not the setting.
PLAYBOOK: dict[str, str] = {
    "OverTime": "Rebalance their workload so the overtime stops.",
    "StockOptionLevel": "Grant equity, or move them up an equity band.",
    "JobSatisfaction": "Run a stay interview and act on what the role is missing.",
    "EnvironmentSatisfaction": "Address the team environment and their manager relationship.",
    "WorkLifeBalance": "Agree firmer hours or flexible working.",
    "JobInvolvement": "Give them ownership of something visible.",
    "BusinessTravel": "Cut their travel load, or share it around the team.",
    "JobLevel": "Put them forward for promotion at the next review.",
    "Department": "",
    "JobRole": "",
    "MaritalStatus": "",
    "PerformanceRating": "",
    "TenureBand": "",
}

#: Categorical fields a retention plan is allowed to touch.
ACTIONABLE = [field for field, pitch in PLAYBOOK.items() if pitch]

#: For each actionable field, the values ordered worst to best.
#:
#: This exists because the counterfactual search will happily report that
#: *lowering* somebody's involvement reduces their attrition risk - a quirk of a
#: 50-row sample - and then pair that with the recommendation "give them
#: ownership of something visible". The advice would contradict the change it
#: was based on. Only moves *up* one of these ladders are ever proposed, so a
#: recommendation can never argue for making somebody's job worse.
IMPROVEMENTS: dict[str, list[str]] = {
    "OverTime": ["Yes", "No"],
    "BusinessTravel": ["Frequent", "Rare", "None"],
    "StockOptionLevel": ["None", "Basic", "Standard", "Premium"],
    "JobSatisfaction": ["Low", "Medium", "High", "Very High"],
    "EnvironmentSatisfaction": ["Low", "Medium", "High", "Very High"],
    "WorkLifeBalance": ["Low", "Medium", "High", "Very High"],
    "JobInvolvement": ["Low", "Medium", "High", "Very High"],
    "JobLevel": ["Entry", "Junior", "Mid", "Senior", "Executive"],
}


def _is_improvement(field: str, current: str, option: str) -> bool:
    """True when moving from ``current`` to ``option`` is genuinely better."""
    ladder = IMPROVEMENTS.get(field)
    if ladder is None:
        return True
    if current not in ladder or option not in ladder:
        return False
    return ladder.index(option) > ladder.index(current)

#: Pay rises to test, as a fraction of current salary. Salary is a number rather
#: than a category, so it needs its own set of counterfactuals.
PAY_RISES = (0.10, 0.20)

_LOCK = threading.Lock()


class ModelNotTrained(RuntimeError):
    """Raised when the saved model file is missing."""


@lru_cache(maxsize=1)
def load_artifact() -> dict[str, Any]:
    """Load the trained pipeline once and keep it in memory."""
    if not MODEL_FILE.exists():
        raise ModelNotTrained(
            "No trained model found. Run `python main.py train` to create "
            "models/attrition_model.joblib."
        )
    artifact = joblib.load(MODEL_FILE)

    # Training fits hundreds of trees at once and rightly uses every core.
    # Serving does the opposite: a handful of rows through an already fitted
    # forest, where handing work to threads costs more than the work itself.
    # Single-threaded scoring measured about twice as fast, bit-for-bit
    # identical results.
    model = artifact["pipeline"].named_steps.get("model")
    if hasattr(model, "n_jobs"):
        model.n_jobs = 1

    return artifact


def reset_cache() -> None:
    """Forget the cached model so a freshly trained one is picked up."""
    load_artifact.cache_clear()


#: Column names as a human would say them.
FRIENDLY = {
    "Age": "Age",
    "MonthlyIncome": "Monthly salary",
    "DistanceFromHome": "Commute distance",
    "PercentSalaryHike": "Last pay rise",
    "TrainingTimesLastYear": "Training sessions last year",
    "NumCompaniesWorked": "Previous employers",
    "TotalWorkingYears": "Total experience",
    "YearsAtCompany": "Years with us",
    "YearsInCurrentRole": "Years in current role",
    "YearsSinceLastPromotion": "Years since promotion",
    "CareerShare": "Share of career spent here",
    "PromotionGap": "Promotion gap",
    "PayPerLevel": "Pay for their grade",
    "OverTime": "Overtime",
    "JobLevel": "Job level",
    "JobRole": "Role",
    "JobSatisfaction": "Job satisfaction",
    "EnvironmentSatisfaction": "Work environment",
    "WorkLifeBalance": "Work-life balance",
    "JobInvolvement": "Involvement",
    "StockOptionLevel": "Equity",
    "BusinessTravel": "Business travel",
    "MaritalStatus": "Marital status",
    "Department": "Department",
    "PerformanceRating": "Performance",
    "TenureBand": "Time here",
}


def _friendly(field: str) -> str:
    return FRIENDLY.get(field, field)


def _prepare(records: list[dict]) -> pd.DataFrame:
    """Run raw form input through the same feature engineering as training."""
    frame = pd.DataFrame(records)
    for column in RAW_NUMERIC:
        frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0)
    engineered = engineer(frame)
    return engineered[list(CATEGORICAL_FEATURES) + NUMERIC_FEATURES]


def _probabilities(pipeline, frame: pd.DataFrame):
    with _LOCK:
        return pipeline.predict_proba(frame)[:, 1]


def predict_many(records: list[dict]) -> list[float]:
    """Attrition probability for a list of employees, in one vectorised pass."""
    artifact = load_artifact()
    return [float(p) for p in _probabilities(artifact["pipeline"], _prepare(records))]


def _build_variants(record: dict, baseline: dict) -> tuple[list[dict], list[tuple]]:
    """Every "what if" version of this employee needed to explain them."""
    variants: list[dict] = []
    labels: list[tuple] = []  # (kind, field, replacement value, display)

    # 1. Drivers: replace one field with the typical employee's value.
    for field in list(CATEGORICAL_FEATURES) + RAW_NUMERIC:
        if field == "TenureBand" or field not in record:
            continue
        typical = baseline.get(field)
        if typical is None or str(record[field]) == str(typical):
            continue
        variants.append({**record, field: typical})
        labels.append(("driver", field, typical, str(typical)))

    # 2. Actions on categorical fields - improvements only.
    for field in ACTIONABLE:
        if field not in record:
            continue
        for option in CATEGORICAL_FEATURES.get(field, []):
            if option == record[field] or not _is_improvement(field, record[field], option):
                continue
            variants.append({**record, field: option})
            labels.append(("action", field, option, option))

    # 3. Actions on salary, which is a number rather than a category.
    current = float(record.get("MonthlyIncome") or 0)
    if current > 0:
        for rise in PAY_RISES:
            raised = round(current * (1 + rise), -2)
            variants.append({**record, "MonthlyIncome": raised})
            labels.append(("pay", "MonthlyIncome", raised, f"+{rise:.0%}"))

    return variants, labels


def _interpret(record: dict, base: float, labels: list[tuple], scores) -> tuple[list, list]:
    """Turn the scored variants into the driver and action lists."""
    drivers: list[dict] = []
    actions: dict[str, dict] = {}

    for (kind, field, value, display), score in zip(labels, scores):
        delta = base - float(score)

        if kind == "driver":
            drivers.append(
                {
                    "field": field,
                    "label": _friendly(field),
                    "value": record[field],
                    "compared_to": display,
                    "impact": round(delta, 4),
                    "direction": "increases" if delta > 0 else "decreases",
                }
            )
            continue

        if delta <= 0.01:  # only keep changes that genuinely reduce the risk
            continue

        if kind == "pay":
            recommendation = (
                f"Raise their salary by {display} - a market correction, not a counter-offer."
            )
        else:
            recommendation = PLAYBOOK[field]

        best = actions.get(field)
        if best is None or delta > best["reduction"]:
            actions[field] = {
                "field": field,
                "label": _friendly(field),
                "from": record[field],
                "to": value,
                "display": display,
                "reduction": round(delta, 4),
                "new_probability": round(float(score), 4),
                "recommendation": recommendation,
                "kind": kind,
            }

    drivers.sort(key=lambda d: abs(d["impact"]), reverse=True)
    ranked = sorted(actions.values(), key=lambda a: a["reduction"], reverse=True)
    return drivers[:6], ranked[:4]


def predict(record: dict, explain: bool = True) -> dict:
    """Score one employee and describe the result in business language.

    The employee and all their "what if" variants go through the model in a
    single batch, so a fully explained prediction costs one pass, not two.
    """
    artifact = load_artifact()
    threshold = artifact["threshold"]

    variants, labels = _build_variants(record, artifact["baseline"]) if explain else ([], [])
    frame = _prepare([record, *variants])
    scores = _probabilities(artifact["pipeline"], frame)
    probability = float(scores[0])
    band, advice = risk_band(probability)

    result = {
        "probability": round(probability, 4),
        "percent": round(probability * 100, 1),
        "will_leave": bool(probability >= threshold),
        "threshold": threshold,
        "risk_band": band,
        "advice": advice,
        "model": artifact.get("model_label", "model"),
        "engineered": {
            "CareerShare": float(frame["CareerShare"].iloc[0]),
            "PromotionGap": float(frame["PromotionGap"].iloc[0]),
            "PayPerLevel": float(frame["PayPerLevel"].iloc[0]),
            "TenureBand": str(frame["TenureBand"].iloc[0]),
        },
    }

    if explain:
        drivers, actions = _interpret(record, probability, labels, scores[1:])
        result["drivers"] = drivers
        result["actions"] = actions
        # Expected cost of losing them: replacement cost weighted by the risk.
        salary = float(record.get("MonthlyIncome") or 0)
        result["cost_at_risk"] = int(round(salary * REPLACEMENT_COST_MONTHS * probability))

    return result
