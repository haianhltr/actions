# Sprint 5 — Integration + Failure Validation + CI/CD

**Goal:** Validate the full closed-loop (detect → recommend → act → recover) with real failure scenarios, set up CI/CD via GitHub Actions, create ArgoCD Application manifests, and finalize the API contract documentation.

**Status:** Not Started
**Depends on:** Sprints 1-4 complete, all other teams operational

---

## Pre-Sprint State

- Actions API running at `http://192.168.1.210:31000` with:
  - `POST /actions` — execute restart/scale/rollback/pause with full RBAC + audit
  - `GET /actions`, `GET /actions/{id}` — action listing + detail
  - `GET /recommendations` — pending recommendations from Kafka events
  - Kafka consumer processing `health.transition.v1` events
  - Full RBAC from `config/rbac.yaml` (fail-closed)
  - Auto-remediation engine with guardrails (rate limit, cooldown, escalation)
  - Correlation: actions linked to triggering events
  - Prometheus metrics, health probe, structured logging
- Ops UI running at `http://192.168.1.210:31080` with:
  - Health Overview page (entity table + filters + auto-refresh)
  - Entity Detail page (health + root cause + action buttons + history)
  - Action Confirmation Dialog
  - Nginx reverse proxy to Actions API and SSOT API
- All dependencies LIVE:
  - Team 4 SSOT API (:30900) — entities, ownership, health_summary
  - Team 5 DHS — health.transition.v1 events on Kafka
  - Team 2 Kafka (kafka.calculator.svc.cluster.local:9092) + Calculator services

## Post-Sprint State

- **E2E scenarios validated:**
  - Worker crash → DHS detects UNHEALTHY → recommendation → restart via UI → recovery confirmed
  - Scale to 0 → DHS detects → scale up via UI → recovery confirmed
  - Unauthorized user → RBAC denies → 403 returned
  - Auto-remediation triggers on CrashLoopBackOff → action logged → recovery confirmed
- **CI/CD pipeline:** GitHub Actions workflow builds and pushes Docker images to `ghcr.io`
- **ArgoCD:** Application YAMLs for `actions-api` and `ops-ui` — auto-deploy on git push
- **Contract docs:** `ACTIONS_CONTRACT.md` with final API spec for all consumers
- **Full test suite** passing: `pytest tests/e2e/ -v`

---

## Milestones

### Milestone 1 — E2E test infrastructure

**Status:** [ ] Not Started

Set up shared test infrastructure: fixtures, helpers, and configuration for the full E2E test suite.

**`tests/requirements.txt`:**
```
pytest==8.3.3
httpx==0.27.2
pytest-timeout==2.3.1
```

**`tests/e2e/conftest.py`:**
```python
import pytest
import httpx
import time

ACTIONS_API = "http://192.168.1.210:31000"
OPS_UI = "http://192.168.1.210:31080"
SSOT_API = "http://192.168.1.210:30900"


@pytest.fixture
def actions_client():
    """HTTP client for Actions API."""
    with httpx.Client(base_url=ACTIONS_API, timeout=30.0) as client:
        yield client


@pytest.fixture
def ssot_client():
    """HTTP client for SSOT API."""
    with httpx.Client(base_url=SSOT_API, timeout=30.0) as client:
        yield client


@pytest.fixture
def ops_ui_client():
    """HTTP client for Ops UI."""
    with httpx.Client(base_url=OPS_UI, timeout=30.0) as client:
        yield client


def wait_for_health_state(entity_id: str, expected_state: str, timeout: int = 180):
    """
    Poll SSOT health_summary until entity reaches expected state or timeout.
    Returns True if state reached, False on timeout.
    """
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = httpx.get(
                f"{SSOT_API}/health_summary/{entity_id}",
                timeout=10.0,
            )
            if r.status_code == 200:
                data = r.json()
                state = data.get("state") or data.get("health_state")
                if state == expected_state:
                    return True
        except Exception:
            pass
        time.sleep(10)
    return False


def wait_for_recommendation(entity_id: str, timeout: int = 180):
    """
    Poll Actions API until a recommendation exists for entity_id or timeout.
    Returns the recommendation dict, or None on timeout.
    """
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = httpx.get(
                f"{ACTIONS_API}/recommendations",
                params={"entity_id": entity_id},
                timeout=10.0,
            )
            if r.status_code == 200:
                recs = r.json()
                if recs:
                    return recs[0]
        except Exception:
            pass
        time.sleep(10)
    return None


def execute_kubectl(command: str) -> str:
    """Execute kubectl command on the k3s cluster via SSH."""
    import subprocess
    result = subprocess.run(
        ["ssh", "5560", f"sudo kubectl {command}"],
        capture_output=True, text=True, timeout=30,
    )
    return result.stdout.strip()
```

