# Contract: Action Schema

**Owner:** team6 (Actions)
**Consumers:** team0 (ActionRequest CRs created by Actions API), engineers (via Ops UI and direct API calls)
**API Base URL (external):** `http://192.168.1.210:31000`
**API Base URL (in-cluster):** `http://actions-api.actions:8080`

---

## Action Types

| Action Type | K8s Operation | Target | Safe | Notes |
|-------------|---------------|--------|------|-------|
| `restart_deployment` | `rollout restart deployment` | Deployment | Yes | Rolling restart, zero downtime |
| `scale_deployment` | `scale deployment --replicas=N` | Deployment | Yes | Bounded: 0–10 replicas |
| `rollback_deployment` | `rollout undo deployment` | Deployment | Mostly | Phase 2 — reverts one revision |
| `pause_rollout` | `rollout pause deployment` | Deployment | Yes | Phase 2 |
| `resume_rollout` | `rollout resume deployment` | Deployment | Yes | Phase 2 |

MVP (Sprint 1): `restart_deployment` and `scale_deployment` only.

---

## POST /actions — Execute Action

**Request:**
```json
{
  "entity_id": "k8s:lab:calculator:Deployment:api",
  "action_type": "restart_deployment",
  "user": "engineer@team.com",
  "reason": "CrashLoopBackOff detected — restarting to recover",
  "parameters": {}
}
```

For `scale_deployment`, include `parameters`:
```json
{
  "entity_id": "k8s:lab:calculator:Deployment:worker",
  "action_type": "scale_deployment",
  "user": "engineer@team.com",
  "reason": "Scaling up to handle load",
  "parameters": {"replicas": 3}
}
```

**Response `200 OK`:**
```json
{
  "action_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "success",
  "result_message": "Rollout restart initiated for deployment api in namespace calculator",
  "completed_at": "2026-03-02T10:20:01Z"
}
```

**Response `403 Forbidden` (RBAC denied):**
```json
{"detail": "User engineer@team.com does not own entity k8s:lab:platform:Deployment:registrar"}
```

**Response `400 Bad Request`:**
```json
{"detail": "Scale replicas 15 exceeds max allowed 10"}
```

---

## GET /actions — List Actions

**Query params:** `entity_id=X`, `user=Y`, `status=success|failure|pending`, `limit=50`

**Response `200 OK`:**
```json
[
  {
    "action_id": "550e8400-...",
    "entity_id": "k8s:lab:calculator:Deployment:api",
    "entity_type": "Deployment",
    "entity_name": "api",
    "namespace": "calculator",
    "action_type": "restart_deployment",
    "user": "engineer@team.com",
    "user_team": "app-team",
    "reason": "CrashLoopBackOff detected",
    "status": "success",
    "result_message": "Rollout restart initiated",
    "correlation_id": "health-transition-event-uuid",
    "created_at": "2026-03-02T10:20:00Z",
    "completed_at": "2026-03-02T10:20:01Z"
  }
]
```

---

## GET /actions/{id} — Get Action Detail

**Response `200 OK`:** Same as action object above.

---

## GET /recommendations — Pending Recommendations

Recommendations derived from DHS `health.transition.v1` events.

**Response `200 OK`:**
```json
[
  {
    "entity_id": "k8s:lab:calculator:Deployment:worker",
    "entity_name": "worker",
    "health_state": "UNHEALTHY",
    "reason": "Worker failure rate 15% > 10%",
    "root_cause_entity_id": "k8s:lab:calculator:Deployment:worker",
    "recommended_action": "restart_deployment",
    "owner_team": "app-team",
    "tier": "tier-2",
    "since": "2026-03-02T10:15:00Z"
  }
]
```

---

## Audit Log Schema (Postgres)

Every action executed is recorded in the `actions` table:

| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT PK | UUID action ID |
| `entity_id` | TEXT | SSOT entity ID |
| `entity_type` | TEXT | Entity type |
| `entity_name` | TEXT | Short entity name |
| `namespace` | TEXT | K8s namespace |
| `action_type` | TEXT | `restart_deployment`, `scale_deployment` |
| `user_id` | TEXT | Who requested (email or service name) |
| `user_team` | TEXT | Team (from SSOT ownership) |
| `parameters` | JSONB | Action parameters (e.g. `{"replicas": 3}`) |
| `reason` | TEXT | Human-readable justification |
| `status` | TEXT | `pending`, `success`, `failure` |
| `result_message` | TEXT | Execution result description |
| `correlation_id` | TEXT | Link to `health.transition.v1` event ID |
| `created_at` | TIMESTAMPTZ | When action was requested |
| `completed_at` | TIMESTAMPTZ | When action finished |

---

## Safety Bounds

| Constraint | Value |
|------------|-------|
| Max replicas (scale) | 10 |
| Min replicas (scale) | 0 |
| Allowed namespaces | `calculator`, `ssot`, `dhs`, `observability` |
| Allowed target kinds | `Deployment` |
| Auto-remediation rate limit | Configurable per rule in `config/auto-remediation.yaml` |

Actions will reject any request outside these bounds with `400 Bad Request`.

---

## How Team 0 Is Used

MVP: Actions API calls K8s directly via in-cluster service account.

Phase 2: Actions API creates `ActionRequest` CRs instead:

```yaml
apiVersion: platform.lab.io/v1alpha1
kind: ActionRequest
metadata:
  name: restart-api-<uuid>
  namespace: ops
spec:
  target:
    kind: Deployment
    namespace: calculator
    name: api
  action: RestartDeployment
  reason: "CrashLoopBackOff detected by DHS"
  requestor: "actions-api"
```

Then Actions API polls `ActionRequest.status.phase` until `Succeeded` or `Failed`.
See `team0/platform-automation/documentation/contracts/ACTIONREQUEST_CRD.md` for the full CR spec.
