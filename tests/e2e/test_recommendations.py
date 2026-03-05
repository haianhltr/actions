"""Sprint 2 — Kafka consumer, recommendations, correlation."""

import pytest

pytestmark = pytest.mark.sprint2


class TestRecommendationsEndpoint:
    """Test GET /recommendations endpoint."""

    def test_recommendations_returns_200(self, client):
        r = client.get("/recommendations")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_recommendations_filter_by_entity(self, client):
        r = client.get("/recommendations", params={"entity_id": "nonexistent-entity"})
        assert r.status_code == 200
        assert r.json() == []

    def test_recommendations_filter_by_health_state(self, client):
        r = client.get("/recommendations", params={"health_state": "UNHEALTHY"})
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_recommendations_filter_by_owner_team(self, client):
        r = client.get("/recommendations", params={"owner_team": "app-team"})
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_recommendation_schema(self, client):
        r = client.get("/recommendations")
        assert r.status_code == 200
        for rec in r.json():
            assert "entity_id" in rec
            assert "recommended_action" in rec
            assert "health_state" in rec
            assert "since" in rec


class TestCorrelation:
    """Test that actions get correlation_id from recommendations."""

    def test_action_with_explicit_correlation_id(self, client):
        r = client.post(
            "/actions",
            json={
                "entity_id": "k8s:lab:calculator:Deployment:api",
                "action_type": "restart_deployment",
                "user": "engineer@team.com",
                "reason": "Correlation test",
                "correlation_id": "test-event-id-123",
            },
            headers={"X-User-Team": "app-team"},
        )
        assert r.status_code == 200
        action_id = r.json()["action_id"]

        detail = client.get(f"/actions/{action_id}")
        assert detail.json()["correlation_id"] == "test-event-id-123"

    def test_action_without_correlation_id_gets_none_when_no_recommendation(self, client):
        r = client.post(
            "/actions",
            json={
                "entity_id": "k8s:lab:calculator:Deployment:api",
                "action_type": "restart_deployment",
                "user": "engineer@team.com",
                "reason": "No recommendation exists",
            },
            headers={"X-User-Team": "app-team"},
        )
        assert r.status_code == 200
        action_id = r.json()["action_id"]

        detail = client.get(f"/actions/{action_id}")
        # No recommendation exists for this entity, so correlation_id should be None
        assert detail.json()["correlation_id"] is None


class TestKafkaConsumerMetrics:
    """Test that Kafka consumer metrics are registered."""

    def test_recommendations_metrics_exist(self, client):
        r = client.get("/metrics")
        assert r.status_code == 200
        assert "actions_recommendations_total" in r.text
        assert "actions_recommendations_cleared_total" in r.text
