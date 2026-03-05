# Sprint 3 Review — Ops UI (Health Overview + Actions)

**Date:** 2026-03-05
**Status:** Complete
**Deployed at:** `http://192.168.1.210:31080`

---

## What Was Delivered

### Ops UI — Nginx-based ops console with two pages

1. **Health Overview page** (`index.html`)
   - Table of all entities with health state, type, root cause, owner, last transition
   - Color-coded health states (green/yellow/red/gray)
   - Filter dropdowns for state, type, and team (populated from data)
   - Recommendation badge `[!]` on entities with pending recommendations
   - Auto-refresh every 30s with "Last updated" timestamp

2. **Entity Detail page** (`entity.html`)
   - Entity metadata (ID, name, type, namespace, cluster, owner, tier, contact)
   - Health state with confidence percentage
   - Root cause display (self or linked to another entity)
   - Recommendation section (shown only when recommendation exists)
   - Action buttons: Restart Deployment, Scale Deployment (with replicas input)
   - Confirmation dialog with reason field and user email
   - Action result display (green success / red failure)
   - Action history table from `GET /actions?entity_id=X`

3. **Nginx reverse proxy**
   - `/proxy/actions/` → `http://actions-api:8080/` (same namespace)
   - `/proxy/ssot/` → `http://ssot-api.ssot.svc.cluster.local:8080/` (cross-namespace FQDN)
   - Eliminates all CORS issues — all browser requests go to same origin

4. **Kubernetes deployment**
   - Deployment: 1 replica, `ghcr.io/haianhltr/actions/ops-ui:latest`
   - Service: NodePort 31080
   - Readiness/liveness probes on port 80
   - Resource limits: 50m-100m CPU, 64Mi-128Mi memory

5. **CI pipeline**
   - Added `build-ops-ui` job to GitHub Actions workflow
   - Builds and pushes `ghcr.io/haianhltr/actions/ops-ui:latest` on push to main

---

## Test Results

**28/28 E2E tests passing** (all sprints combined):
- Sprint 1: 10 tests (API, restart, scale, RBAC)
- Sprint 2: 8 tests (recommendations, correlation, metrics)
- Sprint 3: 10 tests (static files, proxy endpoints)

Sprint 3 tests cover:
- `test_index_page_loads` — index returns 200 with "Health Overview"
- `test_entity_page_loads` — entity.html returns 200 with "Entity Detail"
- `test_static_asset` (4 parametrized) — CSS and JS files all return 200
- `test_proxy_actions_api` — health check through proxy
- `test_proxy_actions_list` — actions list through proxy returns list
- `test_proxy_ssot_entities` — SSOT entities through proxy
- `test_proxy_recommendations` — recommendations through proxy returns list

---

## Smoke Test Results

| Test | Result |
|------|--------|
| Index page loads (200) | Pass |
| Entity page loads (200) | Pass |
| All static assets (200) | Pass |
| Proxy → Actions API health | Pass (`{"status":"ok"}`) |
| Proxy → SSOT entities | Pass (full entity list returned) |
| Proxy → Recommendations | Pass (`[]` — expected, steady state) |
| Proxy → Actions list | Pass (previous sprint actions returned) |

---

## Architecture

```
Browser → :31080 (Nginx)
    ├── / → index.html (static)
    ├── /entity.html → entity.html (static)
    ├── /css/, /js/ → static assets
    ├── /proxy/actions/* → actions-api:8080/* (same namespace)
    └── /proxy/ssot/* → ssot-api.ssot.svc:8080/* (cross-namespace)
```

---

## Design Decisions

| Decision | Rationale |
|----------|-----------|
| Vanilla HTML/CSS/JS | No build step, no npm. 2 pages don't need a framework. |
| Nginx reverse proxy | Eliminates CORS. Single origin for all requests. |
| Dark theme | Standard for ops consoles. Matches Grafana/Prometheus aesthetic. |
| 30s polling | Health data changes on minute timescales. Simple and reliable. |
| Separate pod | Independent lifecycle from API. Can update UI without restarting API. |
| URL query params (`?id=`) | No client-side router needed. Bookmarkable entity URLs. |

---

## Image Path Correction

The PLAN.md referenced `ghcr.io/haianhltr/ops-ui:latest` but the correct path per the CI repo pattern is `ghcr.io/haianhltr/actions/ops-ui:latest`. The deployment manifest was created with the correct path.

---

## What's Next (Sprint 4)

- Full RBAC from `config/rbac.yaml`
- Tier-based restrictions
- Auto-remediation config (safe auto-restart)
- Rate limiting and cooldown
- Escalation on repeated failures
