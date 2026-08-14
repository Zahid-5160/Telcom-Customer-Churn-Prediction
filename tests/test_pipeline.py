"""Tests for the data, feature and insight layers."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from churn.config import CATEGORICAL_FEATURES, NUMERIC_FEATURES, risk_band
from churn.data import clean, load_clean, load_raw, split_features_target
from churn.features import engineer, model_frame


@pytest.fixture(scope="module")
def raw() -> pd.DataFrame:
    return load_raw()


@pytest.fixture(scope="module")
def tidy() -> pd.DataFrame:
    return load_clean()


class TestData:
    def test_dataset_loads(self, raw):
        assert len(raw) == 50, "the bundled sample is 50 customers"
        assert "Churn" in raw.columns

    def test_total_charges_becomes_numeric(self):
        messy = pd.DataFrame(
            {
                "TotalCharges": [" ", "100.5", "", "20"],
                "SeniorCitizen": [0, 1, 0, 1],
                "customerID": list("abcd"),
                "tenure": [0, 2, 0, 1],
            }
        )
        out = clean(messy)
        assert out["TotalCharges"].dtype.kind == "f"
        assert out["TotalCharges"].tolist() == [0.0, 100.5, 0.0, 20.0]

    def test_senior_citizen_becomes_yes_no(self, tidy):
        assert set(tidy["SeniorCitizen"].unique()) <= {"No", "Yes"}

    def test_no_missing_values(self, tidy):
        assert tidy.isnull().sum().sum() == 0

    def test_no_duplicate_customers(self, tidy):
        assert tidy["customerID"].duplicated().sum() == 0

    def test_target_is_binary(self, tidy):
        _, target = split_features_target(tidy)
        assert set(target.unique()) <= {0, 1}
        assert 0.0 < target.mean() < 1.0

    def test_identifier_never_reaches_the_model(self, tidy):
        features, _ = split_features_target(tidy)
        assert "customerID" not in features.columns
        assert "Churn" not in features.columns

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            load_raw("data/raw/does-not-exist.csv")


class TestFeatures:
    def test_engineered_columns_exist(self, tidy):
        out = engineer(tidy)
        for column in ("NumServices", "AvgMonthlySpend", "ChargeRatio", "TenureBand"):
            assert column in out.columns

    def test_service_count_is_in_range(self, tidy):
        out = engineer(tidy)
        assert out["NumServices"].between(0, 9).all()

    def test_service_count_ignores_no_service_wording(self):
        row = pd.DataFrame(
            [
                {
                    "PhoneService": "Yes", "MultipleLines": "No phone service",
                    "InternetService": "No", "OnlineSecurity": "No internet service",
                    "OnlineBackup": "No internet service", "DeviceProtection": "No internet service",
                    "TechSupport": "No internet service", "StreamingTV": "No internet service",
                    "StreamingMovies": "No internet service",
                    "tenure": 5, "MonthlyCharges": 20.0, "TotalCharges": 100.0,
                }
            ]
        )
        # Only the phone line counts; "No internet service" is not a service.
        assert engineer(row)["NumServices"].iloc[0] == 1

    def test_new_customer_avoids_divide_by_zero(self):
        row = pd.DataFrame(
            [{
                "PhoneService": "Yes", "MultipleLines": "No", "InternetService": "DSL",
                "OnlineSecurity": "No", "OnlineBackup": "No", "DeviceProtection": "No",
                "TechSupport": "No", "StreamingTV": "No", "StreamingMovies": "No",
                "tenure": 0, "MonthlyCharges": 45.0, "TotalCharges": 0.0,
            }]
        )
        out = engineer(row)
        assert np.isfinite(out["AvgMonthlySpend"].iloc[0])
        assert out["AvgMonthlySpend"].iloc[0] == 45.0
        assert np.isfinite(out["ChargeRatio"].iloc[0])

    def test_tenure_bands_are_ordered_correctly(self):
        rows = pd.DataFrame(
            [
                {
                    "PhoneService": "Yes", "MultipleLines": "No", "InternetService": "DSL",
                    "OnlineSecurity": "No", "OnlineBackup": "No", "DeviceProtection": "No",
                    "TechSupport": "No", "StreamingTV": "No", "StreamingMovies": "No",
                    "tenure": months, "MonthlyCharges": 45.0, "TotalCharges": 45.0 * months,
                }
                for months in (1, 8, 18, 30, 60)
            ]
        )
        assert engineer(rows)["TenureBand"].tolist() == [
            "0-6 months", "6-12 months", "1-2 years", "2-4 years", "4+ years",
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


@pytest.fixture(scope="module")
def payload() -> dict:
    from churn.insights import compute

    return compute()


class TestInsights:
    def test_kpis_are_self_consistent(self, payload):
        kpis = payload["kpis"]
        assert kpis["churned"] + kpis["retained"] == kpis["customers"]
        assert kpis["churn_rate"] == pytest.approx(kpis["churned"] / kpis["customers"], abs=1e-4)
        assert kpis["annual_revenue_at_risk"] == pytest.approx(
            kpis["monthly_revenue_at_risk"] * 12, abs=0.01
        )

    def test_every_breakdown_sums_to_the_population(self, payload):
        for name, block in payload["breakdowns"].items():
            total = sum(row["total"] for row in block["data"])
            assert total == payload["kpis"]["customers"], f"{name} does not cover everyone"

    def test_breakdown_rates_are_proportions(self, payload):
        for block in payload["breakdowns"].values():
            for row in block["data"]:
                assert 0.0 <= row["churn_rate"] <= 1.0
                assert row["churned"] + row["retained"] == row["total"]

    def test_tenure_histogram_covers_everyone(self, payload):
        assert sum(b["total"] for b in payload["tenure_histogram"]) == payload["kpis"]["customers"]

    def test_headline_patterns_hold_in_the_sample(self, payload):
        """The story the dashboard tells must be true of the data it ships with."""
        contract = {r["category"]: r["churn_rate"] for r in payload["breakdowns"]["Contract"]["data"]}
        assert contract["Month-to-month"] > contract["Two year"]

        tenure = {r["category"]: r["churn_rate"] for r in payload["breakdowns"]["TenureBand"]["data"]}
        assert tenure["0-6 months"] > tenure["4+ years"]

        net = {r["category"]: r["churn_rate"] for r in payload["breakdowns"]["InternetService"]["data"]}
        assert net["Fiber optic"] > net["DSL"]

    def test_headlines_are_readable_sentences(self, payload):
        assert len(payload["headlines"]) >= 4
        for headline in payload["headlines"]:
            assert headline["title"] and headline["detail"]
            assert headline["detail"].endswith(".")

    def test_roster_holds_every_customer(self, payload):
        assert len(payload["customers"]) == payload["kpis"]["customers"]
        assert all("customerID" in c for c in payload["customers"])

    def test_roster_is_json_safe(self, payload):
        import json

        json.dumps(payload)  # raises TypeError on stray numpy scalars