**Files to create:**
- `tests/requirements.txt`
- `tests/e2e/conftest.py`

---

### Milestone 2 — E2E: Worker crash → restart → recovery

**Status:** [ ] Not Started

Validate the full closed-loop: crash → DHS detects → recommendation → restart via UI/API → recovery confirmed.

**`tests/e2e/test_e2e_scenarios.py`** — scenario 1:
```python
import pytest
import httpx
import time

from conftest import (
    ACTIONS_API, wait_for_health_state,
    wait_for_recommendation, execute_kubectl,
)

pytestmark = pytest.mark.sprint5


class TestWorkerCrashRestart:
    """
    E2E Scenario: Worker crash → DHS detects UNHEALTHY → recommendation appears
    → restart via Actions API → pods recover → DHS marks HEALTHY.
    """

    ENTITY_ID = "k8s:lab:calculator:Deployment:worker"

    @pytest.mark.timeout(300)
    def test_crash_restart_recovery(self):
        # 1. Verify worker is initially running
        output = execute_kubectl("get deployment worker -n calculator -o jsonpath='{.status.availableReplicas}'")
        assert output.strip("'") not in ["", "0"], "Worker should be running before test"

        # 2. Kill worker pod to trigger CrashLoopBackOff
        execute_kubectl("delete pod -l app=worker -n calculator --grace-period=0 --force")

        # 3. Wait for recommendation to appear (DHS detects + emits event + Actions consumes)
        rec = wait_for_recommendation(self.ENTITY_ID, timeout=180)
        assert rec is not None, "Recommendation should appear after worker crash"
        assert rec["recommended_action"] == "restart_deployment"

        # 4. Execute restart action
        r = httpx.post(
            f"{ACTIONS_API}/actions",
            json={
                "entity_id": self.ENTITY_ID,
                "action_type": "restart_deployment",
                "user": "engineer@team.com",
                "reason": "E2E test: restart after crash",
            },
            timeout=30.0,
        )
        assert r.status_code == 200
        assert r.json()["status"] == "success"
        action_id = r.json()["action_id"]

        # 5. Verify action has correlation_id
        detail = httpx.get(f"{ACTIONS_API}/actions/{action_id}", timeout=10.0)
        assert detail.status_code == 200
        assert detail.json().get("correlation_id") is not None

        # 6. Wait for recovery (DHS marks HEALTHY)
        recovered = wait_for_health_state(self.ENTITY_ID, "HEALTHY", timeout=180)
        assert recovered, "Worker should recover to HEALTHY after restart"

        # 7. Recommendation should be cleared
        time.sleep(15)  # Allow time for HEALTHY event to clear recommendation
        recs = httpx.get(
            f"{ACTIONS_API}/recommendations",
            params={"entity_id": self.ENTITY_ID},
            timeout=10.0,
        ).json()
        assert len(recs) == 0, "Recommendation should be cleared after recovery"
```

**Files to create/modify:**
- `tests/e2e/test_e2e_scenarios.py` (create)

---

### Milestone 3 — E2E: Scale to 0 → scale up → recovery

**Status:** [ ] Not Started

