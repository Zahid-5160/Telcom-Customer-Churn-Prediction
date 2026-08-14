"""FastAPI service: JSON endpoints plus the dashboard itself.

Start it with ``python main.py serve``. Interactive API docs are generated
automatically at ``/docs``.
"""

from __future__ import annotations

import io
import json
from contextlib import asynccontextmanager
from typing import Annotated, Any

import pandas as pd
from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from churn import __version__, storage
from churn.config import (
    CATEGORICAL_FEATURES,
    FORM_FIELDS,
    INSIGHTS_FILE,
    METRICS_FILE,
    MODEL_FILE,
    RAW_NUMERIC,
    WEB_DIR,
    risk_band,
)
from churn.predictor import ModelNotTrained, load_artifact, predict, predict_many

MAX_BATCH_ROWS = 500


# --------------------------------------------------------------------------- #
# Request models
# --------------------------------------------------------------------------- #
class Customer(BaseModel):
    """One customer as the form submits them.

    Allowed values for every text field come straight from ``churn.config``, so
    the form, the validator and the model can never disagree about the schema.
    """

    gender: str = "Female"
    SeniorCitizen: str = "No"
    Partner: str = "No"
    Dependents: str = "No"
    tenure: int = Field(default=12, ge=0, le=100)
    PhoneService: str = "Yes"
    MultipleLines: str = "No"
    InternetService: str = "Fiber optic"
    OnlineSecurity: str = "No"
    OnlineBackup: str = "No"
    DeviceProtection: str = "No"
    TechSupport: str = "No"
    StreamingTV: str = "No"
    StreamingMovies: str = "No"
    Contract: str = "Month-to-month"
    PaperlessBilling: str = "Yes"
    PaymentMethod: str = "Electronic check"
    MonthlyCharges: float = Field(default=70.0, ge=0, le=1000)
    TotalCharges: float = Field(default=840.0, ge=0, le=100000)
    customerID: str | None = None

    @field_validator(*FORM_FIELDS)
    @classmethod
    def _known_category(cls, value: str, info) -> str:
        allowed = CATEGORICAL_FEATURES[info.field_name]
        if value not in allowed:
            raise ValueError(f"must be one of {allowed}")
        return value


class BatchRequest(BaseModel):
    customers: list[Customer] = Field(min_length=1, max_length=MAX_BATCH_ROWS)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _read_json(path, what: str) -> dict:
    if not path.exists():
        raise HTTPException(
            status_code=503,
            detail=f"{what} has not been generated yet. Run `python main.py build` first.",
        )
    return json.loads(path.read_text(encoding="utf-8"))


def require_model() -> dict[str, Any]:
    """Dependency that turns a missing model file into a clean 503."""
    try:
        return load_artifact()
    except ModelNotTrained as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


ModelReady = Annotated[dict, Depends(require_model)]


# --------------------------------------------------------------------------- #
# Application
# --------------------------------------------------------------------------- #
@asynccontextmanager
async def lifespan(_app: FastAPI):
    storage.init()
    yield


app = FastAPI(
    title="Telco Customer Churn API",
    version=__version__,
    description=(
        "Predicts which telecom customers are about to leave, explains why, and "
        "suggests what to do about it."
    ),
    lifespan=lifespan,
)


@app.get("/api/health", tags=["meta"])
def health() -> dict:
    """Is the service up, and is a trained model available?"""
    return {
        "status": "ok",
        "version": __version__,
        "model_trained": MODEL_FILE.exists(),
        "insights_ready": INSIGHTS_FILE.exists(),
    }


@app.get("/api/schema", tags=["meta"])
def schema() -> dict:
    """Field definitions the front-end builds its form from."""
    return {
        "categorical": {field: CATEGORICAL_FEATURES[field] for field in FORM_FIELDS},
        "numeric": RAW_NUMERIC,
        "order": FORM_FIELDS,
    }


@app.get("/api/insights", tags=["analysis"])
def insights() -> dict:
    """Pre-computed exploratory analysis powering the dashboard charts."""
    return _read_json(INSIGHTS_FILE, "Insights report")


@app.get("/api/model", tags=["analysis"])
def model_card() -> dict:
    """Metrics, leaderboard and feature importance for the trained model."""
    return _read_json(METRICS_FILE, "Model metrics")


