"""Workforce analysis, pre-computed once and served as JSON.

Calculated by ``python main.py analyse``; the dashboard just renders whatever
the API hands it.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from retain.config import (
    INSIGHTS_FILE,
    REPLACEMENT_COST_MONTHS,
    REPORTS_DIR,
    TARGET,
)
from retain.data import load_clean
from retain.features import engineer

#: Columns broken down on the dashboard, with a short caption. Kept brief
#: because these captions double as labels on the risk-group chart.
BREAKDOWNS: dict[str, str] = {
    "OverTime": "Overtime",
    "JobLevel": "Job level",
    "TenureBand": "Time here",
    "StockOptionLevel": "Equity",
    "BusinessTravel": "Travel",
    "MaritalStatus": "Marital status",
    "Department": "Department",
    "JobSatisfaction": "Job satisfaction",
    "WorkLifeBalance": "Work-life balance",
    "EnvironmentSatisfaction": "Environment",
    "JobInvolvement": "Involvement",
    "JobRole": "Role",
    "Gender": "Gender",
}

#: Order categories meaningfully instead of alphabetically where it matters.
ORDERINGS: dict[str, list[str]] = {
    "TenureBand": ["Under 2 years", "2-5 years", "5-10 years", "10+ years"],
    "JobLevel": ["Entry", "Junior", "Mid", "Senior", "Executive"],
    "BusinessTravel": ["None", "Rare", "Frequent"],
    "StockOptionLevel": ["None", "Basic", "Standard", "Premium"],
    "JobSatisfaction": ["Low", "Medium", "High", "Very High"],
    "WorkLifeBalance": ["Low", "Medium", "High", "Very High"],
    "EnvironmentSatisfaction": ["Low", "Medium", "High", "Very High"],
    "JobInvolvement": ["Low", "Medium", "High", "Very High"],
    "OverTime": ["No", "Yes"],
}

#: Gender is reported for fairness monitoring only - never used as a segment to
#: target retention spending, and never fed to the model.
MONITOR_ONLY = {"Gender"}


def _left(df: pd.DataFrame) -> pd.Series:
    return df[TARGET].str.lower() == "yes"


def _breakdown(df: pd.DataFrame, column: str) -> list[dict]:
    """Attrition rate per category of a column."""
    grouped = df.groupby(column, observed=True).agg(
        total=(TARGET, "size"),
        left=(TARGET, lambda s: int((s.str.lower() == "yes").sum())),
        avg_salary=("MonthlyIncome", "mean"),
    )
    grouped["attrition_rate"] = grouped["left"] / grouped["total"]

    if column in ORDERINGS:
        grouped = grouped.reindex([c for c in ORDERINGS[column] if c in grouped.index])
    else:
        grouped = grouped.sort_values("attrition_rate", ascending=False)

    return [
        {
            "category": str(index),
            "total": int(row.total),
            "left": int(row.left),
            "stayed": int(row.total - row.left),
            "attrition_rate": round(float(row.attrition_rate), 4),
            "avg_salary": int(round(float(row.avg_salary), 0)),
        }
        for index, row in grouped.iterrows()
    ]


def _histogram(df: pd.DataFrame, column: str, bins, label_fmt: str) -> list[dict]:
    """Left vs stayed counts per bin of a numeric column.

    The top bin is extended if the data runs past it, because a bin edge that
    stops short would silently drop employees from the chart.
    """
    bins = np.asarray(bins, dtype=float)
    highest = float(df[column].max())
    if highest >= bins[-1]:
        step = bins[-1] - bins[-2]
        while bins[-1] <= highest:
            bins = np.append(bins, bins[-1] + step)

    left = _left(df)
    cut = pd.cut(df[column], bins=bins, include_lowest=True, right=False)
    frame = pd.DataFrame({"bin": cut, "left": left})
    grouped = frame.groupby("bin", observed=True).agg(total=("left", "size"), left=("left", "sum"))

    rows = []
    for interval, row in grouped.iterrows():
        rows.append(
            {
                "label": label_fmt.format(low=int(interval.left), high=int(interval.right)),
                "total": int(row.total),
                "left": int(row.left),
                "stayed": int(row.total - row.left),
                "attrition_rate": round(float(row.left / row.total), 4) if row.total else 0.0,
            }
        )
    return rows


def _risk_segments(df: pd.DataFrame, baseline: float, min_size: int = 8) -> list[dict]:
    """Single characteristics whose attrition rate is furthest above average."""
    segments = []
    for column, caption in BREAKDOWNS.items():
        if column in MONITOR_ONLY:
            continue
        for row in _breakdown(df, column):
            if row["total"] < min_size:
                continue
            segments.append(
                {
                    "segment": f"{caption}: {row['category']}",
                    "employees": row["total"],
                    "attrition_rate": row["attrition_rate"],
                    "lift": round(row["attrition_rate"] / baseline, 2) if baseline else 0.0,
                }
            )
    return sorted(segments, key=lambda s: s["attrition_rate"], reverse=True)[:8]


def _roster(df: pd.DataFrame) -> list[dict]:
    """Every employee in the sample, ready to browse and load into the form."""
    roster = df.sort_values("YearsAtCompany").to_dict(orient="records")
    for row in roster:
        for key, value in row.items():
            if isinstance(value, (np.integer, np.floating)):
                row[key] = value.item()
    return roster


def compute() -> dict:
    """Build the full insights payload from the cleaned dataset."""
    df = engineer(load_clean())
    left = _left(df)
    total = len(df)
    attrition_rate = float(left.mean())

    monthly_lost = float(df.loc[left, "MonthlyIncome"].sum())
    replacement_cost = monthly_lost * REPLACEMENT_COST_MONTHS

    payload: dict = {
        "kpis": {
            "employees": total,
            "left": int(left.sum()),
            "stayed": int((~left).sum()),
            "attrition_rate": round(attrition_rate, 4),
            "monthly_salary_lost": int(round(monthly_lost)),
            "replacement_cost": int(round(replacement_cost)),
            "replacement_cost_months": REPLACEMENT_COST_MONTHS,
            "avg_tenure_left": round(float(df.loc[left, "YearsAtCompany"].mean()), 1),
            "avg_tenure_stayed": round(float(df.loc[~left, "YearsAtCompany"].mean()), 1),
            "avg_salary_left": int(round(float(df.loc[left, "MonthlyIncome"].mean()))),
            "avg_salary_stayed": int(round(float(df.loc[~left, "MonthlyIncome"].mean()))),
            "avg_age_left": round(float(df.loc[left, "Age"].mean()), 1),
            "avg_age_stayed": round(float(df.loc[~left, "Age"].mean()), 1),
        },
        "breakdowns": {
            column: {
                "label": caption,
                "monitor_only": column in MONITOR_ONLY,
                "data": _breakdown(df, column),
            }
            for column, caption in BREAKDOWNS.items()
        },
        # Wide bins on purpose: with 50 employees, narrow bins would hold two or
        # three people each and read as noise.
        "tenure_histogram": _histogram(df, "YearsAtCompany", np.arange(0, 25, 5), "{low}-{high}y"),
        "age_histogram": _histogram(df, "Age", np.arange(18, 63, 9), "{low}-{high}"),
    }

    payload["risk_segments"] = _risk_segments(df, attrition_rate)
    payload["employees"] = _roster(df)
    payload["headlines"] = _headlines(payload)

    return payload


def _rate(payload: dict, column: str, category: str) -> float | None:
    """Look up one category's attrition rate, or ``None`` if absent."""
    for row in payload["breakdowns"].get(column, {}).get("data", []):
        if row["category"] == category:
            return row["attrition_rate"]
    return None