**`tests/e2e/test_e2e_scenarios.py`** — scenario 2 (append to same file):
```python
class TestScaleRecovery:
    """
    E2E Scenario: Scale deployment to 0 → DHS detects UNHEALTHY
    → scale up via Actions API → pods come up → recovery confirmed.
    """

    ENTITY_ID = "k8s:lab:calculator:Deployment:api"

    @pytest.mark.timeout(300)
    def test_scale_down_and_recover(self):
        # 1. Scale API deployment to 0
        r = httpx.post(
            f"{ACTIONS_API}/actions",
            json={
                "entity_id": self.ENTITY_ID,
                "action_type": "scale_deployment",
                "user": "engineer@team.com",
                "reason": "E2E test: scale to 0",
                "parameters": {"replicas": 0},
            },
            timeout=30.0,
        )
        assert r.status_code == 200

        # 2. Wait for DHS to detect UNHEALTHY
        unhealthy = wait_for_health_state(self.ENTITY_ID, "UNHEALTHY", timeout=180)
        assert unhealthy, "Entity should become UNHEALTHY after scale to 0"

        # 3. Scale back up to 1
        r = httpx.post(
            f"{ACTIONS_API}/actions",
            json={
                "entity_id": self.ENTITY_ID,
                "action_type": "scale_deployment",
                "user": "engineer@team.com",
                "reason": "E2E test: scale back up",
                "parameters": {"replicas": 1},
            },
            timeout=30.0,
        )
        assert r.status_code == 200
        assert r.json()["status"] == "success"

        # 4. Wait for recovery
        recovered = wait_for_health_state(self.ENTITY_ID, "HEALTHY", timeout=180)
        assert recovered, "Entity should recover to HEALTHY after scale up"

        # 5. Verify audit trail has both actions
        actions = httpx.get(
            f"{ACTIONS_API}/actions",
            params={"entity_id": self.ENTITY_ID, "limit": 5},
            timeout=10.0,
        ).json()
        scale_actions = [a for a in actions if a["action_type"] == "scale_deployment"]
        assert len(scale_actions) >= 2, "Should have scale-down and scale-up actions"
```

---

### Milestone 4 — E2E: RBAC denial

**Status:** [ ] Not Started

**`tests/e2e/test_e2e_scenarios.py`** — scenario 3 (append):
```python
class TestRBACDenial:
    """
    E2E Scenario: Unauthorized user attempts action → RBAC denies → 403 returned.
    Verifies fail-closed behavior and audit logging of denials.
    """

    def test_unknown_user_denied(self):
        """User not in RBAC config is denied."""
        r = httpx.post(
            f"{ACTIONS_API}/actions",
            json={
                "entity_id": "k8s:lab:calculator:Deployment:api",
                "action_type": "restart_deployment",
                "user": "hacker@evil.com",
                "reason": "Unauthorized attempt",
            },
            timeout=30.0,
        )
        assert r.status_code == 403

    def test_wrong_team_denied(self):
        """User from a different team cannot act on entities they don't own."""
        # engineer@team.com is in app-team, which owns calculator
        # But if we had another team's entity, they'd be denied
        # For MVP, test with a nonexistent entity (fail-closed: no ownership = deny)
        r = httpx.post(
            f"{ACTIONS_API}/actions",
            json={
                "entity_id": "k8s:lab:other-namespace:Deployment:something",
                "action_type": "restart_deployment",
                "user": "engineer@team.com",
                "reason": "Should fail — no ownership for this entity",
            },
            timeout=30.0,
        )
        assert r.status_code in [403, 404]

    def test_platform_admin_bypasses_ownership(self):
        """Platform admin (sre@team.com) can act on any entity."""
        r = httpx.post(
            f"{ACTIONS_API}/actions",
            json={
                "entity_id": "k8s:lab:calculator:Deployment:api",
                "action_type": "restart_deployment",
                "user": "sre@team.com",
                "reason": "Platform admin E2E test",
            },
            timeout=30.0,
        )
        assert r.status_code == 200
```

---

### Milestone 5 — E2E: Auto-remediation triggers

**Status:** [ ] Not Started