@app.post("/api/predict", tags=["prediction"])
def predict_one(customer: Customer, artifact: ModelReady) -> dict:
    """Score a single customer and explain the score."""
    record = customer.model_dump(exclude_none=True)
    result = predict(record)
    storage.record(record, result, source="single")
    return result


@app.post("/api/predict/batch", tags=["prediction"])
def predict_batch(payload: BatchRequest, artifact: ModelReady) -> dict:
    """Score many customers at once from JSON."""
    records = [c.model_dump(exclude_none=True) for c in payload.customers]
    return _batch_response(records, source="batch")


@app.post("/api/predict/csv", tags=["prediction"])
async def predict_csv(artifact: ModelReady, file: UploadFile = File(...)) -> dict:
    """Score a CSV upload with the same columns as the training data."""
    if not (file.filename or "").lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Please upload a .csv file.")

    raw = await file.read()
    if len(raw) > 5_000_000:
        raise HTTPException(status_code=413, detail="File too large (5 MB limit).")

    try:
        frame = pd.read_csv(io.BytesIO(raw))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not read that CSV: {exc}") from exc

    missing = [c for c in FORM_FIELDS + RAW_NUMERIC if c not in frame.columns]
    if missing:
        raise HTTPException(
            status_code=400, detail=f"CSV is missing required columns: {', '.join(missing)}"
        )
    if len(frame) > MAX_BATCH_ROWS:
        raise HTTPException(
            status_code=413, detail=f"Please upload at most {MAX_BATCH_ROWS} rows."
        )

    if "SeniorCitizen" in frame.columns and frame["SeniorCitizen"].dtype != object:
        frame["SeniorCitizen"] = frame["SeniorCitizen"].map({0: "No", 1: "Yes"})
    frame["TotalCharges"] = pd.to_numeric(
        frame["TotalCharges"].astype(str).str.strip().replace("", "0"), errors="coerce"
    ).fillna(0.0)

    keep = [c for c in FORM_FIELDS + RAW_NUMERIC + ["customerID"] if c in frame.columns]
    return _batch_response(frame[keep].to_dict(orient="records"), source="csv")


def _batch_response(records: list[dict], source: str) -> dict:
    """Score a list of customers and summarise the outcome."""
    try:
        probabilities = predict_many(records)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"Could not score those rows: {exc}") from exc

    threshold = load_artifact()["threshold"]
    rows = []
    for index, (record, probability) in enumerate(zip(records, probabilities)):
        band, _ = risk_band(probability)
        rows.append(
            {
                "row": index + 1,
                "customerID": record.get("customerID") or f"row-{index + 1}",
                "tenure": record.get("tenure"),
                "Contract": record.get("Contract"),
                "MonthlyCharges": record.get("MonthlyCharges"),
                "probability": round(probability, 4),
                "percent": round(probability * 100, 1),
                "risk_band": band,
                "will_churn": bool(probability >= threshold),
            }
        )

    flagged = [r for r in rows if r["will_churn"]]
    at_risk_value = sum(
        float(r["MonthlyCharges"] or 0) * r["probability"] * 12 for r in rows
    )

    for record, row in zip(records, rows):
        storage.record(record, row | {"probability": row["probability"]}, source=source)

    rows.sort(key=lambda r: r["probability"], reverse=True)
    return {
        "count": len(rows),
        "flagged": len(flagged),
        "flagged_share": round(len(flagged) / len(rows), 4) if rows else 0.0,
        "annual_value_at_risk": round(at_risk_value, 2),
        "threshold": threshold,
        "results": rows,
    }


@app.get("/api/history", tags=["history"])
def history(limit: int = Query(default=25, ge=1, le=200)) -> dict:
    """Recently scored customers and a running summary."""
    return {"summary": storage.summary(), "items": storage.recent(limit)}


@app.delete("/api/history", tags=["history"])
def clear_history() -> dict:
    """Wipe the stored prediction log."""
    return {"deleted": storage.clear()}


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.exception_handler(ModelNotTrained)
def _model_missing(_request, exc: ModelNotTrained) -> JSONResponse:  # pragma: no cover
    return JSONResponse(status_code=503, content={"detail": str(exc)})


app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
