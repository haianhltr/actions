# Sprint 1 — Actions Service Core + Audit DB

**Goal:** Stand up the Actions service from scratch. After this sprint, remediation actions (restart, scale) can be executed via a REST API, every action is recorded in an audit log, and basic RBAC checks ownership before allowing actions.

**Status:** Not Started
**Depends on:** Team 4 Sprint 1 (SSOT API with entities + ownership)

---

## Pre-Sprint State

- Nothing exists. No namespace, no service, no code.

## Post-Sprint State

- `actions` namespace exists in k3s
- Actions Postgres running with audit table
- Actions API (FastAPI) running and accessible at `http://192.168.1.210:31000`
- `POST /actions` — execute remediation action (restart, scale)
- `GET /actions` — list actions with filters
- `GET /actions/{id}` — get action detail
- RBAC: ownership check via SSOT before executing
- Audit: every action recorded in Postgres
- K8s client: restart and scale deployments via in-cluster API
- Prometheus metrics at `/metrics`
- Structured JSON logging
- Health probe at `/health`

---

## Milestones

### Milestone 1 — Create actions namespace + Postgres

**Status:** [ ] Not Started

**`k8s/namespace.yaml`:**
```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: actions
  labels:
    team: team6
    purpose: actions
```

**`k8s/postgres/statefulset.yaml`:**
- Image: `postgres:16-alpine`
- Namespace: `actions`
- Port: 5432
- PVC: 1Gi (audit logs only — small)
- Env: `POSTGRES_DB=actions`, `POSTGRES_USER=actions`, `POSTGRES_PASSWORD` from Secret
- Liveness: `pg_isready`
- Resource limits: 100m CPU, 256Mi memory

**`k8s/postgres/service.yaml`:**
- ClusterIP on port 5432

**Secret (create manually on cluster):**
```bash
ssh 5560 "sudo kubectl create secret generic actions-postgres-secret -n actions \
  --from-literal=POSTGRES_PASSWORD=actions-secret-pw \
  --from-literal=DATABASE_URL=postgresql+asyncpg://actions:actions-secret-pw@postgres.actions.svc.cluster.local:5432/actions"
```

**Files to create:**
- `k8s/namespace.yaml`
- `k8s/postgres/statefulset.yaml`
- `k8s/postgres/service.yaml`

**Verification:**
```bash
ssh 5560 "sudo kubectl get pods -n actions"
ssh 5560 "sudo kubectl exec -n actions statefulset/postgres -- pg_isready -U actions"
```

---

### Milestone 2 — Create Actions API project structure

**Status:** [ ] Not Started

**`apps/actions-api/requirements.txt`:**
```
fastapi==0.115.0
uvicorn==0.30.6
sqlalchemy==2.0.36
asyncpg==0.30.0
pydantic==2.9.2
httpx==0.27.2
kubernetes==31.0.0
prometheus-client==0.21.0
python-json-logger==2.0.7
```

**`apps/actions-api/database.py`:**
- SQLAlchemy async engine + session factory
- `DATABASE_URL` from env var
- `get_db` dependency

**`apps/actions-api/models.py`:**
```python
class Action(Base):
    __tablename__ = "actions"
    id              = Column(Text, primary_key=True)
    entity_id       = Column(Text, nullable=False)
    entity_type     = Column(Text, nullable=False)
    entity_name     = Column(Text, nullable=False)
    namespace       = Column(Text, nullable=False)
    action_type     = Column(Text, nullable=False)       # restart_deployment, scale_deployment
    user_id         = Column(Text, nullable=False)
    user_team       = Column(Text, nullable=True)
    parameters      = Column(JSONB, default=dict)
    reason          = Column(Text, nullable=True)
    status          = Column(Text, nullable=False, default="pending")
    result_message  = Column(Text, nullable=True)
    correlation_id  = Column(Text, nullable=True)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())
    completed_at    = Column(DateTime(timezone=True), nullable=True)
```

**`apps/actions-api/schemas.py`:**
- `ActionRequest` — POST body: entity_id, action_type, user, reason, parameters
- `ActionResponse` — action_id, status, result_message, completed_at
- `ActionDetail` — full action record

**`apps/actions-api/config.py`:**
- Load config from env vars:
  - `DATABASE_URL`
  - `SSOT_API_URL` = `http://ssot-api.ssot:8080`
  - `K8S_IN_CLUSTER` = `true` (use in-cluster config)
  - `MAX_SCALE_REPLICAS` = 10
  - `MIN_SCALE_REPLICAS` = 0