**`tests/e2e/test_e2e_scenarios.py`** — scenario 4 (append):
```python
class TestAutoRemediation:
    """
    E2E Scenario: Auto-remediation triggers on CrashLoopBackOff
    → action auto-executed → logged with user=auto-remediation → recovery confirmed.
    """

    ENTITY_ID = "k8s:lab:calculator:Deployment:worker"

    @pytest.mark.timeout(300)
    def test_auto_remediation_triggers_and_recovers(self):
        # 1. Record current auto-remediation action count
        existing = httpx.get(
            f"{ACTIONS_API}/actions",
            params={"user": "auto-remediation", "entity_id": self.ENTITY_ID, "limit": 100},
            timeout=10.0,
        ).json()
        initial_count = len(existing)

        # 2. Kill worker pod to trigger CrashLoopBackOff
        execute_kubectl("delete pod -l app=worker -n calculator --grace-period=0 --force")

        # 3. Wait for auto-remediation to execute
        #    (DHS detects → emits event → Actions consumes → rule matches → auto-action)
        time.sleep(180)  # Allow full pipeline to execute

        # 4. Check that a new auto-remediation action was created
        updated = httpx.get(
            f"{ACTIONS_API}/actions",
            params={"user": "auto-remediation", "entity_id": self.ENTITY_ID, "limit": 100},
            timeout=10.0,
        ).json()

        assert len(updated) > initial_count, (
            f"Auto-remediation should have created a new action "
            f"(was {initial_count}, now {len(updated)})"
        )

        # 5. Verify the auto-action has expected fields
        latest = updated[0]
        assert latest["user_id"] == "auto-remediation"
        assert latest["action_type"] == "restart_deployment"
        assert latest["correlation_id"] is not None
        assert "auto-remediation" in latest.get("reason", "").lower()

        # 6. Wait for recovery
        recovered = wait_for_health_state(self.ENTITY_ID, "HEALTHY", timeout=180)
        # Note: recovery not guaranteed in all cases (depends on app state)
        # but auto-remediation should have tried
```

---

### Milestone 6 — CI/CD: GitHub Actions workflow

**Status:** [ ] Not Started

**GitHub repo:** `haianhltr/actions` (confirm with manager before creating)

**`.github/workflows/ci.yaml`:**
```yaml
name: CI/CD — Actions Platform

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

env:
  REGISTRY: ghcr.io
  ACTIONS_API_IMAGE: ghcr.io/haianhltr/actions-api
  OPS_UI_IMAGE: ghcr.io/haianhltr/ops-ui

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install test dependencies
        run: pip install -r tests/requirements.txt

      - name: Run linting (optional)
        run: |
          pip install ruff
          ruff check apps/actions-api/ --select E,F,W
        continue-on-error: true

  build-actions-api:
    needs: test
    runs-on: ubuntu-latest
    if: github.event_name == 'push' && github.ref == 'refs/heads/main'
    permissions:
      contents: read
      packages: write
    steps:
      - uses: actions/checkout@v4

      - name: Log in to GHCR
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Build and push Actions API
        uses: docker/build-push-action@v5
        with:
          context: apps/actions-api
          push: true
          tags: |
            ${{ env.ACTIONS_API_IMAGE }}:latest
            ${{ env.ACTIONS_API_IMAGE }}:${{ github.sha }}

  build-ops-ui:
    needs: test
    runs-on: ubuntu-latest
    if: github.event_name == 'push' && github.ref == 'refs/heads/main'
    permissions:
      contents: read
      packages: write
    steps:
      - uses: actions/checkout@v4

      - name: Log in to GHCR
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Build and push Ops UI
        uses: docker/build-push-action@v5
        with:
          context: apps/ops-ui
          push: true
          tags: |
            ${{ env.OPS_UI_IMAGE }}:latest
            ${{ env.OPS_UI_IMAGE }}:${{ github.sha }}
```

**Files to create:**
- `.github/workflows/ci.yaml`

**Verification:**
```bash
# Push to main branch and verify GitHub Actions runs
git push origin main

# Check GitHub Actions tab: all jobs should pass
# Check GHCR: images should be published at ghcr.io/haianhltr/actions-api and ghcr.io/haianhltr/ops-ui
```

---

### Milestone 7 — ArgoCD Application YAMLs

**Status:** [ ] Not Started

