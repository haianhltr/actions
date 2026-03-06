import pytest
import httpx

pytestmark = pytest.mark.sprint4

ACTIONS_API = "http://192.168.1.210:31000"


class TestRBACFullEnforcement:
    """Test full RBAC enforcement from config/rbac.yaml."""

    def test_authorized_team_member_allowed(self):
        """engineer@team.com (app-team) can act on calculator entities."""
        r = httpx.post(
            f"{ACTIONS_API}/actions",
            json={
                "entity_id": "k8s:lab:calculator:Deployment:api",
                "action_type": "restart_deployment",
                "user": "engineer@team.com",
                "reason": "RBAC test — authorized",
            },
        )
        assert r.status_code == 200
        assert r.json()["status"] == "success"

    def test_unknown_user_denied(self):
        """User not in RBAC config gets 403."""
        r = httpx.post(
            f"{ACTIONS_API}/actions",
            json={
                "entity_id": "k8s:lab:calculator:Deployment:api",
                "action_type": "restart_deployment",
                "user": "nobody@unknown.com",
                "reason": "Should be denied",
            },
        )
        assert r.status_code == 403

    def test_platform_admin_allowed_on_any_entity(self):
        """sre@team.com (platform-admin) can act on any entity."""
        r = httpx.post(
            f"{ACTIONS_API}/actions",
            json={
                "entity_id": "k8s:lab:calculator:Deployment:api",
                "action_type": "restart_deployment",
                "user": "sre@team.com",
                "reason": "Platform admin test",
            },
        )
        assert r.status_code == 200

    def test_fail_closed_no_ownership(self):
        """Entity without ownership record in SSOT is denied (fail-closed)."""
        r = httpx.post(
            f"{ACTIONS_API}/actions",
            json={
                "entity_id": "k8s:lab:unknown:Deployment:nonexistent",
                "action_type": "restart_deployment",
                "user": "engineer@team.com",
                "reason": "Should be denied — no ownership",
            },
        )
        assert r.status_code in [403, 404]


class TestPhase2Actions:
    """Test pause and resume rollout actions."""

    def test_pause_rollout(self):
        r = httpx.post(
            f"{ACTIONS_API}/actions",
            json={
                "entity_id": "k8s:lab:calculator:Deployment:api",
                "action_type": "pause_rollout",
                "user": "sre@team.com",
                "reason": "Test pause",
            },
        )
        assert r.status_code == 200
        assert "paused" in r.json()["result_message"].lower()

    def test_resume_rollout(self):
        r = httpx.post(
            f"{ACTIONS_API}/actions",
            json={
                "entity_id": "k8s:lab:calculator:Deployment:api",
                "action_type": "resume_rollout",
                "user": "sre@team.com",
                "reason": "Test resume",
            },
        )
        assert r.status_code == 200
        assert "resumed" in r.json()["result_message"].lower()


class TestAutoRemediationAudit:
    """Test that auto-remediation metrics and audit are accessible."""

    def test_auto_remediation_metrics_exist(self):
        r = httpx.get(f"{ACTIONS_API}/metrics")
        assert r.status_code == 200
        assert "actions_auto_remediation_total" in r.text
        assert "actions_auto_remediation_blocked_total" in r.text

    def test_auto_remediation_actions_queryable(self):
        """Auto-remediation actions should be queryable with user filter."""
        r = httpx.get(
            f"{ACTIONS_API}/actions",
            params={"user": "auto-remediation", "limit": 10},
        )
        assert r.status_code == 200

    def test_rbac_denied_metric(self):
        """RBAC denied metric should exist."""
        r = httpx.get(f"{ACTIONS_API}/metrics")
        assert r.status_code == 200
        assert "actions_rbac_denied_total" in r.text
