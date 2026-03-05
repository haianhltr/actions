"""Sprint 1 — Actions API core: health, list, RBAC, audit."""

import pytest

pytestmark = pytest.mark.sprint1


class TestActionsReachable:
    def test_api_root(self, client):
        resp = client.get("/")
        assert resp.status_code == 200

    def test_health_endpoint(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_metrics_endpoint(self, client):
        resp = client.get("/metrics")
        assert resp.status_code == 200
        assert "actions_executed_total" in resp.text


class TestActionsList:
    def test_list_actions_empty_or_populated(self, client):
        resp = client.get("/actions", params={"limit": 10})
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_list_actions_with_filter(self, client):
        resp = client.get("/actions", params={"action_type": "restart_deployment", "limit": 5})
        assert resp.status_code == 200


class TestRestartAction:
    def test_restart_deployment(self, client):
        """Execute a restart action against the calculator API deployment."""
        resp = client.post(
            "/actions",
            json={
                "entity_id": "k8s:lab:calculator:Deployment:api",
                "action_type": "restart_deployment",
                "user": "pytest@team.com",
                "reason": "E2E test restart",
                "parameters": {},
            },
            headers={"X-User-Team": "app-team"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "action_id" in data

    def test_restart_recorded_in_audit(self, client):
        """After a restart, the action appears in the action list."""
        resp = client.get("/actions", params={"action_type": "restart_deployment", "limit": 1})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) > 0
        assert data[0]["action_type"] == "restart_deployment"


class TestScaleAction:
    def test_scale_deployment_up(self, client):
        resp = client.post(
            "/actions",
            json={
                "entity_id": "k8s:lab:calculator:Deployment:api",
                "action_type": "scale_deployment",
                "user": "pytest@team.com",
                "reason": "E2E test scale up",
                "parameters": {"replicas": 2},
            },
            headers={"X-User-Team": "app-team"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"

    def test_scale_deployment_back(self, client):
        """Scale back to 1 to clean up."""
        resp = client.post(
            "/actions",
            json={
                "entity_id": "k8s:lab:calculator:Deployment:api",
                "action_type": "scale_deployment",
                "user": "pytest@team.com",
                "reason": "E2E test scale back",
                "parameters": {"replicas": 1},
            },
            headers={"X-User-Team": "app-team"},
        )
        assert resp.status_code == 200


class TestRBACDenial:
    def test_wrong_team_denied(self, client):
        """A user from the wrong team should be denied."""
        resp = client.post(
            "/actions",
            json={
                "entity_id": "k8s:lab:calculator:Deployment:api",
                "action_type": "restart_deployment",
                "user": "outsider@other.com",
                "reason": "Should be denied",
                "parameters": {},
            },
            headers={"X-User-Team": "other-team"},
        )
        assert resp.status_code == 403