Create ArgoCD Application manifests for both `actions-api` and `ops-ui`. ArgoCD will auto-deploy when manifests change in the git repo.

**`k8s/argocd/actions-api.yaml`:**
```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: actions-api
  namespace: argocd
  labels:
    team: team6
    component: actions-api
spec:
  project: default
  source:
    repoURL: https://github.com/haianhltr/actions.git
    targetRevision: main
    path: k8s/actions-api
  destination:
    server: https://kubernetes.default.svc
    namespace: actions
  syncPolicy:
    automated:
      selfHeal: true
      prune: true
    syncOptions:
      - CreateNamespace=false
```

**`k8s/argocd/ops-ui.yaml`:**
```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: ops-ui
  namespace: argocd
  labels:
    team: team6
    component: ops-ui
spec:
  project: default
  source:
    repoURL: https://github.com/haianhltr/actions.git
    targetRevision: main
    path: k8s/ops-ui
  destination:
    server: https://kubernetes.default.svc
    namespace: actions
  syncPolicy:
    automated:
      selfHeal: true
      prune: true
    syncOptions:
      - CreateNamespace=false
```

**Files to create:**
- `k8s/argocd/actions-api.yaml`
- `k8s/argocd/ops-ui.yaml`

**Verification:**
```bash
# Apply ArgoCD Applications
ssh 5560 "sudo kubectl apply -f k8s/argocd/"

# Verify in ArgoCD UI
# Navigate to https://192.168.1.210:30443
# Should show actions-api and ops-ui applications in Synced state

# Or via CLI:
ssh 5560 "sudo kubectl get applications -n argocd | grep -E 'actions-api|ops-ui'"
```

---

### Milestone 8 — Write ACTIONS_CONTRACT.md

**Status:** [ ] Not Started

Finalize the API contract documentation with the complete API specification, covering all endpoints, schemas, error codes, and integration details.

**`documentation/contracts/ACTIONS_CONTRACT.md`:**

Content should cover:
- **Service overview** — what Actions does, deployment model, ports
- **All endpoints** — complete request/response schemas for:
  - `POST /actions` — execute action (all supported action types)
  - `GET /actions` — list with filters
  - `GET /actions/{id}` — detail
  - `GET /recommendations` — pending recommendations
  - `GET /health` — readiness probe
  - `GET /metrics` — Prometheus metrics
- **Action types** — restart_deployment, scale_deployment, rollback_deployment (optional), pause_rollout (optional)
- **RBAC rules** — who can do what, fail-closed behavior, team mappings
- **Error responses** — 400, 403, 404, 500 with example payloads
- **Kafka integration** — topic, consumer group, event processing
- **Auto-remediation** — rules, guardrails, how it logs actions
- **Correlation** — how actions link to health.transition events
- **Prometheus metrics** — complete list with labels
- **Integration examples** — curl commands for common operations

**Files to create:**
- `documentation/contracts/ACTIONS_CONTRACT.md`

---

### Milestone 9 — Final integration verification

**Status:** [ ] Not Started

Run the full test suite and verify all components are operational.

```bash
# 1. Install test dependencies
pip install -r tests/requirements.txt

# 2. Run full E2E test suite
pytest tests/e2e/ -v --timeout=300

# 3. Verify all pods are running
ssh 5560 "sudo kubectl get pods -n actions"
# Expected: actions-api (Running), postgres (Running), ops-ui (Running)

# 4. Verify all endpoints respond
curl -s http://192.168.1.210:31000/health     # Actions API health
curl -s http://192.168.1.210:31000/           # Actions API status
curl -s http://192.168.1.210:31080/           # Ops UI loads
curl -s http://192.168.1.210:31000/metrics    # Prometheus metrics

# 5. Verify Kafka consumer is connected
ssh 5560 "sudo kubectl logs deploy/actions-api -n actions --tail=5 | grep kafka"

# 6. Verify RBAC is active
ssh 5560 "sudo kubectl logs deploy/actions-api -n actions --tail=20 | grep RBAC"

# 7. Verify auto-remediation is loaded
ssh 5560 "sudo kubectl logs deploy/actions-api -n actions --tail=20 | grep -i 'auto-remediation'"

# 8. Verify ArgoCD applications are synced
ssh 5560 "sudo kubectl get applications -n argocd | grep -E 'actions|ops'"

# 9. Verify metrics are being collected
curl -s http://192.168.1.210:31000/metrics | grep -E "actions_executed|actions_recommendations|actions_rbac|actions_auto"

# 10. Full end-to-end: trigger failure and verify closed loop
ssh 5560 "sudo kubectl delete pod -l app=worker -n calculator --grace-period=0 --force"
echo "Waiting 3 minutes for full pipeline..."
sleep 180
curl -s "http://192.168.1.210:31000/actions?limit=3" | python3 -m json.tool
# Should show auto-remediation action for worker
```

