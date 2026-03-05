# Sprint 1 Review — Actions Service Core + Audit DB

**Sprint:** 1
**Duration:** 2026-03-05
**Status:** Complete

## Objective

Stand up the Actions service from scratch: namespace, Postgres, FastAPI API with restart/scale actions, RBAC enforcement, and audit logging — deployed and verified on k3s.

## What We Shipped

- **`actions` namespace** in k3s with Postgres StatefulSet (1Gi PVC) and ClusterIP service
- **Actions API** (FastAPI, Python 3.12) deployed as a Deployment with NodePort 31000
  - `POST /actions` — execute restart or scale actions against Deployments
  - `GET /actions` — list actions with filters (entity_id, user, status, action_type, limit, offset)
  - `GET /actions/{id}` — action detail
  - `GET /health` — readiness/liveness probe
  - `GET /metrics` — Prometheus metrics
  - `GET /` — service info with uptime and action count
- **K8s client** using `kubernetes` Python client with all calls wrapped in `asyncio.to_thread()`
  - `restart_deployment` — rolling restart via annotation patch
  - `scale_deployment` — replica count patch with min/max bounds
- **SSOT client** — async HTTP client querying SSOT API for entity, ownership, and health_summary
- **RBAC enforcer** — fail-closed: denies actions when no ownership record exists. Team-based ownership check via SSOT. Platform-admin bypass.
- **Audit logging** — every action recorded in Postgres with who/what/when/why/result
- **Prometheus metrics** — `actions_executed_total`, `actions_rbac_denied_total`, `actions_execution_duration_seconds`, `actions_api_requests_total`, `actions_api_request_duration_seconds`
- **Structured JSON logging** via `python-json-logger`
- **K8s RBAC** — ServiceAccount (`actions-sa`), ClusterRole, ClusterRoleBinding with minimal permissions
- **CI pipeline** — GitHub Actions workflow building and pushing to `ghcr.io/haianhltr/actions/actions-api:latest`
- **E2E tests** — 10/10 passing (restart, scale, audit trail, RBAC denial, health, metrics)

## Key Metrics

- 10/10 E2E tests passing
- Restart action executes in ~9ms
- Scale action executes in ~8ms
- API response time < 100ms for all endpoints

## Incidents & Fixes During Rollout

| Issue | Resolution |
|-------|------------|
| `sudo kubectl` requires password via SSH | Switched to `kubectl` without sudo (user has k3s access) |
| SSOT ownership records only existed for Service entities, not Deployments | Registered Deployment ownership via `PUT /ownership` for calculator api, worker, frontend |
| Scale action reverted by ArgoCD | Expected behavior — ArgoCD manages calculator Deployment replicas. K8s API call succeeds, ArgoCD syncs back. Not a bug. |

## Architecture Before & After

**Before:** Nothing. No namespace, no pods, no code.

**After:**
```
actions namespace
├── postgres-0 (StatefulSet, 1Gi PVC)
├── actions-api (Deployment, 1 replica)
│   ├── FastAPI on :8080
│   ├── K8s client (restart, scale)
│   ├── SSOT client (entity, ownership)
│   ├── RBAC enforcer (fail-closed)
│   └── Audit writer (Postgres)
└── Services
    ├── postgres (ClusterIP :5432)
    └── actions-api (NodePort :31000)
```

## Design Decisions

| Decision | Rationale |
|----------|-----------|
| `asyncio.to_thread()` for all K8s calls | kubernetes Python client is synchronous; wrapping prevents event loop blocking |
| Fail-closed RBAC | Unknown entities must not be modifiable (per RBAC_POLICY.md contract) |
| Header-based auth (`X-User-Team`) | Simple MVP; replaceable with OIDC later |
| Annotation patch for restart | Rolling restart, no downtime, standard kubectl pattern |
| Separate Postgres (not shared with SSOT) | Independent lifecycle, simple audit schema, no coupling |

## What We Didn't Do (and why)

| Skipped | Reason |
|---------|--------|
| Kafka consumer | Sprint 2 scope |
| Ops UI | Sprint 3 scope |
| Auto-remediation | Sprint 4 scope |
| OIDC/proper auth | MVP uses header-based team identity |
| ArgoCD Application for Actions | Will add in Sprint 5 |

## Completion Checklist

- [x] `actions` namespace created
- [x] Postgres running with audit table
- [x] Actions API deployed and accessible at `:31000`
- [x] `POST /actions` executes restart and scale
- [x] `GET /actions` lists with filters
- [x] `GET /actions/{id}` returns detail
- [x] RBAC enforces ownership (fail-closed)
- [x] Audit log records every action
- [x] Prometheus metrics exposed
- [x] Health probe working
- [x] Structured JSON logging
- [x] K8s RBAC (ServiceAccount + ClusterRole)
- [x] CI pipeline builds and pushes image
- [x] E2E tests passing (10/10)

## What's Next

Sprint 2: Kafka consumer for `health.transition.v1` events, recommendations table, `GET /recommendations` endpoint, action-to-event correlation via `correlation_id`.