**`apps/actions-api/Dockerfile`:**
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
```

**Files to create:**
- `apps/actions-api/requirements.txt`
- `apps/actions-api/database.py`
- `apps/actions-api/models.py`
- `apps/actions-api/schemas.py`
- `apps/actions-api/config.py`
- `apps/actions-api/Dockerfile`

---

### Milestone 3 — Kubernetes client (restart + scale)

**Status:** [ ] Not Started

**`apps/actions-api/k8s_client.py`:**
- Uses `kubernetes` Python client (in-cluster config)
- `class K8sClient`:
  - `async def restart_deployment(name: str, namespace: str) -> str`
    - Patch deployment with restart annotation:
      ```python
      body = {
          "spec": {
              "template": {
                  "metadata": {
                      "annotations": {
                          "kubectl.kubernetes.io/restartedAt": datetime.utcnow().isoformat()
                      }
                  }
              }
          }
      }
      apps_v1.patch_namespaced_deployment(name, namespace, body)
      ```
    - Returns success message
  - `async def scale_deployment(name: str, namespace: str, replicas: int) -> str`
    - Validate: `MIN_SCALE_REPLICAS <= replicas <= MAX_SCALE_REPLICAS`
    - Patch deployment scale:
      ```python
      body = {"spec": {"replicas": replicas}}
      apps_v1.patch_namespaced_deployment_scale(name, namespace, body)
      ```
    - Returns success message with old → new replica count
  - `async def get_deployment_status(name: str, namespace: str) -> dict`
    - Read deployment status (replicas, available, conditions)
    - For validating action targets exist

- Error handling:
  - K8s API errors → catch and return meaningful error message
  - Deployment not found → 404
  - Forbidden → RBAC issue on service account

**Files to create:**
- `apps/actions-api/k8s_client.py`

---

### Milestone 4 — SSOT client (ownership lookup)

**Status:** [ ] Not Started

**`apps/actions-api/ssot_client.py`:**
- Async HTTP client using `httpx` to query SSOT API
- `async def get_entity(entity_id: str) -> dict | None`
  - `GET /entities/{entity_id}`
  - Returns entity metadata or None if not found
- `async def get_ownership(entity_id: str) -> dict | None`
  - `GET /ownership/{entity_id}`
  - Returns `{team, tier, contact}` or None
- `async def get_health_summary(entity_id: str) -> dict | None`
  - `GET /health_summary/{entity_id}`
- Used by RBAC enforcer to check if user's team owns the entity

**Files to create:**
- `apps/actions-api/ssot_client.py`

---

### Milestone 5 — RBAC enforcer

**Status:** [ ] Not Started

**`apps/actions-api/rbac.py`:**
- `class RBACEnforcer`:
  - `async def check_permission(user: str, entity_id: str, action_type: str) -> tuple[bool, str]`
    1. Get ownership from SSOT: `ssot_client.get_ownership(entity_id)`
    2. If no ownership record → allow (no restriction) with warning log
    3. If user is in `platform-admin` list → allow
    4. If entity owner_team matches user's team → allow
    5. Else → deny with reason "User {user} team does not own entity {entity_id}"
  - Team membership: for MVP, extract team from request header `X-User-Team` or from a simple config file
  - Future: OIDC integration, proper identity

- Log all RBAC decisions (allow/deny) with entity_id, user, action_type
- Instrument: `actions_rbac_denied_total` counter

**Files to create:**
- `apps/actions-api/rbac.py`

---

### Milestone 6 — Actions API endpoints + main.py

**Status:** [ ] Not Started

**`apps/actions-api/main.py`:**

**`POST /actions`** — Execute action:
```python
@app.post("/actions", response_model=ActionResponse, status_code=200)
async def execute_action(body: ActionRequest, db: AsyncSession = Depends(get_db)):
    # 1. Validate entity exists in SSOT
    # 2. Check RBAC permission
    # 3. Parse entity_id to extract namespace + name
    # 4. Execute action via K8s client:
    #    - restart_deployment → k8s_client.restart_deployment(name, ns)
    #    - scale_deployment → k8s_client.scale_deployment(name, ns, replicas)
    # 5. Record in audit DB (status: success or failure)
    # 6. Return ActionResponse