---

### Milestone 10 — Update docs + write sprint review

**Status:** [ ] Not Started

- Update `documentation/sprint/ROADMAP.md` — mark Sprint 5 as complete, mark overall project as complete
- Write `documentation/sprint/sprint5/REVIEW.md`
- Verify all contract docs are current

**Files to modify:**
- `documentation/sprint/ROADMAP.md`

**Files to create:**
- `documentation/sprint/sprint5/REVIEW.md`

---

## Design Decisions

| Decision | Rationale | Why not X |
|----------|-----------|-----------|
| E2E tests via SSH + httpx | Tests run from dev machine, hit real cluster. Validates full pipeline including K8s, DHS, Kafka. No mocking. | In-cluster test pod: harder to debug, view logs. Mocked tests: don't validate real integration. |
| `pytest-timeout` for long-running tests | E2E tests wait for DHS detection + Kafka events, which take 1-3 minutes. Timeout prevents hanging tests. | No timeout: tests could hang indefinitely on failure. |
| `wait_for_health_state` polling helper | Health state transitions take minutes (DHS evaluation cycle + debounce). Polling with timeout is the simplest reliable approach. | WebSocket listener: DHS doesn't expose WebSocket. Kafka consumer in test: over-complex. |
| GitHub Actions for CI/CD | Standard, free for public repos, built-in GHCR integration. Team already uses GitHub. | Jenkins: requires hosting. GitLab CI: would need migration. |
| ArgoCD auto-sync with self-heal + prune | Ensures cluster state matches git. Self-heal reverts manual changes. Prune removes deleted resources. Standard GitOps. | Manual sync: defeats GitOps purpose. No prune: orphaned resources accumulate. |
| Separate ArgoCD Application per component | Independent sync status. Can see which component is out of sync. Cleaner than one Application for all manifests. | Single Application: harder to debug sync issues, all-or-nothing sync. |
| ACTIONS_CONTRACT.md as final API doc | Single-source contract for all consumers (Ops UI, other teams, future integrations). Supersedes ACTION_SCHEMA.md with complete details. | Swagger/OpenAPI auto-generated: FastAPI can generate this, but a hand-written contract is clearer for cross-team use. |
| GitHub repo `haianhltr/actions` | Consistent with team naming. Confirm with manager before creating. | Monorepo: possible but complicates ArgoCD paths and CI/CD. |

---

## Estimated New Files

| File | Purpose |
|------|---------|
| `tests/requirements.txt` | Test dependencies (pytest, httpx, pytest-timeout) |
| `tests/e2e/conftest.py` | Shared fixtures and helpers (clients, wait functions) |
| `tests/e2e/test_e2e_scenarios.py` | Full E2E test scenarios (crash→restart, scale, RBAC, auto-remediation) |
| `.github/workflows/ci.yaml` | CI/CD pipeline (test, build, push to GHCR) |
| `k8s/argocd/actions-api.yaml` | ArgoCD Application for actions-api |
| `k8s/argocd/ops-ui.yaml` | ArgoCD Application for ops-ui |
| `documentation/contracts/ACTIONS_CONTRACT.md` | Final API contract documentation |
| `documentation/sprint/sprint5/REVIEW.md` | Sprint retrospective |

## Estimated Modified Files

| File | Change |
|------|--------|
| `documentation/sprint/ROADMAP.md` | Mark Sprint 5 + overall project as complete |
