"""Model training, selection and evaluation.

Run with ``python main.py train``.

Evaluation strategy
-------------------
The bundled dataset holds 50 customers. Carving out a hold-out test set would
leave roughly ten rows and three churners, and any score computed on that would
be noise. So instead of one split we run *repeated stratified cross-validation*:
the data is split five ways, each fifth is predicted by a model trained on the
other four, and the whole exercise repeats ten times with different shuffles.
Every customer therefore gets scored many times by models that never saw them,
and the reported metrics are the average across all of it - the honest way to
measure a model on a small sample.

Three candidates compete, the best average ROC-AUC wins, its decision threshold
is tuned on out-of-fold predictions, and the winner is finally refitted on all
50 customers before being saved.
"""

from __future__ import annotations

import json
import time
import warnings
from dataclasses import dataclass
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    precision_recall_curve,
    precision_score,
    recall_score,
    roc_auc_score,
    roc_curve,
)
from sklearn.model_selection import RepeatedStratifiedKFold, cross_val_predict

from churn.config import (
    CV_FOLDS,
    CV_REPEATS,
    METRICS_FILE,
    MODEL_FILE,
    MODELS_DIR,
    RANDOM_STATE,
)
from churn.data import load_clean, split_features_target
from churn.features import build_pipeline, model_frame


@dataclass(frozen=True)
class Candidate:
    """A named estimator plus the plain-English reason it is in the race."""

    key: str
    label: str
    rationale: str
    estimator: Any


def candidates() -> list[Candidate]:
    """The three models we compare, from most explainable to most powerful.

    Every hyper-parameter here is deliberately conservative - shallow trees, few
    leaves, strong regularisation - because with 50 rows an unconstrained model
    memorises the data instead of learning from it.
    """
    return [
        Candidate(
            key="logistic_regression",
            label="Logistic Regression",
            rationale="Transparent linear baseline - every feature gets a readable weight.",
            estimator=LogisticRegression(
                C=0.5,
                max_iter=5000,
                class_weight="balanced",
                random_state=RANDOM_STATE,
            ),
        ),
        Candidate(
            key="random_forest",
            label="Random Forest",
            rationale="Hundreds of shallow decision trees voting together.",
            estimator=RandomForestClassifier(
                n_estimators=300,
                max_depth=4,
                min_samples_leaf=3,
                max_features="sqrt",
                class_weight="balanced_subsample",
                n_jobs=-1,
                random_state=RANDOM_STATE,
            ),
        ),
        Candidate(
            key="gradient_boosting",
            label="Gradient Boosting",
            rationale="Trees built in sequence, each correcting the last one's mistakes.",
            estimator=GradientBoostingClassifier(
                n_estimators=120,
                learning_rate=0.05,
                max_depth=2,
                min_samples_leaf=4,
                subsample=0.9,
                random_state=RANDOM_STATE,
            ),
        ),
    ]


def _cv() -> RepeatedStratifiedKFold:
    return RepeatedStratifiedKFold(
        n_splits=CV_FOLDS, n_repeats=CV_REPEATS, random_state=RANDOM_STATE
    )


def _out_of_fold(pipeline, X: pd.DataFrame, y: pd.Series) -> np.ndarray:
    """Average out-of-fold churn probability for every customer.

    ``cross_val_predict`` cannot be used directly with repeated splits (each row
    would appear once per repeat), so the repeats are averaged by hand.
    """
    folds = np.zeros((CV_REPEATS, len(X)), dtype=float)
    for repeat in range(CV_REPEATS):
        cv = RepeatedStratifiedKFold(
            n_splits=CV_FOLDS, n_repeats=1, random_state=RANDOM_STATE + repeat
        )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            folds[repeat] = cross_val_predict(
                pipeline, X, y, cv=cv, method="predict_proba", n_jobs=-1
            )[:, 1]
    return folds.mean(axis=0)


def _tune_threshold(y_true: np.ndarray, probabilities: np.ndarray) -> float:
    """Pick the probability cut-off with the best F1 score.

    The textbook 0.50 is a poor fit here: only about a third of these customers
    churn, and missing a leaver costs far more than one unnecessary phone call.
    """
    precision, recall, thresholds = precision_recall_curve(y_true, probabilities)
    if not len(thresholds):
        return 0.5
    f1 = np.divide(
        2 * precision * recall,
        precision + recall,
        out=np.zeros_like(precision),
        where=(precision + recall) > 0,
    )
    # Rounded here, once, so the leaderboard and the final report agree exactly.
    return round(float(np.clip(thresholds[int(np.argmax(f1[:-1]))], 0.15, 0.85)), 3)


def _curve_points(x: np.ndarray, y: np.ndarray, limit: int = 60) -> list[dict[str, float]]:
    """Down-sample a curve so the JSON stays small but the shape survives."""
    idx = (
        np.arange(len(x))
        if len(x) <= limit
        else np.unique(np.linspace(0, len(x) - 1, limit).astype(int))
    )
    return [{"x": round(float(x[i]), 4), "y": round(float(y[i]), 4)} for i in idx]


def _feature_importance(pipeline, X: pd.DataFrame, y: pd.Series) -> list[dict]:
    """Rank the original columns by permutation importance.

    Shuffle one column, measure how far ROC-AUC falls. A big fall means the model
    leaned on that column. It works for any model, linear or tree-based.
    """
    fitted = build_pipeline(pipeline.named_steps["model"]).fit(X, y)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        result = permutation_importance(
            fitted, X, y, n_repeats=30, random_state=RANDOM_STATE, scoring="roc_auc", n_jobs=-1
        )
    ranked = sorted(
        (
            {"feature": column, "importance": round(float(mean), 5), "std": round(float(std), 5)}
            for column, mean, std in zip(X.columns, result.importances_mean, result.importances_std)
        ),
        key=lambda row: row["importance"],
        reverse=True,
    )
    return [row for row in ranked if row["importance"] > 0][:12]