```

**`GET /actions`** — List actions:
```python
@app.get("/actions", response_model=list[ActionDetail])
async def list_actions(
    entity_id: str | None = None,
    user: str | None = None,
    status: str | None = None,
    action_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    # Build query with optional filters
    # Order by created_at DESC
```

**`GET /actions/{id}`** — Get action detail:
```python
@app.get("/actions/{action_id}", response_model=ActionDetail)
```

Also implement:
- Startup: `Base.metadata.create_all` to auto-create tables
- `GET /` — service status (name, version, uptime, action_count)
- `GET /health` — readiness probe
- `GET /metrics` — Prometheus metrics
- Structured JSON logging
- Metrics middleware (request count + latency)

**Files to create/modify:**
- `apps/actions-api/main.py`

**Verification:**
```bash
# Test action execution (restart):
curl -s -X POST http://192.168.1.210:31000/actions \
  -H "Content-Type: application/json" \
  -H "X-User-Team: app-team" \
  -d '{
    "entity_id": "k8s:lab:calculator:Deployment:api",
    "action_type": "restart_deployment",
    "user": "engineer@team.com",
    "reason": "Testing restart action"
  }'

# Test action list:
curl -s "http://192.168.1.210:31000/actions?limit=10" | python -m json.tool

# Test action detail:
curl -s "http://192.168.1.210:31000/actions/{action_id}" | python -m json.tool

# Test RBAC denial:
curl -s -X POST http://192.168.1.210:31000/actions \
  -H "Content-Type: application/json" \
  -H "X-User-Team: other-team" \
  -d '{
    "entity_id": "k8s:lab:calculator:Deployment:api",
    "action_type": "restart_deployment",
    "user": "outsider@other.com",
    "reason": "Should be denied"
  }'
# Should return 403
```

---

### Milestone 7 — Deploy Actions API to k3s

**Status:** [ ] Not Started

**K8s RBAC (create first — Actions needs K8s permissions):**

**`k8s/rbac/serviceaccount.yaml`:**
```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: actions-sa
  namespace: actions
```

**`k8s/rbac/clusterrole.yaml`:**
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: actions-role
rules:
  - apiGroups: ["apps"]
    resources: ["deployments"]
    verbs: ["get", "list", "patch"]
  - apiGroups: ["apps"]
    resources: ["deployments/scale"]
    verbs: ["get", "patch"]
  - apiGroups: [""]
    resources: ["pods"]
    verbs: ["get", "list"]
  - apiGroups: ["apps"]
    resources: ["replicasets"]
    verbs: ["get", "list"]
```

**`k8s/rbac/clusterrolebinding.yaml`:**
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: actions-binding
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: actions-role
subjects:
  - kind: ServiceAccount
    name: actions-sa
    namespace: actions
```

**`k8s/actions-api/deployment.yaml`:**
- Image: `ghcr.io/<repo>/actions-api:latest`
- Namespace: `actions`
- ServiceAccount: `actions-sa`
- Port: 8080
- Env:
  - `DATABASE_URL` from secret
  - `SSOT_API_URL=http://ssot-api.ssot:8080`
  - `K8S_IN_CLUSTER=true`
  - `MAX_SCALE_REPLICAS=10`
- Readiness probe: `GET /health` on port 8080
- Liveness probe: `GET /health` on port 8080
- Resource limits: 100m CPU, 128Mi memory
- Labels: `app: actions-api, service: actions-api, team: team6, env: production`

**`k8s/actions-api/service.yaml`:**
- NodePort 31000 → port 8080

**Files to create:**
- `k8s/rbac/serviceaccount.yaml`
- `k8s/rbac/clusterrole.yaml`
- `k8s/rbac/clusterrolebinding.yaml`
- `k8s/actions-api/deployment.yaml`
- `k8s/actions-api/service.yaml`

**Verification:**
```bash
ssh 5560 "sudo kubectl get pods -n actions"
ssh 5560 "curl -s http://192.168.1.210:31000/"
ssh 5560 "curl -s http://192.168.1.210:31000/health"
ssh 5560 "curl -s http://192.168.1.210:31000/metrics | head -10"
```

---

### Milestone 8 — Smoke test: restart + scale + audit

**Status:** [ ] Not Started

Run a comprehensive smoke test:

```bash
# 1. Verify Actions API is running:
ssh 5560 "curl -s http://192.168.1.210:31000/ | python3 -m json.tool"

# 2. Test restart action:
ssh 5560 "curl -s -X POST http://192.168.1.210:31000/actions \
  -H 'Content-Type: application/json' \
  -H 'X-User-Team: app-team' \
  -d '{
    \"entity_id\": \"k8s:lab:calculator:Deployment:api\",
    \"action_type\": \"restart_deployment\",
    \"user\": \"engineer@team.com\",
    \"reason\": \"Smoke test restart\"
  }'"
# Should return status: success

# 3. Verify restart happened:
ssh 5560 "sudo kubectl rollout status deployment api -n calculator"

# 4. Test scale action:
ssh 5560 "curl -s -X POST http://192.168.1.210:31000/actions \
  -H 'Content-Type: application/json' \
  -H 'X-User-Team: app-team' \
  -d '{
    \"entity_id\": \"k8s:lab:calculator:Deployment:api\",
    \"action_type\": \"scale_deployment\",
    \"user\": \"engineer@team.com\",
    \"reason\": \"Smoke test scale\",
    \"parameters\": {\"replicas\": 2}
  }'"

# 5. Verify scale:
ssh 5560 "sudo kubectl get deployment api -n calculator"
# Should show 2 replicas

# 6. Scale back to 1:
ssh 5560 "curl -s -X POST http://192.168.1.210:31000/actions \
  -H 'Content-Type: application/json' \
  -H 'X-User-Team: app-team' \
  -d '{
    \"entity_id\": \"k8s:lab:calculator:Deployment:api\",
    \"action_type\": \"scale_deployment\",
    \"user\": \"engineer@team.com\",
    \"reason\": \"Scale back\",
    \"parameters\": {\"replicas\": 1}
  }'"

# 7. Check audit trail:
ssh 5560 "curl -s 'http://192.168.1.210:31000/actions?limit=10' | python3 -m json.tool"
# Should show all 3 actions with timestamps and results

# 8. Test RBAC denial:
ssh 5560 "curl -s -X POST http://192.168.1.210:31000/actions \
  -H 'Content-Type: application/json' \
  -H 'X-User-Team: other-team' \
  -d '{
    \"entity_id\": \"k8s:lab:calculator:Deployment:api\",
    \"action_type\": \"restart_deployment\",
    \"user\": \"outsider@other.com\",
    \"reason\": \"Should be denied\"
  }'"
# Should return 403 Forbidden

# 9. Check metrics:
ssh 5560 "curl -s http://192.168.1.210:31000/metrics | grep actions_"
# Should show actions_executed_total, actions_rbac_denied_total
```

All tests must pass before proceeding.

---

### Milestone 9 — Update docs + write sprint review

**Status:** [ ] Not Started

- Update `documentation/sprint/ROADMAP.md` — mark Sprint 1 as complete
- Write `documentation/sprint/sprint1/REVIEW.md`

**Files to modify:**
- `documentation/sprint/ROADMAP.md`

**Files to create:**
- `documentation/sprint/sprint1/REVIEW.md`

---

## Design Decisions

| Decision | Rationale | Why not X |
|----------|-----------|-----------|
| Python 3.12 / FastAPI | Same stack as SSOT and DHS. Async-first. Consistent across platform. | Go: different language. Node: less common for infra. |
| `kubernetes` Python client | Official Kubernetes client. In-cluster auth. Well-documented. | kubectl subprocess: fragile, hard to parse. Direct HTTP: reinventing the wheel. |
| Separate Postgres (not shared) | Independent lifecycle. Audit schema is simple. No coupling to SSOT DB. | Shared with SSOT: schema conflicts, coupled deployments. SQLite: no concurrent access in K8s. |
| Header-based auth (MVP) | Simple to implement. Can be replaced with OIDC later. | OIDC: too complex for MVP. No auth: dangerous for remediation. |
| Patch for restart (not delete) | Rolling restart via annotation patch is safe. No downtime. | Delete pods: causes downtime. kubectl exec: not available in library. |
| NodePort 31000 | Doesn't conflict with other teams (30000-30950 taken). | 30960: too close to DHS. 8080: not externally accessible. |

---

## Estimated New Files

| File | Purpose |
|------|---------|
| `k8s/namespace.yaml` | actions namespace |
| `k8s/postgres/statefulset.yaml` | Audit database |
| `k8s/postgres/service.yaml` | DB service |
| `k8s/rbac/serviceaccount.yaml` | K8s service account |
| `k8s/rbac/clusterrole.yaml` | K8s permissions |
| `k8s/rbac/clusterrolebinding.yaml` | Role binding |
| `k8s/actions-api/deployment.yaml` | API deployment |
| `k8s/actions-api/service.yaml` | API NodePort 31000 |
| `apps/actions-api/main.py` | FastAPI application |
| `apps/actions-api/config.py` | Environment config |
| `apps/actions-api/database.py` | SQLAlchemy setup |
| `apps/actions-api/models.py` | Action ORM model |
| `apps/actions-api/schemas.py` | Pydantic models |
| `apps/actions-api/k8s_client.py` | Kubernetes API client |
| `apps/actions-api/ssot_client.py` | SSOT API client |
| `apps/actions-api/rbac.py` | RBAC enforcer |
| `apps/actions-api/requirements.txt` | Python deps |
| `apps/actions-api/Dockerfile` | Container image |
| `documentation/sprint/sprint1/REVIEW.md` | Sprint retrospective |
