# Sprint Roadmap — Actions (Remediation & Control Plane)

**Goal:** Controlled remediation layer that consumes DHS health decisions and enables safe, auditable, RBAC-enforced operations against the platform.

**Source of truth for target state:** `documentation/progress/ARCHITECTURE_DESIRED.md`
**Source of truth for current state:** the code itself (`apps/`, `k8s/`, `config/`)

---

## Current State

Sprint 1 complete. Actions API running at `:31000` with restart/scale actions, RBAC, and audit logging.

---

## Sprint Sequence

```
Sprint 1  ✅ Actions Service Core + Audit DB
    │         actions namespace, Postgres for audit
    │         K8s client (restart, scale deployments)
    │         REST API: POST /actions, GET /actions
    │         Audit logging (every action recorded)
    │         RBAC stub (team-based ownership check via SSOT)
    │         Deploy to k3s, verify restart/scale work
    │
    ▼
Sprint 2     Kafka Consumer + Recommendations
    │         Consume health.transition.v1 events
    │         Store pending recommendations
    │         GET /recommendations endpoint
    │         Correlation: link actions to triggering events
    │
    ▼
Sprint 3     Ops UI (Health Overview + Actions)
    │         Health overview page (entities, state, owner)
    │         Entity detail page (health, root cause, actions)
    │         Action buttons with confirmation dialog
    │         Action history display
    │         Static files served via Nginx
    │
    ▼
Sprint 4     RBAC + Guardrails + Auto-Remediation
    │         Full RBAC from config/rbac.yaml
    │         Tier-based restrictions
    │         Auto-remediation config (safe auto-restart)
    │         Rate limiting and cooldown
    │         Escalation on repeated failures
    │
    ▼
Sprint 5     Integration + Failure Validation
               Full end-to-end test: DHS → Actions → K8s → Recovery
               Worker crash → restart via UI → recovery confirmed
               Scale test → scale via UI → recovery confirmed
               RBAC test → unauthorized user denied
               CI/CD pipeline, ArgoCD Application
               Contract docs (ACTIONS_CONTRACT.md)
```

---

## Dependencies

| Sprint | Hard Dependencies | Why |
|--------|-------------------|-----|
| 1 (Service Core) | **Team 4 Sprint 1** (SSOT API for ownership lookup) | RBAC needs ownership data |
| 2 (Kafka Consumer) | Sprint 1, **Team 5 Sprint 3** (health.transition events on Kafka) | Must have events to consume |
| 3 (Ops UI) | Sprint 1, **Team 4 Sprint 3** (health_summary + ownership in SSOT) | UI reads health + ownership |
| 4 (RBAC + Auto-Remediation) | Sprints 1-3 | Full stack must exist |
| 5 (Integration) | Sprints 1-4, all teams operational | End-to-end validation |

---

## Dependencies on Other Teams

| What Actions Needs | Team | Status |
|--------------------|------|--------|
| SSOT API with entities, ownership, health_summary | Team 4 Sprints 1+3 | Live |
| health.transition events on Kafka topic | Team 5 Sprint 3 | Live |
| Calculator services running for remediation targets | Team 2 | Live |
| Prometheus scraping Actions metrics | Team 3 | Future |
| DHS writing health states to SSOT | Team 5 Sprint 1 | Live |

---

## What Each Sprint Unlocks

| After Sprint | Platform Can... |
|--------------|-----------------|
| 1 | Execute restart/scale actions via API with audit trail |
| 2 | Receive health event recommendations, link actions to root cause |
| 3 | Engineers use a UI instead of kubectl for remediation |
| 4 | Enforce authorization, auto-remediate safe failures |
| 5 | Full closed-loop: detect → decide → execute → recover |

---

## Definition of Done Mapping

| Criterion | Sprint |
|-----------|--------|
| health.transition events consumed | Sprint 2 |
| UI displays entity health + root cause | Sprint 3 |
| Restart and scale actions work | Sprint 1 |
| Audit logs record all actions | Sprint 1 |
| RBAC prevents unauthorized actions | Sprint 4 (stub in Sprint 1) |
| Worker crash → restart works | Sprint 5 (validated) |
| No dangerous actions possible | Sprint 4 |
