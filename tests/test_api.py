"""Tests for the prediction service and the HTTP API."""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from retain.api import app
from retain.config import MODEL_FILE, RAW_DATA_FILE

pytestmark = pytest.mark.skipif(
    not MODEL_FILE.exists(), reason="run `python main.py train` first"
)

#: A young, underpaid, overworked new joiner - the classic flight risk.
AT_RISK = {
    "Department": "Sales", "JobRole": "Sales Representative", "JobLevel": "Entry",
    "BusinessTravel": "Frequent", "OverTime": "Yes", "MaritalStatus": "Single",
    "StockOptionLevel": "None", "JobSatisfaction": "Low",
    "EnvironmentSatisfaction": "Low", "WorkLifeBalance": "Low",
    "JobInvolvement": "Low", "PerformanceRating": "Meets expectations",
    "Age": 24, "MonthlyIncome": 35000, "DistanceFromHome": 22,
    "PercentSalaryHike": 11, "TrainingTimesLastYear": 0, "NumCompaniesWorked": 3,
    "TotalWorkingYears": 3, "YearsAtCompany": 1, "YearsInCurrentRole": 1,
    "YearsSinceLastPromotion": 1,
}

#: A settled senior with equity and no overtime.
SETTLED = {
    **AT_RISK,
    "JobLevel": "Senior", "OverTime": "No", "BusinessTravel": "Rare",
    "MaritalStatus": "Married", "StockOptionLevel": "Standard",
    "JobSatisfaction": "Very High", "EnvironmentSatisfaction": "Very High",
    "WorkLifeBalance": "Very High", "JobInvolvement": "Very High",
    "Age": 44, "MonthlyIncome": 280000, "DistanceFromHome": 4,
    "TotalWorkingYears": 20, "YearsAtCompany": 12, "YearsInCurrentRole": 8,
    "YearsSinceLastPromotion": 1, "TrainingTimesLastYear": 4,
}


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


