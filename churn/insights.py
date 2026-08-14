"""Exploratory analysis, pre-computed once and served as JSON.

The old notebook redrew these charts every time somebody opened it. Here the
numbers are calculated once by ``python main.py analyse`` and the dashboard just
renders whatever the API hands it.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from churn.config import INSIGHTS_FILE, REPORTS_DIR, TARGET
from churn.data import load_clean
from churn.features import engineer

#: Columns broken down on the dashboard, with a plain-English caption.
#: Kept short: these captions are also the labels on the risk-segment chart.
BREAKDOWNS: dict[str, str] = {
    "Contract": "Contract",
    "InternetService": "Internet",
    "PaymentMethod": "Payment",
    "TenureBand": "With us",
    "TechSupport": "Tech support",
    "OnlineSecurity": "Online security",
    "SeniorCitizen": "Senior citizen",
    "PaperlessBilling": "Paperless bill",
    "Dependents": "Dependents",
    "Partner": "Partner",
    "gender": "Gender",
    "MultipleLines": "Multiple lines",
}

#: Order categories sensibly instead of alphabetically where it matters.
ORDERINGS: dict[str, list[str]] = {
    "TenureBand": ["0-6 months", "6-12 months", "1-2 years", "2-4 years", "4+ years"],
    "Contract": ["Month-to-month", "One year", "Two year"],
}


def _churned(df: pd.DataFrame) -> pd.Series:
    return df[TARGET].str.lower() == "yes"


def _breakdown(df: pd.DataFrame, column: str) -> list[dict]:
    """Churn rate per category of a column, sorted worst-first."""
    grouped = df.groupby(column, observed=True).agg(
        total=(TARGET, "size"),
        churned=(TARGET, lambda s: int((s.str.lower() == "yes").sum())),
        avg_monthly=("MonthlyCharges", "mean"),
    )
    grouped["churn_rate"] = grouped["churned"] / grouped["total"]

    if column in ORDERINGS:
        grouped = grouped.reindex([c for c in ORDERINGS[column] if c in grouped.index])
    else:
        grouped = grouped.sort_values("churn_rate", ascending=False)

    return [
        {
            "category": str(index),
            "total": int(row.total),
            "churned": int(row.churned),
            "retained": int(row.total - row.churned),
            "churn_rate": round(float(row.churn_rate), 4),
            "avg_monthly": round(float(row.avg_monthly), 2),
        }
        for index, row in grouped.iterrows()
    ]


def _histogram(df: pd.DataFrame, column: str, bins: np.ndarray, label_fmt: str) -> list[dict]:
    """Churned vs retained counts per bin of a numeric column.

    The top bin is extended if the data runs past it, because a bin edge that
    stops short would silently drop customers from the chart.
    """
    bins = np.asarray(bins, dtype=float)
    highest = float(df[column].max())
    if highest >= bins[-1]:
        step = bins[-1] - bins[-2]
        while bins[-1] <= highest:
            bins = np.append(bins, bins[-1] + step)

    churned = _churned(df)
    cut = pd.cut(df[column], bins=bins, include_lowest=True, right=False)
    frame = pd.DataFrame({"bin": cut, "churned": churned})
    grouped = frame.groupby("bin", observed=True).agg(
        total=("churned", "size"), churned=("churned", "sum")
    )
    rows = []
    for interval, row in grouped.iterrows():
        rows.append(
            {
                "label": label_fmt.format(low=int(interval.left), high=int(interval.right)),
                "total": int(row.total),
                "churned": int(row.churned),
                "retained": int(row.total - row.churned),
                "churn_rate": round(float(row.churned / row.total), 4) if row.total else 0.0,
            }
        )
    return rows


def _risk_segments(df: pd.DataFrame, baseline: float, min_size: int = 8) -> list[dict]:
    """Single-column segments whose churn rate is furthest above the average."""
    segments = []
    for column in BREAKDOWNS:
        for row in _breakdown(df, column):
            if row["total"] < min_size:
                continue
            segments.append(
                {
                    "segment": f"{BREAKDOWNS[column]}: {row['category']}",
                    "customers": row["total"],
                    "churn_rate": row["churn_rate"],
                    "lift": round(row["churn_rate"] / baseline, 2) if baseline else 0.0,
                }
            )
    return sorted(segments, key=lambda s: s["churn_rate"], reverse=True)[:8]


def compute() -> dict:
    """Build the full insights payload from the cleaned dataset."""
    df = engineer(load_clean())
    churned = _churned(df)
    total = len(df)
    churn_rate = float(churned.mean())

    monthly_at_risk = float(df.loc[churned, "MonthlyCharges"].sum())

    payload: dict = {
        "kpis": {
            "customers": total,
            "churned": int(churned.sum()),
            "retained": int((~churned).sum()),
            "churn_rate": round(churn_rate, 4),
            "monthly_revenue_at_risk": round(monthly_at_risk, 2),
            "annual_revenue_at_risk": round(monthly_at_risk * 12, 2),
            "avg_tenure_churned": round(float(df.loc[churned, "tenure"].mean()), 1),
            "avg_tenure_retained": round(float(df.loc[~churned, "tenure"].mean()), 1),
            "avg_monthly_churned": round(float(df.loc[churned, "MonthlyCharges"].mean()), 2),
            "avg_monthly_retained": round(float(df.loc[~churned, "MonthlyCharges"].mean()), 2),
            "avg_services_churned": round(float(df.loc[churned, "NumServices"].mean()), 2),
            "avg_services_retained": round(float(df.loc[~churned, "NumServices"].mean()), 2),
        },
        "breakdowns": {
            column: {"label": label, "data": _breakdown(df, column)}
            for column, label in BREAKDOWNS.items()
        },
        # Bin widths are wide on purpose: with 50 customers, narrow bins would
        # hold two or three people each and read as noise.
        "tenure_histogram": _histogram(df, "tenure", np.arange(0, 84, 12), "{low}-{high}m"),
    }

    payload["risk_segments"] = _risk_segments(df, churn_rate)
    payload["customers"] = _customer_roster(df)
    payload["headlines"] = _headlines(payload)

    return payload


def _customer_roster(df: pd.DataFrame) -> list[dict]:
    """Every customer in the sample, ready to browse and load into the form.

    Only viable because the dataset is deliberately small - all 50 people fit on
    one screen, so a user can click any real customer and re-score them.
    """
    columns = [
        "customerID", "gender", "SeniorCitizen", "Partner", "Dependents", "tenure",
        "PhoneService", "MultipleLines", "InternetService", "OnlineSecurity",
        "OnlineBackup", "DeviceProtection", "TechSupport", "StreamingTV",
        "StreamingMovies", "Contract", "PaperlessBilling", "PaymentMethod",
        "MonthlyCharges", "TotalCharges", "NumServices", "TenureBand", TARGET,
    ]
    present = [c for c in columns if c in df.columns]
    roster = df[present].sort_values("tenure").to_dict(orient="records")
    for row in roster:
        for key, value in row.items():
            if isinstance(value, (np.integer, np.floating)):
                row[key] = value.item()
    return roster


def _rate(payload: dict, column: str, category: str) -> float | None:
    """Look up one category's churn rate, or ``None`` if it is not present."""
    for row in payload["breakdowns"].get(column, {}).get("data", []):
        if row["category"] == category:
            return row["churn_rate"]
    return None


