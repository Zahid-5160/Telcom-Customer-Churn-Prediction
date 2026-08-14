"""FastAPI service: JSON endpoints plus the dashboard itself.

Start it with ``python main.py serve``. Interactive API docs are generated
automatically at ``/docs``.
"""

from __future__ import annotations

import io
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

import pandas as pd
from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from retain import __version__, storage
from retain.config import (
    CATEGORICAL_FEATURES,
    FORM_FIELDS,
    INSIGHTS_FILE,
    METRICS_FILE,
    MODEL_FILE,
    RAW_NUMERIC,
    REPLACEMENT_COST_MONTHS,
    WEB_DIR,
    risk_band,
)
from retain.predictor import ModelNotTrained, load_artifact, predict, predict_many

MAX_BATCH_ROWS = 500


# --------------------------------------------------------------------------- #
# Request models
# --------------------------------------------------------------------------- #
class Employee(BaseModel):
    """One employee as the form submits them.

    Allowed values for every text field come straight from ``retain.config``, so
    the form, the validator and the model can never disagree about the schema.

    Note what is *absent*: gender is never accepted here, because it is never
    used to predict. See ``EXCLUDED_FROM_MODEL`` in the config for why.
    """

    Department: str = "Research and Development"
    JobRole: str = "Research Scientist"
    JobLevel: str = "Entry"
    BusinessTravel: str = "Rare"
    OverTime: str = "Yes"
    MaritalStatus: str = "Single"
    StockOptionLevel: str = "None"
    JobSatisfaction: str = "Low"
    EnvironmentSatisfaction: str = "Medium"
    WorkLifeBalance: str = "High"
    JobInvolvement: str = "High"
    PerformanceRating: str = "Meets expectations"

    Age: int = Field(default=30, ge=18, le=75)
    MonthlyIncome: float = Field(default=60000, ge=0, le=10_000_000)
    DistanceFromHome: int = Field(default=8, ge=0, le=200)
    PercentSalaryHike: int = Field(default=13, ge=0, le=100)
    TrainingTimesLastYear: int = Field(default=2, ge=0, le=20)
    NumCompaniesWorked: int = Field(default=1, ge=0, le=20)
    TotalWorkingYears: int = Field(default=6, ge=0, le=60)
    YearsAtCompany: int = Field(default=3, ge=0, le=60)
    YearsInCurrentRole: int = Field(default=2, ge=0, le=60)
    YearsSinceLastPromotion: int = Field(default=1, ge=0, le=60)

    EmployeeID: str | None = None

    @field_validator(*FORM_FIELDS)
    @classmethod
    def _known_category(cls, value: str, info) -> str:
        allowed = CATEGORICAL_FEATURES[info.field_name]
        if value not in allowed:
            raise ValueError(f"must be one of {allowed}")
        return value


class BatchRequest(BaseModel):
    employees: list[Employee] = Field(min_length=1, max_length=MAX_BATCH_ROWS)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
#: Parsed report files, keyed by path. Re-read only when the file changes on
#: disk, so repeat dashboard loads never pay to parse the same JSON again.
_JSON_CACHE: dict[Path, tuple[float, dict]] = {}


def _read_json(path: Path, what: str) -> dict:
    if not path.exists():
        raise HTTPException(
            status_code=503,
            detail=f"{what} has not been generated yet. Run `python main.py build` first.",
        )
    stamp = path.stat().st_mtime
    cached = _JSON_CACHE.get(path)
    if cached is None or cached[0] != stamp:
        _JSON_CACHE[path] = (stamp, json.loads(path.read_text(encoding="utf-8")))
    return _JSON_CACHE[path][1]


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
    # Warm the caches at boot rather than making the first visitor wait: loading
    # the model off disk is the slowest part of a cold first prediction.
    try:
        load_artifact()
    except ModelNotTrained:
        pass
    for path, label in ((INSIGHTS_FILE, "Insights"), (METRICS_FILE, "Metrics")):
        if path.exists():
            _read_json(path, label)
    yield


app = FastAPI(
    title="Retain - Employee Retention Intelligence API",
    version=__version__,
    description=(
        "Predicts which employees are at risk of leaving, explains why, and "
        "suggests what would keep them."
    ),
    lifespan=lifespan,
)

# The insights payload is tens of kilobytes of JSON; compressing it cuts the
# dashboard's first load to a fraction of that over the wire.
app.add_middleware(GZipMiddleware, minimum_size=1024)


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
def predict_one(employee: Employee, artifact: ModelReady) -> dict:
    """Score a single employee and explain the score."""
    record = employee.model_dump(exclude_none=True)
    result = predict(record)
    storage.record(record, result, source="single")
    return result


@app.post("/api/predict/batch", tags=["prediction"])
def predict_batch(payload: BatchRequest, artifact: ModelReady) -> dict:
    """Score many employees at once from JSON."""
    records = [e.model_dump(exclude_none=True) for e in payload.employees]
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

    keep = [c for c in FORM_FIELDS + RAW_NUMERIC + ["EmployeeID"] if c in frame.columns]
    return _batch_response(frame[keep].to_dict(orient="records"), source="csv")


def _batch_response(records: list[dict], source: str) -> dict:
    """Score a list of employees and summarise the outcome."""
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
                "EmployeeID": record.get("EmployeeID") or f"row-{index + 1}",
                "JobRole": record.get("JobRole"),
                "Department": record.get("Department"),
                "YearsAtCompany": record.get("YearsAtCompany"),
                "MonthlyIncome": record.get("MonthlyIncome"),
                "probability": round(probability, 4),
                "percent": round(probability * 100, 1),
                "risk_band": band,
                "will_leave": bool(probability >= threshold),
            }
        )

    flagged = [r for r in rows if r["will_leave"]]
    # Expected replacement bill: what each person would cost to replace,
    # weighted by how likely they are to go.
    cost_at_risk = sum(
        float(r["MonthlyIncome"] or 0) * REPLACEMENT_COST_MONTHS * r["probability"] for r in rows
    )

    storage.record_many(zip(records, rows), source=source)

    rows.sort(key=lambda r: r["probability"], reverse=True)
    return {
        "count": len(rows),
        "flagged": len(flagged),
        "flagged_share": round(len(flagged) / len(rows), 4) if rows else 0.0,
        "cost_at_risk": int(round(cost_at_risk)),
        "threshold": threshold,
        "results": rows,
    }


@app.get("/api/history", tags=["history"])
def history(limit: int = Query(default=25, ge=1, le=200)) -> dict:
    """Recently scored employees and a running summary."""
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