def _rupees(amount: float) -> str:
    """Format with Indian digit grouping - 12,50,000 rather than 1,250,000."""
    whole = f"{int(round(amount)):,}"
    digits = whole.replace(",", "")
    if len(digits) <= 3:
        return f"₹{digits}"
    head, tail = digits[:-3], digits[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return "₹" + ",".join(parts) + "," + tail


def _headlines(payload: dict) -> list[dict]:
    """Turn the aggregates into sentences a non-technical reader can act on.

    Every number is read back out of the computed data rather than hard-coded,
    and each claim is only published if the data actually supports it - so the
    text cannot end up asserting something the charts contradict.
    """
    kpis = payload["kpis"]
    headlines: list[dict] = []

    ot_yes, ot_no = _rate(payload, "OverTime", "Yes"), _rate(payload, "OverTime", "No")
    if ot_yes is not None and ot_no is not None and ot_yes > ot_no:
        headlines.append(
            {
                "title": "Overtime is the clearest warning sign there is",
                "detail": (
                    f"{ot_yes:.0%} of people regularly working overtime left, against "
                    f"{ot_no:.0%} of those who did not. Sustained extra hours are not a sign "
                    "of commitment - they are the sound of somebody burning out."
                ),
            }
        )

    entry, senior = _rate(payload, "JobLevel", "Entry"), _rate(payload, "JobLevel", "Senior")
    if entry is not None and senior is not None and entry > senior:
        headlines.append(
            {
                "title": "Junior staff walk, senior staff stay",
                "detail": (
                    f"{entry:.0%} of entry-level employees left, against {senior:.0%} at senior "
                    "level. Early-career people have the most options and the least tying them "
                    "to any one employer."
                ),
            }
        )

    if kpis["avg_salary_left"] < kpis["avg_salary_stayed"]:
        gap = kpis["avg_salary_stayed"] - kpis["avg_salary_left"]
        headlines.append(
            {
                "title": "The people leaving are the ones paid least",
                "detail": (
                    f"Leavers earned {_rupees(kpis['avg_salary_left'])} a month on average; "
                    f"those who stayed earned {_rupees(kpis['avg_salary_stayed'])} - a gap of "
                    f"{_rupees(gap)} every month. Pay is rarely the whole story, but it is "
                    "never absent from it."
                ),
            }
        )

    no_equity, some_equity = (
        _rate(payload, "StockOptionLevel", "None"),
        _rate(payload, "StockOptionLevel", "Basic"),
    )
    if no_equity is not None and some_equity is not None and no_equity > some_equity:
        headlines.append(
            {
                "title": "A stake in the company keeps people in it",
                "detail": (
                    f"{no_equity:.0%} of employees with no equity left, against {some_equity:.0%} "
                    "of those holding even a basic grant. Something that vests over time gives "
                    "an obvious reason to still be here when it does."
                ),
            }
        )

    frequent, none_travel = (
        _rate(payload, "BusinessTravel", "Frequent"),
        _rate(payload, "BusinessTravel", "None"),
    )
    if frequent is not None and none_travel is not None and frequent > none_travel:
        headlines.append(
            {
                "title": "Frequent travellers wear out",
                "detail": (
                    f"{frequent:.0%} of frequent travellers left, against {none_travel:.0%} of "
                    "those who never travel. Travel is a cost paid in evenings and weekends, "
                    "and it does not appear on any budget line."
                ),
            }
        )

    early = _rate(payload, "TenureBand", "Under 2 years")
    loyal = _rate(payload, "TenureBand", "10+ years")
    if early is not None and loyal is not None and early > loyal:
        headlines.append(
            {
                "title": "The first two years decide the next ten",
                "detail": (
                    f"{early:.0%} of employees with under two years' service left, falling to "
                    f"{loyal:.0%} past ten years. Get somebody through their second year and "
                    "they tend to stay for good."
                ),
            }
        )

    headlines.append(
        {
            "title": "What this costs",
            "detail": (
                f"The {kpis['left']} people who left were earning "
                f"{_rupees(kpis['monthly_salary_lost'])} a month between them. At the standard "
                f"estimate of {kpis['replacement_cost_months']} months' salary to replace "
                f"somebody, that is roughly {_rupees(kpis['replacement_cost'])} to rebuild the "
                "same team you already had."
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
        print(f"  {kpis['employees']} employees analysed | attrition {kpis['attrition_rate']:.1%}")
        print(f"  Cost to replace the leavers: {_rupees(kpis['replacement_cost'])}")
        print(f"  Saved insights -> reports/{INSIGHTS_FILE.name}")
    return payload


if __name__ == "__main__":  # pragma: no cover
    from retain.console import enable_unicode

    enable_unicode()
    build()
