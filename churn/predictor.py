"""Scoring a customer, and explaining why the model scored them that way.

Two explanations are produced for every prediction, both by asking the model
"what if?" rather than by reading its internals - which means they work
identically whichever of the three candidate models happened to win.

* **Drivers** - swap one attribute for the typical customer's value and see how
  far the risk moves. That isolates what makes *this* customer unusual.
* **Actions** - try every alternative value for each attribute and keep the
  single change that lowers risk most. That turns a score into something a
  retention team can actually do on Monday morning.
"""

from __future__ import annotations

import threading
from functools import lru_cache
from typing import Any

import joblib
import pandas as pd

from churn.config import (
    CATEGORICAL_FEATURES,
    MODEL_FILE,
    NUMERIC_FEATURES,
    RAW_NUMERIC,
    risk_band,
)
from churn.features import engineer

#: Changes a retention team can realistically offer, with the pitch to use.
PLAYBOOK: dict[str, str] = {
    "Contract": "Offer a discounted annual or two-year contract at renewal.",
    "PaymentMethod": "Move them onto automatic payment with a small billing credit.",
    "TechSupport": "Bundle tech support in free for the first year.",
    "OnlineSecurity": "Add online security to the plan at no extra cost.",
    "OnlineBackup": "Include online backup as a loyalty perk.",
    "DeviceProtection": "Add device protection to increase the value of staying.",
    "InternetService": "Review the connection - a service quality check or a plan change.",
    "PaperlessBilling": "Check the billing experience; paper billing may suit them better.",
    "StreamingTV": "Offer a streaming add-on trial to deepen the bundle.",
    "StreamingMovies": "Offer a movies add-on trial to deepen the bundle.",
    "MultipleLines": "Propose a multi-line family plan.",
    "Dependents": "",
    "Partner": "",
    "gender": "",
    "SeniorCitizen": "",
    "PhoneService": "Review whether a phone line belongs in their bundle.",
}

#: Attributes the business can change. Age and gender are neither actionable nor
#: appropriate to build a retention offer around, so they are excluded here.
ACTIONABLE = [f for f, pitch in PLAYBOOK.items() if pitch]

_LOCK = threading.Lock()


class ModelNotTrained(RuntimeError):
    """Raised when the saved model file is missing."""


@lru_cache(maxsize=1)
def load_artifact() -> dict[str, Any]:
    """Load the trained pipeline once and keep it in memory."""
    if not MODEL_FILE.exists():
        raise ModelNotTrained(
            "No trained model found. Run `python main.py train` to create models/churn_model.joblib."
        )
    artifact = joblib.load(MODEL_FILE)

    # Training fits 300 trees at once and rightly uses every core. Serving does
    # the opposite: a handful of rows through an already-fitted forest. There the
    # thread hand-off costs more than the work itself, so scoring a single
    # customer measured about twice as fast single-threaded. Results are
    # bit-for-bit identical either way.
    model = artifact["pipeline"].named_steps.get("model")
    if hasattr(model, "n_jobs"):
        model.n_jobs = 1

    return artifact


def reset_cache() -> None:
    """Forget the cached model so a freshly trained one is picked up."""
    load_artifact.cache_clear()


def _friendly(field: str) -> str:
    """Turn a column name into something readable in the UI."""
    words = {
        "tenure": "Months as a customer",
        "MonthlyCharges": "Monthly bill",
        "TotalCharges": "Lifetime spend",
        "NumServices": "Number of services",
        "AvgMonthlySpend": "Average monthly spend",
        "ChargeRatio": "Recent price change",
        "SeniorCitizen": "Senior citizen",
        "PaymentMethod": "Payment method",
        "InternetService": "Internet service",
        "PaperlessBilling": "Paperless billing",
        "TechSupport": "Tech support",
        "OnlineSecurity": "Online security",
        "OnlineBackup": "Online backup",
        "DeviceProtection": "Device protection",
        "StreamingTV": "Streaming TV",
        "StreamingMovies": "Streaming movies",
        "MultipleLines": "Multiple lines",
        "PhoneService": "Phone service",
        "TenureBand": "Time as a customer",
    }
    return words.get(field, field)