def _headlines(payload: dict) -> list[dict]:
    """Turn the aggregates into sentences a non-technical reader can act on.

    Every number is read back out of the computed data rather than hard-coded, so
    the text stays true if the dataset is ever swapped or extended.
    """
    kpis = payload["kpis"]
    headlines: list[dict] = []

    m2m = _rate(payload, "Contract", "Month-to-month")
    two_year = _rate(payload, "Contract", "Two year")
    if m2m is not None and two_year is not None:
        ratio = m2m / two_year if two_year else 0
        comparison = f"about {ratio:.0f} times higher" if ratio >= 1.5 else "noticeably higher"
        headlines.append(
            {
                "title": "Rolling monthly contracts are the biggest leak",
                "detail": (
                    f"{m2m:.0%} of month-to-month customers leave, against {two_year:.0%} of "
                    f"those on a two-year deal - {comparison}. Nothing is holding the monthly "
                    "customer in place, so every bill is a chance to reconsider."
                ),
            }
        )

    early = _rate(payload, "TenureBand", "0-6 months")
    loyal = _rate(payload, "TenureBand", "4+ years")
    if early is not None and loyal is not None:
        headlines.append(
            {
                "title": "The first six months decide everything",
                "detail": (
                    f"{early:.0%} of customers churn inside their first six months, falling to "
                    f"{loyal:.0%} once they pass four years. Attention paid early is worth far "
                    "more than a discount offered late."
                ),
            }
        )

    fibre = _rate(payload, "InternetService", "Fiber optic")
    dsl = _rate(payload, "InternetService", "DSL")
    if fibre is not None and dsl is not None and fibre > dsl:
        headlines.append(
            {
                "title": "The premium product loses the most customers",
                "detail": (
                    f"Fibre optic users leave at {fibre:.0%} versus {dsl:.0%} on slower DSL, even "
                    "though fibre costs more. People paying a premium expect a premium "
                    "experience, and judge it harshly."
                ),
            }
        )

    cheque = _rate(payload, "PaymentMethod", "Electronic check")
    autopay = [
        r for r in (
            _rate(payload, "PaymentMethod", "Bank transfer (automatic)"),
            _rate(payload, "PaymentMethod", "Credit card (automatic)"),
        ) if r is not None
    ]
    if cheque is not None and autopay:
        best_auto = min(autopay)
        headlines.append(
            {
                "title": "How they pay reveals how committed they are",
                "detail": (
                    f"Electronic-cheque payers churn at {cheque:.0%}, while the safest automatic "
                    f"payment group sits at {best_auto:.0%}. Someone who has set up autopay has "
                    "quietly decided to stay."
                ),
            }
        )

    if kpis["avg_services_retained"] > kpis["avg_services_churned"]:
        headlines.append(
            {
                "title": "Bundled customers are harder to lose",
                "detail": (
                    f"Customers who stay use {kpis['avg_services_retained']:.1f} services on "
                    f"average; those who leave use {kpis['avg_services_churned']:.1f}. Each extra "
                    "service is one more thing to unpick before switching provider."
                ),
            }
        )

    headlines.append(
        {
            "title": "What all this is worth",
            "detail": (
                f"The {kpis['churned']} customers who left were paying "
                f"${kpis['monthly_revenue_at_risk']:,.0f} a month - "
                f"${kpis['annual_revenue_at_risk']:,.0f} a year walking out of the door. "
                "Keeping even a third of them pays for the whole retention effort."
            ),
        }
    )

    return headlines


def build(verbose: bool = True) -> dict:
    """Compute the insights and write them to ``reports/insights.json``."""
    payload = compute()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    INSIGHTS_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    if verbose:
        kpis = payload["kpis"]
        print(f"  {kpis['customers']:,} customers analysed | churn rate {kpis['churn_rate']:.2%}")
        print(f"  Monthly revenue at risk: ${kpis['monthly_revenue_at_risk']:,.0f}")
        print(f"  Saved insights -> {INSIGHTS_FILE.relative_to(INSIGHTS_FILE.parents[1])}")
    return payload


if __name__ == "__main__":  # pragma: no cover
    build()
