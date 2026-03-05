# Desired Architecture — Actions (Remediation & Control Plane)

**Goal:** Controlled remediation layer that consumes DHS health decisions and enables safe, auditable, RBAC-enforced remediation actions. Actions turns health decisions into controlled operations.

---

## System Diagram

```
┌──────────────────────────────────────────────────────────────────────────┐
│                     k3s Cluster — Lenovo 5560                          │
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐    │
│  │  namespace: actions (Team 6)                                     │    │
│  │                                                                  │    │
│  │  ┌───────────────────────────────────────────────────────┐      │    │
│  │  │              Actions Service (:31000)                  │      │    │
│  │  │                                                        │      │    │
│  │  │  ┌──────────────┐  ┌──────────────┐  ┌────────────┐  │      │    │
│  │  │  │ Kafka        │  │ Remediation  │  │ RBAC       │  │      │    │
│  │  │  │ Consumer     │  │ Engine       │  │ Enforcer   │  │      │    │
│  │  │  │ (health.     │  │ (restart,    │  │ (team,     │  │      │    │
│  │  │  │  transition) │  │  scale)      │  │  tier)     │  │      │    │
│  │  │  └──────┬───────┘  └──────┬───────┘  └─────┬──────┘  │      │    │
│  │  │         │                 │                 │          │      │    │
│  │  │  ┌──────▼─────────────────▼─────────────────▼──────┐  │      │    │
│  │  │  │                K8s API Client                     │  │      │    │
│  │  │  │  - rollout restart deployment                     │  │      │    │
│  │  │  │  - scale deployment replicas                      │  │      │    │
│  │  │  │  - read deployment/pod status                     │  │      │    │
│  │  │  └──────┬──────────────────────────────┬───────────┘  │      │    │
│  │  │         │                              │              │      │    │
│  │  │  ┌──────▼───────┐              ┌───────▼──────────┐   │      │    │
│  │  │  │ Audit Writer │              │ REST API         │   │      │    │
│  │  │  │ (Postgres)   │              │ /actions         │   │      │    │
│  │  │  │              │              │ /actions/{id}    │   │      │    │
│  │  │  └──────────────┘              └──────────────────┘   │      │    │
│  │  └───────────────────────────────────────────────────────┘      │    │
│  │                                                                  │    │
│  │  ┌───────────────────────────┐  ┌────────────────────────┐      │    │
│  │  │  Ops UI (:31080)          │  │  Actions Postgres      │      │    │
│  │  │  - Health Overview        │  │  - actions table       │      │    │
│  │  │  - Entity Detail          │  │  - (approvals future)  │      │    │
│  │  │  - Action Buttons         │  │                        │      │    │
│  │  │  - Action History         │  │                        │      │    │
│  │  └───────────────────────────┘  └────────────────────────┘      │    │
│  └──────────────────────────────────────────────────────────────────┘    │
│                                                                          │
│  READS FROM:                                                             │
│  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────────┐         │
│  │ SSOT API        │  │ Kafka           │  │ Kubernetes API   │         │
│  │ :30900          │  │ health.         │  │ in-cluster       │         │
│  │ entities,       │  │ transition.v1   │  │ deployments,     │         │
│  │ ownership,      │  │ events from DHS │  │ pods, status     │         │
│  │ health_summary  │  │                 │  │                  │         │
│  └─────────────────┘  └─────────────────┘  └──────────────────┘         │
│                                                                          │
│  WRITES TO:                                                              │
│  ┌─────────────────┐  ┌─────────────────────────────┐                    │
│  │ Kubernetes API  │  │ Actions Postgres             │                    │
│  │ restart, scale  │  │ audit log of all actions     │                    │
│  └─────────────────┘  └─────────────────────────────┘                    │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## Actions Service Components

### Kafka Consumer

- Subscribes to Kafka topic `health.transition.v1`
- Consumes transition events from DHS
- For each event:
  - Store as "pending recommendation" (in-memory or DB)
  - Match against auto-remediation rules (Phase 2)
  - Make event data available to UI for "recommended actions"
- Consumer group: `actions-consumer-group`
- At-least-once delivery (idempotent action handling)

### Remediation Engine

Executes safe, reversible actions against Kubernetes:

#### Required Actions (MVP)

| Action | K8s Operation | Target | Safe? |
|--------|---------------|--------|-------|
| `restart_deployment` | `kubectl rollout restart deployment <name> -n <ns>` | Deployment | Yes — rolling restart |
| `scale_deployment` | `kubectl scale deployment <name> -n <ns> --replicas=N` | Deployment | Yes — within bounds |

#### Optional Actions (Phase 2)

| Action | K8s Operation | Target | Safe? |
|--------|---------------|--------|-------|
| `rollback_deployment` | `kubectl rollout undo deployment <name> -n <ns>` | Deployment | Mostly — reverts to previous revision |
| `pause_rollout` | `kubectl rollout pause deployment <name> -n <ns>` | Deployment | Yes — stops rollout progression |

#### Safety Bounds

- Scale: min_replicas=0, max_replicas=10 (configurable per entity type)
- Restart: no bounds (always safe — rolling restart)
- Rollback: only one revision back (no multi-step rollback)

### RBAC Enforcer

Before executing any action, validate:

1. **User identity** — who is requesting the action?
2. **Ownership check** — does user's team own the target entity? (query SSOT ownership)
3. **No ownership record** — **deny (fail closed)**. If SSOT has no ownership for the entity, the action is rejected with 403.
4. **Tier restrictions:**
   - Tier-3: any team member can act
   - Tier-2: any team member can act (with audit)
   - Tier-1: requires SRE/platform team approval (future)
5. **Platform role** — `platform-admin` can act on any entity

RBAC rules configurable via `config/rbac.yaml`.

### Audit Writer

Every action must be recorded:

```json
{
  "action_id": "uuid",
  "entity_id": "k8s:lab:calculator:Deployment:api",
  "entity_type": "Deployment",
  "entity_name": "api",
  "namespace": "calculator",
  "action_type": "restart_deployment",
  "user": "engineer@team.com",
  "team": "app-team",
  "parameters": {"reason": "CrashLoopBackOff detected"},
  "status": "success",
  "result_message": "Rollout restart initiated",
  "correlation_id": "health-transition-event-uuid",
  "created_at": "2026-03-02T10:20:00Z",
  "completed_at": "2026-03-02T10:20:01Z"
}
```

### REST API

| Method | Route | Purpose |
|--------|-------|---------|
| POST | `/actions` | Execute an action (requires auth) |
| GET | `/actions` | List actions (filter by entity, user, status) |
| GET | `/actions/{id}` | Get action detail + result |
| GET | `/recommendations` | Get pending recommendations from health.transition events |
| GET | `/health` | Readiness probe |
| GET | `/metrics` | Prometheus metrics |

#### POST /actions Request

```json
{
  "entity_id": "k8s:lab:calculator:Deployment:api",
  "action_type": "restart_deployment",
  "user": "engineer@team.com",
  "reason": "CrashLoopBackOff detected, restarting to recover",
  "parameters": {}
}
```

#### POST /actions Response

```json
{
  "action_id": "uuid",
  "status": "success",
  "result_message": "Rollout restart initiated for deployment api in namespace calculator",
  "completed_at": "2026-03-02T10:20:01Z"
}
```

---

## Ops UI

### Technology

- Static HTML/CSS/JS (no framework needed for MVP)
- Or lightweight framework (Alpine.js, htmx, or vanilla JS)
- Served by Nginx or the Actions API itself
- Reads from SSOT API and Actions API

### Pages

#### Health Overview Page

| Column | Source |
|--------|--------|
| Entity | SSOT `/entities` |
| Type | SSOT entity.type |
| Health State | SSOT `/health_summary` |
| Root Cause | SSOT health_summary.root_cause_entity_id |
| Owner | SSOT `/ownership` |
| Last Transition | SSOT health_summary.updated_at |

- Filter by: state (HEALTHY, DEGRADED, UNHEALTHY), type, owner team
- Color coding: green/yellow/red/gray
- Auto-refresh every 30s

#### Entity Detail Page

- Entity metadata (from SSOT)
- Current health state + reason
- Root cause chain (follow root_cause_entity_id)
- Recent transitions (from SSOT health_summary history or DHS events)
- Available actions (restart, scale) with buttons
- Action history for this entity (from Actions API)

#### Action Confirmation Dialog

- "Are you sure you want to restart Deployment api in namespace calculator?"
- Optional reason field
- Confirm / Cancel buttons
- Shows result after execution

---

## Storage

### Actions Postgres

```sql
CREATE TABLE actions (
    id              TEXT PRIMARY KEY,
    entity_id       TEXT NOT NULL,
    entity_type     TEXT NOT NULL,
    entity_name     TEXT NOT NULL,
    namespace       TEXT NOT NULL,
    action_type     TEXT NOT NULL,       -- restart_deployment, scale_deployment
    user_id         TEXT NOT NULL,
    user_team       TEXT,
    parameters      JSONB DEFAULT '{}',
    reason          TEXT,
    status          TEXT NOT NULL DEFAULT 'pending',  -- pending, success, failure
    result_message  TEXT,
    correlation_id  TEXT,               -- link to health.transition event
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ
);

