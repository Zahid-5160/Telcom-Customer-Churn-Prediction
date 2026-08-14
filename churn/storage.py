"""Prediction history, stored in SQLite.

SQLite ships with Python, needs no server and keeps the whole history in one
file under ``reports/``. For a single-node dashboard that is genuinely the right
tool - MongoDB or Postgres would add an install step and a running service
without changing what the app can do.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from churn.config import HISTORY_DB, REPORTS_DIR

_SCHEMA = """
CREATE TABLE IF NOT EXISTS predictions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at   TEXT    NOT NULL,
    source       TEXT    NOT NULL,
    customer_ref TEXT,
    probability  REAL    NOT NULL,
    risk_band    TEXT    NOT NULL,
    will_churn   INTEGER NOT NULL,
    monthly      REAL,
    tenure       INTEGER,
    contract     TEXT,
    payload      TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_predictions_created ON predictions(created_at DESC);
"""


@contextmanager
def _connect():
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(HISTORY_DB, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def init() -> None:
    """Create the table and index if this is the first run."""
    with _connect() as connection:
        # Write-ahead logging lets reads and writes overlap, and NORMAL sync is
        # the right trade for a local prediction log: much faster commits, with
        # durability that still survives an application crash.
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.executescript(_SCHEMA)


_INSERT = """INSERT INTO predictions
    (created_at, source, customer_ref, probability, risk_band,
     will_churn, monthly, tenure, contract, payload)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""


def _row(customer: dict, result: dict, source: str, now: str) -> tuple:
    return (
        now,
        source,
        str(customer.get("customerID") or "")[:64] or None,
        float(result["probability"]),
        result["risk_band"],
        int(result["will_churn"]),
        float(customer.get("MonthlyCharges") or 0),
        int(float(customer.get("tenure") or 0)),
        customer.get("Contract"),
        json.dumps(customer, default=str),
    )


def record(customer: dict, result: dict, source: str = "single") -> None:
    """Append one scored customer to the log."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _connect() as connection:
        connection.execute(_INSERT, _row(customer, result, source, now))


def record_many(pairs, source: str = "batch") -> int:
    """Append many scored customers in a single transaction.

    Scoring a 500-row CSV one INSERT at a time would open 500 connections and
    commit 500 times; this opens one and commits once.
    """
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows = [_row(customer, result, source, now) for customer, result in pairs]
    if not rows:
        return 0
    with _connect() as connection:
        connection.executemany(_INSERT, rows)
    return len(rows)


def recent(limit: int = 25) -> list[dict]:
    """The most recent predictions, newest first."""
    with _connect() as connection:
        rows = connection.execute(
            """SELECT id, created_at, source, customer_ref, probability, risk_band,
                      will_churn, monthly, tenure, contract
               FROM predictions ORDER BY id DESC LIMIT ?""",
            (max(1, min(limit, 200)),),
        ).fetchall()
    return [dict(row) for row in rows]


def summary() -> dict:
    """Headline counts for the history panel."""
    with _connect() as connection:
        row = connection.execute(
            """SELECT COUNT(*)                              AS total,
                      COALESCE(SUM(will_churn), 0)          AS flagged,
                      COALESCE(AVG(probability), 0)         AS avg_probability,
                      COALESCE(SUM(monthly * probability), 0) AS monthly_at_risk
               FROM predictions"""
        ).fetchone()
    return {
        "total": int(row["total"]),
        "flagged": int(row["flagged"]),
        "avg_probability": round(float(row["avg_probability"]), 4),
        "monthly_at_risk": round(float(row["monthly_at_risk"]), 2),
    }


def clear() -> int:
    """Delete every stored prediction; returns how many were removed."""
    with _connect() as connection:
        removed = connection.execute("SELECT COUNT(*) FROM predictions").fetchone()[0]
        connection.execute("DELETE FROM predictions")
    return int(removed)