def _score_block(y_true, y_pred, probabilities) -> dict[str, float]:
    return {
        "accuracy": round(float(accuracy_score(y_true, y_pred)), 4),
        "precision": round(float(precision_score(y_true, y_pred, zero_division=0)), 4),
        "recall": round(float(recall_score(y_true, y_pred, zero_division=0)), 4),
        "f1": round(float(f1_score(y_true, y_pred, zero_division=0)), 4),
        "roc_auc": round(float(roc_auc_score(y_true, probabilities)), 4),
        "pr_auc": round(float(average_precision_score(y_true, probabilities)), 4),
        "brier": round(float(brier_score_loss(y_true, probabilities)), 4),
    }


def train(verbose: bool = True) -> dict:
    """Train every candidate, keep the best, and persist model + metrics."""
    started = time.perf_counter()

    df = load_clean()
    features, target = split_features_target(df)
    X = model_frame(features)
    y = target

    leaderboard: list[dict] = []
    best: tuple[float, Candidate, np.ndarray, dict] | None = None

    for candidate in candidates():
        pipeline = build_pipeline(candidate.estimator)
        oof = _out_of_fold(pipeline, X, y)
        threshold = _tune_threshold(y.to_numpy(), oof)
        predictions = (oof >= threshold).astype(int)

        row = {
            "key": candidate.key,
            "label": candidate.label,
            "rationale": candidate.rationale,
            "threshold": threshold,
            **_score_block(y, predictions, oof),
        }
        leaderboard.append(row)

        if verbose:
            print(
                f"  {candidate.label:<22} ROC-AUC {row['roc_auc']:.4f} "
                f"| F1 {row['f1']:.4f} | recall {row['recall']:.4f}"
            )

        if best is None or row["roc_auc"] > best[0]:
            best = (row["roc_auc"], candidate, oof, row)

    assert best is not None
    _, winner, oof, best_row = best
    threshold = best_row["threshold"]
    predictions = (oof >= threshold).astype(int)

    fpr, tpr, _ = roc_curve(y, oof)
    precision, recall, _ = precision_recall_curve(y, oof)
    matrix = confusion_matrix(y, predictions)

    # Final model: refit the winner on every available customer.
    final_pipeline = build_pipeline(winner.estimator).fit(X, y)

    metrics = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "training_seconds": round(time.perf_counter() - started, 1),
        "rows_total": int(len(df)),
        "churn_rate": round(float(y.mean()), 4),
        "evaluation": {
            "strategy": f"{CV_REPEATS}x repeated {CV_FOLDS}-fold stratified cross-validation",
            "explanation": (
                "With only 50 customers a hold-out test set would contain about ten "
                "rows, so every customer is instead predicted by models trained "
                f"without them, repeated {CV_REPEATS} times and averaged."
            ),
            "models_fitted": CV_FOLDS * CV_REPEATS,
            "customers_scored": int(len(X)),
            "caveat": (
                "These scores come from a 50-row teaching sample. They show the "
                "method working end to end; they are not production benchmarks."
            ),
        },
        "selected_model": best_row["label"],
        "selected_key": best_row["key"],
        "selection_reason": (
            f"Best cross-validated ROC-AUC ({best_row['roc_auc']:.4f}) of "
            f"{len(leaderboard)} candidates."
        ),
        "decision_threshold": threshold,
        "threshold_reason": (
            "Tuned on out-of-fold predictions to maximise F1 instead of being left "
            "at 0.50, because churners are the minority and a missed leaver costs "
            "more than a needless retention call."
        ),
        "scores": _score_block(y, predictions, oof),
        "confusion_matrix": {
            "true_negative": int(matrix[0][0]),
            "false_positive": int(matrix[0][1]),
            "false_negative": int(matrix[1][0]),
            "true_positive": int(matrix[1][1]),
        },
        "roc_curve": _curve_points(fpr, tpr),
        "pr_curve": _curve_points(recall, precision),
        "leaderboard": leaderboard,
        "feature_importance": _feature_importance(final_pipeline, X, y),
    }

    # The "typical customer" used as the reference point when explaining a single
    # prediction: the most common value for text columns, the median for numbers.
    baseline = {
        column: (
            float(X[column].median())
            if pd.api.types.is_numeric_dtype(X[column])
            else str(X[column].mode().iloc[0])
        )
        for column in X.columns
    }

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {
            "pipeline": final_pipeline,
            "threshold": threshold,
            "columns": list(X.columns),
            "baseline": baseline,
            "model_label": best_row["label"],
            "trained_at": metrics["generated_at"],
        },
        MODEL_FILE,
        compress=3,
    )
    METRICS_FILE.write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    if verbose:
        scores = metrics["scores"]
        print(f"\n  Winner: {metrics['selected_model']} (threshold {threshold:.2f})")
        print(
            f"  ROC-AUC {scores['roc_auc']:.4f} | F1 {scores['f1']:.4f} | "
            f"recall {scores['recall']:.4f} | accuracy {scores['accuracy']:.4f}"
        )
        print(f"  Saved model   -> models/{MODEL_FILE.name}")
        print(f"  Saved metrics -> models/{METRICS_FILE.name}")

    return metrics


if __name__ == "__main__":  # pragma: no cover
    train()