class TestMeta:
    def test_health(self, client):
        body = client.get("/api/health").json()
        assert body["status"] == "ok"
        assert body["model_trained"] is True

    def test_schema_matches_the_form(self, client):
        body = client.get("/api/schema").json()
        assert body["categorical"]["OverTime"] == ["No", "Yes"]
        assert body["categorical"]["JobLevel"] == [
            "Entry", "Junior", "Mid", "Senior", "Executive"
        ]
        assert "MonthlyIncome" in body["numeric"]

    def test_schema_never_offers_a_protected_characteristic(self, client):
        body = client.get("/api/schema").json()
        assert "Gender" not in body["categorical"]

    def test_dashboard_is_served(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert "Retain" in response.text
        assert "Employee retention intelligence" in response.text

    def test_static_assets_are_served(self, client):
        for path in ("/css/styles.css", "/js/app.js", "/js/charts.js"):
            assert client.get(path).status_code == 200


class TestPredict:
    def test_returns_a_usable_result(self, client):
        body = client.post("/api/predict", json=AT_RISK).json()
        assert 0.0 <= body["probability"] <= 1.0
        assert body["percent"] == pytest.approx(body["probability"] * 100, abs=0.1)
        assert body["risk_band"] in {"Low", "Moderate", "High", "Critical"}
        assert isinstance(body["will_leave"], bool)

    def test_flag_follows_the_threshold(self, client):
        body = client.post("/api/predict", json=AT_RISK).json()
        assert body["will_leave"] == (body["probability"] >= body["threshold"])

    def test_explanations_are_present_and_ordered(self, client):
        body = client.post("/api/predict", json=AT_RISK).json()
        impacts = [abs(d["impact"]) for d in body["drivers"]]
        assert impacts == sorted(impacts, reverse=True)
        reductions = [a["reduction"] for a in body["actions"]]
        assert reductions == sorted(reductions, reverse=True)
        assert all(a["reduction"] > 0 for a in body["actions"])

    def test_recommended_actions_really_lower_the_risk(self, client):
        """An action is only worth showing if applying it actually scores lower."""
        body = client.post("/api/predict", json=AT_RISK).json()
        for action in body["actions"]:
            changed = {**AT_RISK, action["field"]: action["to"]}
            after = client.post("/api/predict", json=changed).json()
            assert after["probability"] < body["probability"] + 1e-9

    def test_actions_never_target_who_somebody_is(self, client):
        """Retention offers must never be priced off personal circumstances."""
        body = client.post("/api/predict", json=AT_RISK).json()
        off_limits = {"Gender", "Age", "MaritalStatus", "Department", "JobRole"}
        assert not off_limits & {a["field"] for a in body["actions"]}

    def test_actions_never_recommend_making_the_job_worse(self, client):
        """A recommendation must not argue for a downgrade.

        The counterfactual search can find that *lowering* somebody's involvement
        reduces their modelled risk - a small-sample quirk - which would pair the
        advice "give them ownership" with a move from High to Medium.
        """
        from retain.predictor import IMPROVEMENTS

        # Someone mid-ladder on every scale, so a downgrade is available to find.
        midway = {
            **AT_RISK, "JobSatisfaction": "High", "EnvironmentSatisfaction": "High",
            "WorkLifeBalance": "High", "JobInvolvement": "High",
            "StockOptionLevel": "Standard", "BusinessTravel": "Rare", "JobLevel": "Mid",
        }
        body = client.post("/api/predict", json=midway).json()
        for action in body["actions"]:
            ladder = IMPROVEMENTS.get(action["field"])
            if ladder is None:
                continue
            assert ladder.index(action["to"]) > ladder.index(action["from"]), (
                f"{action['field']} recommends {action['from']} -> {action['to']}, "
                "which is a downgrade"
            )

    def test_a_pay_rise_is_offered_as_a_lever(self, client):
        """Salary is numeric, so it needs its own counterfactual - check it works."""
        body = client.post("/api/predict", json=AT_RISK).json()
        pay = [a for a in body["actions"] if a["kind"] == "pay"]
        for action in pay:
            assert action["to"] > AT_RISK["MonthlyIncome"]
            assert "%" in action["display"]

    def test_settled_employee_scores_below_flight_risk(self, client):
        risky = client.post("/api/predict", json=AT_RISK).json()["probability"]
        settled = client.post("/api/predict", json=SETTLED).json()["probability"]
        assert settled < risky

    def test_engineered_values_are_returned(self, client):
        body = client.post("/api/predict", json=AT_RISK).json()
        assert body["engineered"]["TenureBand"] == "Under 2 years"
        assert 0.0 <= body["engineered"]["CareerShare"] <= 1.0

    def test_cost_at_risk_scales_with_salary(self, client):
        low = client.post("/api/predict", json=AT_RISK).json()
        high = client.post("/api/predict", json={**AT_RISK, "MonthlyIncome": 200000}).json()
        assert high["cost_at_risk"] > low["cost_at_risk"]

    def test_gender_is_rejected_as_an_input(self, client):
        """Sending gender must not silently influence anything."""
        with_gender = client.post("/api/predict", json={**AT_RISK, "Gender": "Female"}).json()
        without = client.post("/api/predict", json=AT_RISK).json()
        assert with_gender["probability"] == without["probability"]

    def test_unknown_category_is_rejected(self, client):
        response = client.post("/api/predict", json={**AT_RISK, "JobLevel": "Overlord"})
        assert response.status_code == 422

    def test_out_of_range_number_is_rejected(self, client):
        assert client.post("/api/predict", json={**AT_RISK, "Age": 9}).status_code == 422
        assert client.post(
            "/api/predict", json={**AT_RISK, "MonthlyIncome": -1}
        ).status_code == 422

    def test_defaults_fill_in_a_sparse_request(self, client):
        assert client.post("/api/predict", json={"YearsAtCompany": 1}).status_code == 200


class TestBatch:
    def test_json_batch(self, client):
        body = client.post(
            "/api/predict/batch", json={"employees": [AT_RISK, SETTLED]}
        ).json()
        assert body["count"] == 2
        assert body["results"][0]["probability"] >= body["results"][1]["probability"]
        assert body["cost_at_risk"] > 0

    def test_empty_batch_is_rejected(self, client):
        assert client.post("/api/predict/batch", json={"employees": []}).status_code == 422

    def test_csv_upload(self, client):
        content = RAW_DATA_FILE.read_bytes()
        response = client.post(
            "/api/predict/csv",
            files={"file": ("team.csv", io.BytesIO(content), "text/csv")},
        )
        body = response.json()
        assert response.status_code == 200
        assert body["count"] == 50
        assert body["cost_at_risk"] > 0

    def test_csv_with_missing_columns_is_rejected(self, client):
        bad = io.BytesIO(b"EmployeeID,Age\nEMP-1,30\n")
        response = client.post("/api/predict/csv", files={"file": ("bad.csv", bad, "text/csv")})
        assert response.status_code == 400
        assert "missing required columns" in response.json()["detail"]

    def test_non_csv_is_rejected(self, client):
        response = client.post(
            "/api/predict/csv",
            files={"file": ("notes.txt", io.BytesIO(b"hello"), "text/plain")},
        )
        assert response.status_code == 400


class TestModelCard:
    def test_metrics_are_in_range(self, client):
        body = client.get("/api/model").json()
        for key in ("accuracy", "precision", "recall", "f1", "roc_auc"):
            assert 0.0 <= body["scores"][key] <= 1.0
        assert body["selected_model"] in {
            "Logistic Regression", "Random Forest", "Gradient Boosting"
        }

    def test_confusion_matrix_covers_every_employee(self, client):
        body = client.get("/api/model").json()
        assert sum(body["confusion_matrix"].values()) == body["rows_total"]

    def test_leaderboard_explains_the_winner(self, client):
        body = client.get("/api/model").json()
        assert len(body["leaderboard"]) == 3
        winner = max(body["leaderboard"], key=lambda r: r["roc_auc"])
        assert winner["key"] == body["selected_key"]

    def test_the_small_sample_caveat_is_published(self, client):
        """The API must never present these scores as production benchmarks."""
        body = client.get("/api/model").json()
        caveat = body["evaluation"]["caveat"]
        assert "50-row" in caveat
        assert "over-represented" in caveat

    def test_gender_is_absent_from_feature_importance(self, client):
        body = client.get("/api/model").json()
        assert "Gender" not in {f["feature"] for f in body["feature_importance"]}


class TestHistory:
    def test_predictions_are_recorded(self, client):
        before = client.get("/api/history").json()["summary"]["total"]
        client.post("/api/predict", json=AT_RISK)
        after = client.get("/api/history").json()["summary"]["total"]
        assert after == before + 1

    def test_history_can_be_cleared(self, client):
        client.post("/api/predict", json=AT_RISK)
        assert client.delete("/api/history").json()["deleted"] >= 1
        assert client.get("/api/history").json()["summary"]["total"] == 0

    def test_limit_is_bounded(self, client):
        assert client.get("/api/history?limit=0").status_code == 422
        assert client.get("/api/history?limit=999").status_code == 422
