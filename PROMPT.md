# Copy-Paste Prompt for Team 6 — Sprint 1: Actions Service Core + Audit DB

> Copy everything below this line and paste it as the first message to a new Claude Code session
> pointed at the `team6/actions` directory.

---

You are the Actions Platform engineer. Your job is to build the safe, auditable remediation layer — turning DHS health decisions into controlled operations that engineers can trigger or automate.

## Start Here

1. Read `CLAUDE.md` — your operating instructions, what you own, what you don't, deployment flow
2. Read `documentation/progress/ARCHITECTURE_DESIRED.md` — the target specification
3. Read `documentation/sprint/ROADMAP.md` — sprint sequence and what's done vs remaining
4. Read `documentation/sprint/sprint1/PLAN.md` — your concrete work for this session

**The code in `apps/` IS the current architecture.** What doesn't exist isn't built yet. This is a greenfield build — nothing exists yet.

## This Sprint (Sprint 1)

Sprint 1 builds the **Actions Service Core + Audit DB**. After this sprint:

- `actions` namespace exists in k3s
- Actions Postgres running with audit table
- Actions API (FastAPI) live at `http://192.168.1.210:31000`
- `POST /actions` — execute restart/scale with RBAC + audit
- `GET /actions` — list actions with filters
- `GET /actions/{id}` — get action detail
- K8s client: restart and scale deployments via in-cluster API
- RBAC: ownership check via SSOT before executing
- Audit: every action recorded in Postgres
- Prometheus metrics at `/metrics`
- Health probe at `/health`

**This sprint does NOT include:** Kafka consumer (Sprint 2), Ops UI (Sprint 3), auto-remediation (Sprint 4).

## Dependency Status (IMPORTANT — read this)

All external dependencies for Sprint 1 are **already live and deployed**:

| Dependency | Status | Verified |
|-----------|--------|----------|
| Team 4 SSOT API (`:30900`) — entities, ownership, health_summary | **LIVE** | All 18 endpoints, 4 tables |
| Team 2 Calculator services — restart/scale targets | **LIVE** | API, Worker, Frontend running |
| Kubernetes API — in-cluster | **LIVE** | Always available |

You do NOT need to check if these are running. They are. Use them directly.

## Critical Corrections (vs PLAN.md)

The Sprint 1 PLAN.md has a few issues. Follow these corrections:

### 1. RBAC Must Fail-Closed (not default-allow)

PLAN.md Milestone 5 says: "If no ownership record → allow (no restriction) with warning log"

**THIS IS WRONG.** Per `documentation/contracts/RBAC_POLICY.md` line 92:
> "If SSOT has no ownership record for an entity, the action is **denied** (fail closed)."

In `rbac.py`, when `get_ownership()` returns None:
```python
# CORRECT — fail closed
if ownership is None:
    return (False, f"No ownership record for entity {entity_id} — denied")

# WRONG — do NOT do this
if ownership is None:
    return (True, "No ownership — allowing with warning")
```

### 2. Kubernetes Client Must Be Async-Wrapped

The `kubernetes` Python client (v31) is synchronous. FastAPI is async. All K8s API calls **must** be wrapped to avoid blocking the event loop:

```python
import asyncio
from kubernetes import client, config

# In-cluster auth
config.load_incluster_config()
apps_v1 = client.AppsV1Api()

async def restart_deployment(name: str, namespace: str) -> str:
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
    # MUST wrap sync call in to_thread
    await asyncio.to_thread(apps_v1.patch_namespaced_deployment, name, namespace, body)
    return f"Rollout restart initiated for deployment {name} in namespace {namespace}"
```

Do this for ALL `kubernetes` client calls: `patch_namespaced_deployment`, `patch_namespaced_deployment_scale`, `read_namespaced_deployment`, etc.

### 3. Entity ID Parsing

Entity IDs follow the format: `k8s:{cluster}:{namespace}:{kind}:{name}`

Example: `k8s:lab:calculator:Deployment:api`
- Split on `:` → index 0=`k8s`, 1=`lab`, 2=`calculator` (namespace), 3=`Deployment` (kind), 4=`api` (name)