def _prepare(records: list[dict]) -> pd.DataFrame:
    """Run raw form input through the same feature engineering as training."""
    frame = pd.DataFrame(records)
    for column in RAW_NUMERIC:
        frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0.0)
    engineered = engineer(frame)
    return engineered[list(CATEGORICAL_FEATURES) + NUMERIC_FEATURES]


def _probabilities(pipeline, frame: pd.DataFrame):
    with _LOCK:
        return pipeline.predict_proba(frame)[:, 1]


def predict_many(records: list[dict]) -> list[float]:
    """Churn probability for a list of customers, in one vectorised pass."""
    artifact = load_artifact()
    return [float(p) for p in _probabilities(artifact["pipeline"], _prepare(records))]


def _build_variants(record: dict, baseline: dict) -> tuple[list[dict], list[tuple[str, str, str]]]:
    """Every "what if" version of this customer we need in order to explain them."""
    variants: list[dict] = []
    labels: list[tuple[str, str, str]] = []  # (kind, field, replacement value)

    # 1. Drivers: replace one field with the typical customer's value.
    for field in list(CATEGORICAL_FEATURES) + RAW_NUMERIC:
        if field == "TenureBand" or field not in record:
            continue
        typical = baseline.get(field)
        if typical is None or str(record[field]) == str(typical):
            continue
        variants.append({**record, field: typical})
        labels.append(("driver", field, str(typical)))

    # 2. Actions: try each alternative value of every changeable field.
    for field in ACTIONABLE:
        if field not in record:
            continue
        for option in CATEGORICAL_FEATURES.get(field, []):
            if option == record[field]:
                continue
            variants.append({**record, field: option})
            labels.append(("action", field, option))

    return variants, labels


def _interpret(
    record: dict,
    base_probability: float,
    labels: list[tuple[str, str, str]],
    scores,
) -> tuple[list[dict], list[dict]]:
    """Turn the scored variants into the driver and action lists."""
    drivers: list[dict] = []
    actions: dict[str, dict] = {}

    for (kind, field, value), score in zip(labels, scores):
        delta = base_probability - float(score)
        if kind == "driver":
            drivers.append(
                {
                    "field": field,
                    "label": _friendly(field),
                    "value": record[field],
                    "compared_to": value,
                    "impact": round(delta, 4),
                    "direction": "increases" if delta > 0 else "decreases",
                }
            )
        elif delta > 0.01:  # only keep changes that genuinely reduce risk
            best = actions.get(field)
            if best is None or delta > best["reduction"]:
                actions[field] = {
                    "field": field,
                    "label": _friendly(field),
                    "from": record[field],
                    "to": value,
                    "reduction": round(delta, 4),
                    "new_probability": round(float(score), 4),
                    "recommendation": PLAYBOOK[field],
                }

    drivers.sort(key=lambda d: abs(d["impact"]), reverse=True)
    ranked_actions = sorted(actions.values(), key=lambda a: a["reduction"], reverse=True)

    return drivers[:6], ranked_actions[:4]


def predict(record: dict, explain: bool = True) -> dict:
    """Score one customer and describe the result in business language.

    The customer and all their "what if" variants go through the model in a
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
        "will_churn": bool(probability >= threshold),
        "threshold": threshold,
        "risk_band": band,
        "advice": advice,
        "model": artifact.get("model_label", "model"),
        "engineered": {
            "NumServices": int(frame["NumServices"].iloc[0]),
            "AvgMonthlySpend": float(frame["AvgMonthlySpend"].iloc[0]),
            "ChargeRatio": float(frame["ChargeRatio"].iloc[0]),
            "TenureBand": str(frame["TenureBand"].iloc[0]),
        },
    }

    if explain:
        drivers, actions = _interpret(record, probability, labels, scores[1:])
        result["drivers"] = drivers
        result["actions"] = actions
        result["value_at_risk"] = round(float(record.get("MonthlyCharges", 0)) * 12 * probability, 2)

    return result
