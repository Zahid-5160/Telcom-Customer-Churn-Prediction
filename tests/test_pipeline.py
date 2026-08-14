"""Tests for the data, feature and analysis layers."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from retain.config import (
    CATEGORICAL_FEATURES,
    EXCLUDED_FROM_MODEL,
    NUMERIC_FEATURES,
    risk_band,
)
from retain.data import clean, load_clean, load_raw, split_features_target
from retain.features import engineer, model_frame


@pytest.fixture(scope="module")
def raw() -> pd.DataFrame:
    return load_raw()


@pytest.fixture(scope="module")
def tidy() -> pd.DataFrame:
    return load_clean()


@pytest.fixture(scope="module")
def payload() -> dict:
    from retain.insights import compute

    return compute()


def _employee(**overrides) -> pd.DataFrame:
    """A single valid employee row, with any field overridden."""
    base = {
        "Department": "Sales", "JobRole": "Sales Executive", "JobLevel": "Entry",
        "BusinessTravel": "Rare", "OverTime": "No", "MaritalStatus": "Single",
        "StockOptionLevel": "None", "JobSatisfaction": "High",
        "EnvironmentSatisfaction": "High", "WorkLifeBalance": "High",
        "JobInvolvement": "High", "PerformanceRating": "Meets expectations",
        "Age": 30, "MonthlyIncome": 60000, "DistanceFromHome": 5,
        "PercentSalaryHike": 12, "TrainingTimesLastYear": 2, "NumCompaniesWorked": 1,
        "TotalWorkingYears": 8, "YearsAtCompany": 4, "YearsInCurrentRole": 3,
        "YearsSinceLastPromotion": 1,
    }
    base.update(overrides)
    return pd.DataFrame([base])


class TestData:
    def test_dataset_loads(self, raw):
        assert len(raw) == 50, "the bundled sample is 50 employees"
        assert "Attrition" in raw.columns

    def test_no_missing_values(self, tidy):
        assert tidy.isnull().sum().sum() == 0

    def test_none_survives_as_a_real_category(self, tidy):
        """Pandas reads bare "None" as missing; these columns mean it literally."""
        assert (tidy["StockOptionLevel"] == "None").any(), "no-equity employees were lost"
        assert (tidy["BusinessTravel"] == "None").any(), "non-travelling employees were lost"
        assert tidy["StockOptionLevel"].isnull().sum() == 0

    def test_no_duplicate_employees(self, tidy):
        assert tidy["EmployeeID"].duplicated().sum() == 0

    def test_whitespace_is_trimmed(self):
        messy = pd.DataFrame(
            {"EmployeeID": [" EMP-1 "], "Department": ["  Sales  "],
             "Attrition": ["Yes"], "MonthlyIncome": ["  50000 "]}
        )
        out = clean(messy)
        assert out["Department"].iloc[0] == "Sales"
        assert out["EmployeeID"].iloc[0] == "EMP-1"
        assert out["MonthlyIncome"].iloc[0] == 50000

    def test_target_is_binary(self, tidy):
        _, target = split_features_target(tidy)
        assert set(target.unique()) <= {0, 1}
        assert 0.0 < target.mean() < 1.0

    def test_identifier_never_reaches_the_model(self, tidy):
        features, _ = split_features_target(tidy)
        assert "EmployeeID" not in features.columns
        assert "Attrition" not in features.columns

    def test_protected_characteristics_never_reach_the_model(self, tidy):
        """Gender must be physically absent from the training frame."""
        features, _ = split_features_target(tidy)
        for column in EXCLUDED_FROM_MODEL:
            assert column not in features.columns, f"{column} must never be a feature"
        assert "Gender" not in model_frame(features).columns

    def test_gender_is_still_available_for_fairness_reporting(self, tidy):
        assert "Gender" in tidy.columns

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            load_raw("data/raw/does-not-exist.csv")


class TestFeatures:
    def test_engineered_columns_exist(self, tidy):
        out = engineer(tidy)
        for column in ("CareerShare", "PromotionGap", "PayPerLevel", "TenureBand"):
            assert column in out.columns

    def test_career_share_is_a_proportion(self, tidy):
        out = engineer(tidy)
        assert out["CareerShare"].between(0, 1).all()

    def test_career_share_reflects_a_lifer(self):
        out = engineer(_employee(TotalWorkingYears=10, YearsAtCompany=10))
        assert out["CareerShare"].iloc[0] == 1.0

    def test_brand_new_employee_avoids_divide_by_zero(self):
        out = engineer(_employee(TotalWorkingYears=0, YearsAtCompany=0,
                                 YearsSinceLastPromotion=0))
        assert np.isfinite(out["CareerShare"].iloc[0])
        assert np.isfinite(out["PromotionGap"].iloc[0])
        assert np.isfinite(out["PayPerLevel"].iloc[0])

    def test_pay_per_level_falls_as_grade_rises(self):
        entry = engineer(_employee(JobLevel="Entry", MonthlyIncome=100000))
        exec_ = engineer(_employee(JobLevel="Executive", MonthlyIncome=100000))
        assert entry["PayPerLevel"].iloc[0] > exec_["PayPerLevel"].iloc[0]

    def test_promotion_gap_grows_when_overlooked(self):
        recent = engineer(_employee(YearsAtCompany=10, YearsSinceLastPromotion=1))
        stalled = engineer(_employee(YearsAtCompany=10, YearsSinceLastPromotion=8))
        assert stalled["PromotionGap"].iloc[0] > recent["PromotionGap"].iloc[0]

    def test_tenure_bands_are_ordered_correctly(self):
        rows = pd.concat([_employee(YearsAtCompany=y) for y in (1, 3, 7, 15)])
        assert engineer(rows)["TenureBand"].tolist() == [
            "Under 2 years", "2-5 years", "5-10 years", "10+ years",
        ]

    def test_model_frame_has_exactly_the_expected_columns(self, tidy):
        features, _ = split_features_target(tidy)
        frame = model_frame(features)
        assert list(frame.columns) == list(CATEGORICAL_FEATURES) + NUMERIC_FEATURES

    def test_engineering_does_not_mutate_the_input(self, tidy):
        before = tidy.copy()
        engineer(tidy)
        pd.testing.assert_frame_equal(tidy, before)


class TestRiskBands:
    @pytest.mark.parametrize(
        "probability,expected",
        [(0.0, "Low"), (0.24, "Low"), (0.25, "Moderate"), (0.49, "Moderate"),
         (0.5, "High"), (0.74, "High"), (0.75, "Critical"), (1.0, "Critical")],
    )
    def test_bands_cover_the_whole_range(self, probability, expected):
        assert risk_band(probability)[0] == expected

    def test_every_band_carries_advice(self):
        for probability in (0.1, 0.3, 0.6, 0.9):
            _, advice = risk_band(probability)
            assert advice and advice[0].isupper()


class TestInsights:
    def test_kpis_are_self_consistent(self, payload):
        kpis = payload["kpis"]
        assert kpis["left"] + kpis["stayed"] == kpis["employees"]
        assert kpis["attrition_rate"] == pytest.approx(
            kpis["left"] / kpis["employees"], abs=1e-4
        )
        assert kpis["replacement_cost"] == pytest.approx(
            kpis["monthly_salary_lost"] * kpis["replacement_cost_months"], rel=1e-3
        )

    def test_every_breakdown_covers_the_whole_workforce(self, payload):
        for name, block in payload["breakdowns"].items():
            total = sum(row["total"] for row in block["data"])
            assert total == payload["kpis"]["employees"], f"{name} does not cover everyone"

    def test_breakdown_rates_are_proportions(self, payload):
        for block in payload["breakdowns"].values():
            for row in block["data"]:
                assert 0.0 <= row["attrition_rate"] <= 1.0
                assert row["left"] + row["stayed"] == row["total"]

    def test_tenure_histogram_covers_everyone(self, payload):
        assert sum(b["total"] for b in payload["tenure_histogram"]) == payload["kpis"]["employees"]

    def test_age_histogram_covers_everyone(self, payload):
        assert sum(b["total"] for b in payload["age_histogram"]) == payload["kpis"]["employees"]

    def test_gender_is_flagged_monitor_only(self, payload):
        assert payload["breakdowns"]["Gender"]["monitor_only"] is True

    def test_gender_is_never_offered_as_a_risk_segment(self, payload):
        """Risk groups drive retention spend, so a protected trait must not appear."""
        segments = " ".join(s["segment"] for s in payload["risk_segments"])
        assert "Gender" not in segments

    def test_headline_patterns_hold_in_the_sample(self, payload):
        """The story the dashboard tells must be true of the data it ships with."""
        overtime = {r["category"]: r["attrition_rate"]
                    for r in payload["breakdowns"]["OverTime"]["data"]}
        assert overtime["Yes"] > overtime["No"]

        tenure = {r["category"]: r["attrition_rate"]
                  for r in payload["breakdowns"]["TenureBand"]["data"]}
        assert tenure["Under 2 years"] > tenure["10+ years"]

        assert payload["kpis"]["avg_salary_left"] < payload["kpis"]["avg_salary_stayed"]

    def test_headlines_are_readable_sentences(self, payload):
        assert len(payload["headlines"]) >= 4
        for headline in payload["headlines"]:
            assert headline["title"] and headline["detail"]
            assert headline["detail"].endswith(".")

    def test_headlines_quote_rupees_not_dollars(self, payload):
        text = " ".join(h["detail"] for h in payload["headlines"])
        assert "₹" in text
        assert "$" not in text

    def test_roster_holds_every_employee(self, payload):
        assert len(payload["employees"]) == payload["kpis"]["employees"]
        assert all("EmployeeID" in e for e in payload["employees"])

    def test_roster_is_json_safe(self, payload):
        import json

        json.dumps(payload)  # raises TypeError on stray numpy scalars


class TestCurrency:
    @pytest.mark.parametrize(
        "amount,expected",
        [(500, "₹500"), (50000, "₹50,000"), (125000, "₹1,25,000"),
         (8238000, "₹82,38,000"), (12500000, "₹1,25,00,000")],
    )
    def test_indian_digit_grouping(self, amount, expected):
        """Salaries must group as lakh and crore, not in thousands."""
        from retain.insights import _rupees

        assert _rupees(amount) == expected