Create a parser utility:
```python
def parse_entity_id(entity_id: str) -> tuple[str, str, str]:
    """Returns (namespace, kind, name). Raises ValueError if invalid."""
    parts = entity_id.split(":")
    if len(parts) != 5 or parts[0] != "k8s":
        raise ValueError(f"Invalid entity_id format: {entity_id}")
    namespace, kind, name = parts[2], parts[3], parts[4]
    if kind != "Deployment":
        raise ValueError(f"Unsupported entity kind: {kind}. Only Deployment is supported.")
    return namespace, kind, name
```

### 4. Scale to 0 — Log a Warning

`MIN_SCALE_REPLICAS=0` is intentional (allows testing DHS failure detection). But when scaling to 0, log a WARNING:
```python
if replicas == 0:
    logger.warning(f"Scaling {name} in {namespace} to 0 replicas — this will cause downtime")
```

## Tech Stack

- **Language:** Python 3.12
- **API:** FastAPI + uvicorn
- **Database:** PostgreSQL 16 (asyncpg + SQLAlchemy async)
- **K8s client:** `kubernetes==31.0.0` (sync, wrapped with `asyncio.to_thread`)
- **HTTP client:** `httpx` (async, for SSOT API calls)
- **Metrics:** `prometheus-client`
- **Port:** NodePort 31000 → container 8080

## Key Files to Create (Sprint 1)

| File | Purpose |
|------|---------|
| `k8s/namespace.yaml` | actions namespace |
| `k8s/postgres/statefulset.yaml` | Audit database |
| `k8s/postgres/service.yaml` | DB ClusterIP |
| `k8s/rbac/serviceaccount.yaml` | K8s service account for Actions |
| `k8s/rbac/clusterrole.yaml` | K8s permissions (get/list/patch deployments) |
| `k8s/rbac/clusterrolebinding.yaml` | Bind role to service account |
| `k8s/actions-api/deployment.yaml` | Actions API deployment |
| `k8s/actions-api/service.yaml` | NodePort 31000 |
| `apps/actions-api/main.py` | FastAPI application |
| `apps/actions-api/config.py` | Environment config |
| `apps/actions-api/database.py` | SQLAlchemy async engine |
| `apps/actions-api/models.py` | Action ORM model |
| `apps/actions-api/schemas.py` | Pydantic request/response |
| `apps/actions-api/k8s_client.py` | Kubernetes restart/scale (async-wrapped) |
| `apps/actions-api/ssot_client.py` | SSOT ownership lookup (httpx) |
| `apps/actions-api/rbac.py` | RBAC enforcer (fail-closed) |
| `apps/actions-api/requirements.txt` | Python deps |
| `apps/actions-api/Dockerfile` | Container image |

## What You Read (Sprint 1)

| Source | URL (in-cluster) | What |
|--------|-----------------|------|
| SSOT API | `http://ssot-api.ssot:8080` | `/ownership/{entity_id}` for RBAC, `/entities/{entity_id}` for validation |
| Kubernetes API | In-cluster (service account) | Deployment get/patch for restart and scale |

## What You Write (Sprint 1)

| Target | What |
|--------|------|
| Actions Postgres | Audit log — every action recorded |
| Kubernetes API | `patch` deployments (restart annotation + scale) |

## Machines

- **This PC (Windows):** Dev machine — write code, push to GitHub
- **Lenovo 5560 (Ubuntu 24.04):** `ssh 5560` (IP: `192.168.1.210`) — runs k3s

## Key Contracts

- `documentation/contracts/ACTION_SCHEMA.md` — your REST API spec and audit log schema
- `documentation/contracts/RBAC_POLICY.md` — authorization rules (**RBAC must fail-closed**)

## Working Convention

After each milestone: mark `[x] Done` in Sprint 1 `PLAN.md`.
After finishing the sprint: write `REVIEW.md`, update `ROADMAP.md`, commit and push.

**Warning:** Sprint 1 restart/scale tests execute real K8s actions against the calculator namespace. Always scale back to original replica count after scale tests to avoid leaving the cluster in a broken state.

## Milestone Order

Follow the PLAN.md milestones 1-9 in order:
1. Create `actions` namespace + Postgres
2. Create Actions API project structure
3. Kubernetes client (restart + scale) — **use `asyncio.to_thread` wrappers**
4. SSOT client (ownership lookup)
5. RBAC enforcer — **fail-closed when no ownership record**
6. Actions API endpoints + main.py
7. Deploy Actions API to k3s
8. Smoke test: restart + scale + audit + RBAC denial
9. Update docs + write sprint review

Begin by reading the files listed in "Start Here", then execute milestones in order.