CREATE INDEX idx_actions_entity ON actions(entity_id);
CREATE INDEX idx_actions_user ON actions(user_id);
CREATE INDEX idx_actions_status ON actions(status);
CREATE INDEX idx_actions_created ON actions(created_at DESC);
```

### Future: Approvals Table (Phase 2+)

```sql
CREATE TABLE approvals (
    id          TEXT PRIMARY KEY,
    action_id   TEXT NOT NULL REFERENCES actions(id),
    approver    TEXT NOT NULL,
    decision    TEXT NOT NULL,          -- approved, denied
    reason      TEXT,
    decided_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

---

## Auto-Remediation (Phase 2)

### Config Format

```yaml
# config/auto-remediation.yaml
auto_actions:
  - name: restart_on_crashloop
    trigger:
      new_state: UNHEALTHY
      reason_contains: "CrashLoopBackOff"
      entity_type: Deployment
    action:
      type: restart_deployment
      max_per_hour: 2
      cooldown_minutes: 30
    enabled: true

  - name: scale_on_lag
    trigger:
      new_state: DEGRADED
      reason_contains: "Consumer lag"
      entity_type: Deployment
    action:
      type: scale_deployment
      parameters:
        replicas_add: 1
        max_replicas: 5
      max_per_hour: 3
      cooldown_minutes: 15
    enabled: false
```

### Guardrails

- Rate limiting: max N auto-actions per hour per entity
- Cooldown: no repeat auto-action within cooldown period
- Escalation: if auto-action fails or entity stays UNHEALTHY → stop auto-remediating, alert
- All auto-actions logged with `user: "auto-remediation"`
- Never auto-delete resources
- Never auto-rollback without explicit config

---

## Kubernetes RBAC

### Service Account

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: actions-sa
  namespace: actions
```

### ClusterRole (minimal permissions)

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: actions-role
rules:
  - apiGroups: ["apps"]
    resources: ["deployments"]
    verbs: ["get", "list", "patch"]        # patch for restart + scale
  - apiGroups: ["apps"]
    resources: ["deployments/scale"]
    verbs: ["get", "patch"]
  - apiGroups: [""]
    resources: ["pods"]
    verbs: ["get", "list"]                 # read pod status
  - apiGroups: ["apps"]
    resources: ["replicasets"]
    verbs: ["get", "list"]                 # for rollback history
```

### ClusterRoleBinding

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

---

## Application RBAC Config

```yaml
# config/rbac.yaml
roles:
  platform-admin:
    can_act_on: all
    description: "Can act on any entity in any namespace"

  team-member:
    can_act_on: owned_entities
    description: "Can act on entities owned by their team"

team_mappings:
  app-team:
    members:
      - "engineer@team.com"
    owns:
      - "k8s:lab:calculator:*"

  platform-team:
    members:
      - "sre@team.com"
    role: platform-admin

tier_restrictions:
  tier-1:
    requires_approval: true
  tier-2:
    requires_approval: false
  tier-3:
    requires_approval: false
```

---

## Kubernetes Deployment Model

| Component | Kind | Namespace | Replicas | Exposed | Notes |
|-----------|------|-----------|----------|---------|-------|
| Actions API | Deployment | actions | 1 | NodePort 31000 | FastAPI + uvicorn |
| Actions Postgres | StatefulSet | actions | 1 | ClusterIP | PVC 1Gi, audit log only |
| Ops UI | Deployment | actions | 1 | NodePort 31080 | Static files via Nginx |

All pods must have resource requests/limits, liveness/readiness probes.

---

## Ports Summary

| Port | Service | Namespace |
|------|---------|-----------|
| 31000 | Actions API | actions |
| 31080 | Ops UI | actions |

---

## Prometheus Metrics (Actions Service)

| Metric | Type | Purpose |
|--------|------|---------|
| `actions_executed_total` | Counter (action_type, status) | Actions executed |
| `actions_execution_duration_seconds` | Histogram (action_type) | Time to execute action |
| `actions_recommendations_total` | Counter | Health transition events received |
| `actions_rbac_denied_total` | Counter | RBAC denials |
| `actions_api_requests_total` | Counter (method, endpoint, status) | API request count |
| `actions_api_request_duration_seconds` | Histogram (method, endpoint) | API latency |
| `actions_auto_remediation_total` | Counter (action_name, status) | Auto-actions triggered (Phase 2) |

---

## End-to-End Action Flow

```
1. DHS detects Worker UNHEALTHY (CrashLoopBackOff, 0/3 replicas for >60s)
2. DHS emits health.transition event to Kafka
3. Actions Service consumes event
4. Actions stores recommendation: "restart_deployment for calculator-worker"
5. [Optional] Slack notification sent (future integration)
6. Engineer opens Ops UI at :31080
7. Sees: Worker UNHEALTHY, root cause = Worker Deployment, recommended action = Restart
8. Clicks "Restart" button
9. Ops UI sends POST /actions to Actions API
10. Actions API:
    a. Validates RBAC (engineer's team owns calculator-worker)
    b. Calls K8s API: rollout restart deployment calculator-worker -n calculator
    c. Records audit log in Postgres
    d. Returns success
11. Kubernetes rolls new pods
12. Metrics stabilize → DHS marks Worker HEALTHY
13. DHS emits recovery health.transition event
14. Ops UI shows green state
```

---

## Definition of Done

Actions Team is done when:

1. **health.transition events consumed** — Actions service reads from Kafka topic
2. **UI displays health** — Ops UI shows entity health, root cause, owner
3. **Restart works** — Restart Deployment action executes via K8s API
4. **Scale works** — Scale Deployment action executes within bounds
5. **Audit logs** — Every action recorded with who/what/when/result
6. **RBAC enforced** — Only owner team can act on their entities
7. **Failure scenarios tested:**
   - Worker crash → restart via UI works → recovery confirmed
   - Scale to 0 → scale up via UI works → recovery confirmed
   - Unauthorized user cannot restart another team's deployment
8. **No dangerous actions** — Actions cannot break the system accidentally
