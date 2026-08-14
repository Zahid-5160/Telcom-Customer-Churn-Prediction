"""Tests for the prediction service and the HTTP API."""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from churn.api import app
from churn.config import MODEL_FILE, RAW_DATA_FILE

pytestmark = pytest.mark.skipif(
    not MODEL_FILE.exists(), reason="run `python main.py train` first"
)

VALID = {
    "gender": "Female", "SeniorCitizen": "No", "Partner": "No", "Dependents": "No",
    "tenure": 3, "PhoneService": "Yes", "MultipleLines": "No",
    "InternetService": "Fiber optic", "OnlineSecurity": "No", "OnlineBackup": "No",
    "DeviceProtection": "No", "TechSupport": "No", "StreamingTV": "Yes",
    "StreamingMovies": "Yes", "Contract": "Month-to-month", "PaperlessBilling": "Yes",
    "PaymentMethod": "Electronic check", "MonthlyCharges": 95.0, "TotalCharges": 285.0,
}

LOYAL = {**VALID, "tenure": 68, "Contract": "Two year", "TotalCharges": 4500.0,
         "PaymentMethod": "Bank transfer (automatic)", "TechSupport": "Yes",
         "OnlineSecurity": "Yes", "InternetService": "DSL", "MonthlyCharges": 65.0}


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
        assert "Contract" in body["categorical"]
        assert body["categorical"]["Contract"] == ["Month-to-month", "One year", "Two year"]
        assert set(body["numeric"]) == {"tenure", "MonthlyCharges", "TotalCharges"}

    def test_dashboard_is_served(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert "Churn Insight" in response.text

    def test_static_assets_are_served(self, client):
        assert client.get("/css/styles.css").status_code == 200
        assert client.get("/js/app.js").status_code == 200
        assert client.get("/js/charts.js").status_code == 200


class TestPredict:
    def test_returns_a_usable_result(self, client):
        body = client.post("/api/predict", json=VALID).json()
        assert 0.0 <= body["probability"] <= 1.0
        assert body["percent"] == pytest.approx(body["probability"] * 100, abs=0.1)
        assert body["risk_band"] in {"Low", "Moderate", "High", "Critical"}
        assert isinstance(body["will_churn"], bool)

    def test_flag_follows_the_threshold(self, client):
        body = client.post("/api/predict", json=VALID).json()
        assert body["will_churn"] == (body["probability"] >= body["threshold"])

    def test_explanations_are_present_and_ordered(self, client):
        body = client.post("/api/predict", json=VALID).json()
        impacts = [abs(d["impact"]) for d in body["drivers"]]
        assert impacts == sorted(impacts, reverse=True)
        reductions = [a["reduction"] for a in body["actions"]]
        assert reductions == sorted(reductions, reverse=True)
        assert all(a["reduction"] > 0 for a in body["actions"])

    def test_recommended_actions_really_lower_the_risk(self, client):
        """An action is only worth showing if applying it actually scores lower."""
        body = client.post("/api/predict", json=VALID).json()
        for action in body["actions"]:
            changed = {**VALID, action["field"]: action["to"]}
            after = client.post("/api/predict", json=changed).json()
            assert after["probability"] < body["probability"] + 1e-9

    def test_actions_never_suggest_changing_who_someone_is(self, client):
        body = client.post("/api/predict", json=VALID).json()
        off_limits = {"gender", "SeniorCitizen", "Partner", "Dependents"}
        assert not off_limits & {a["field"] for a in body["actions"]}

    def test_loyal_customer_scores_below_risky_one(self, client):
        risky = client.post("/api/predict", json=VALID).json()["probability"]
        loyal = client.post("/api/predict", json=LOYAL).json()["probability"]
        assert loyal < risky

    def test_engineered_values_are_returned(self, client):
        body = client.post("/api/predict", json=VALID).json()
        assert body["engineered"]["TenureBand"] == "0-6 months"
        assert body["engineered"]["NumServices"] >= 1

    def test_unknown_category_is_rejected(self, client):
        response = client.post("/api/predict", json={**VALID, "Contract": "Lifetime"})
        assert response.status_code == 422

    def test_out_of_range_number_is_rejected(self, client):
        assert client.post("/api/predict", json={**VALID, "tenure": -5}).status_code == 422
        assert client.post("/api/predict", json={**VALID, "MonthlyCharges": -1}).status_code == 422

    def test_defaults_fill_in_a_sparse_request(self, client):
        response = client.post("/api/predict", json={"tenure": 1})
        assert response.status_code == 200


class TestBatch:
    def test_json_batch(self, client):
        body = client.post("/api/predict/batch", json={"customers": [VALID, LOYAL]}).json()
        assert body["count"] == 2
        assert 0 <= body["flagged"] <= 2
        # results come back riskiest first
        assert body["results"][0]["probability"] >= body["results"][1]["probability"]

    def test_empty_batch_is_rejected(self, client):
        assert client.post("/api/predict/batch", json={"customers": []}).status_code == 422

    def test_csv_upload(self, client):
        content = RAW_DATA_FILE.read_bytes()
        response = client.post(
            "/api/predict/csv",
            files={"file": ("customers.csv", io.BytesIO(content), "text/csv")},
        )
        body = response.json()
        assert response.status_code == 200
        assert body["count"] == 50
        assert body["annual_value_at_risk"] > 0

    def test_csv_with_missing_columns_is_rejected(self, client):
        bad = io.BytesIO(b"customerID,tenure\n1,5\n")
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
        scores = body["scores"]
        for key in ("accuracy", "precision", "recall", "f1", "roc_auc"):
            assert 0.0 <= scores[key] <= 1.0
        assert body["selected_model"] in {"Logistic Regression", "Random Forest", "Gradient Boosting"}

    def test_confusion_matrix_covers_every_customer(self, client):
        body = client.get("/api/model").json()
        m = body["confusion_matrix"]
        assert sum(m.values()) == body["rows_total"]

    def test_leaderboard_explains_the_winner(self, client):
        body = client.get("/api/model").json()
        assert len(body["leaderboard"]) == 3
        winner = max(body["leaderboard"], key=lambda r: r["roc_auc"])
        assert winner["key"] == body["selected_key"]

    def test_the_small_sample_caveat_is_published(self, client):
        """The API must never present these scores as production benchmarks."""
        body = client.get("/api/model").json()
        assert "caveat" in body["evaluation"]
        assert "50-row" in body["evaluation"]["caveat"]


class TestHistory:
    def test_predictions_are_recorded(self, client):
        before = client.get("/api/history").json()["summary"]["total"]
        client.post("/api/predict", json=VALID)
        after = client.get("/api/history").json()["summary"]["total"]
        assert after == before + 1

    def test_history_can_be_cleared(self, client):
        client.post("/api/predict", json=VALID)
        assert client.delete("/api/history").json()["deleted"] >= 1
        assert client.get("/api/history").json()["summary"]["total"] == 0

    def test_limit_is_bounded(self, client):
        assert client.get("/api/history?limit=0").status_code == 422
        assert client.get("/api/history?limit=999").status_code == 422
