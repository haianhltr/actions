# Actions (Remediation & Control Plane) — Agent Instructions

## Start Here

1. Read `documentation/progress/ARCHITECTURE_DESIRED.md` — the **target specification**. This is what Actions must become.
2. Read the code (`apps/`, `k8s/`, `config/`) — this is the **current state**. The gap between code and desired architecture is your work.
3. Read `documentation/sprint/ROADMAP.md` — overall sprint sequence and what's done vs remaining.
4. Read the current sprint `documentation/sprint/sprintN/PLAN.md` — your concrete work for this session.

**There is no separate "current architecture" document. The code IS the current architecture.**

## What Actions Is

Actions is the **controlled remediation layer** that turns health decisions into safe operations. It:
- **Consumes** `health.transition` events from DHS (Kafka)
- **Exposes** remediation endpoints (restart, scale, rollback)
- **Enforces** RBAC — only authorized teams can act on their resources
- **Audits** every action (who, what, when, why, result)
- **Provides** a minimal Ops UI for health overview + one-click remediation
- **Optionally** auto-remediates safe, reversible failures (Phase 2)

**Actions does NOT derive health** (that's DHS). **Actions does NOT collect metrics** (that's Observability). **Actions does NOT model topology** (that's SSOT). Actions executes, not decides.

## What You Own

1. **Actions Service** — Python service: Kafka consumer, K8s client, REST endpoints, RBAC, audit logging
2. **Ops UI** — Minimal web UI: health overview, entity detail, action buttons, action history
3. **Audit Store** — Postgres table recording every action with result
4. **Auto-Remediation Config** — YAML-defined safe auto-actions with guardrails (Phase 2)

## Context: Other Teams

| Team | What They Provide to Actions | Actions Interface |
|------|------------------------------|-------------------|
| Team 2 (App) | Calculator services (API, Worker, Frontend) | Actions restarts/scales their deployments |
| Team 3 (Observability) | Prometheus, Grafana, event stream | Actions does not read these directly |
| Team 4 (SSOT) | Entities, relationships, ownership, health_summary | Actions **reads** entity health + ownership for UI |
| Team 5 (DHS) | `health.transition` events on Kafka | Actions **consumes** these to trigger/recommend actions |

### What Actions Reads

| Source | Endpoint | What |
|--------|----------|------|
| SSOT API | `http://ssot-api.ssot:8080` | Entity health, ownership, topology (for UI) |
| Kafka | Topic `health.transition.v1` | Transition events from DHS |
| Kubernetes API | In-cluster API | Execute restart/scale/rollback |

### What Actions Writes

| Target | Endpoint | What |
|--------|----------|------|
| Kubernetes API | In-cluster | Deployment restarts, scale changes |
| Actions Postgres | Internal | Audit log of all actions |

## Machines

- **This PC (Windows):** Dev machine — write code, push to GitHub
- **Lenovo 5560 (Ubuntu 24.04):** Server — runs k3s, all pods live here. Reach it via `ssh 5560` (IP: `192.168.1.210`)

## Deployment Flow

```
Edit code in apps/ → git push origin main → GitHub Actions builds images → ArgoCD deploys to k3s
Edit manifests in k8s/ → git push origin main → ArgoCD picks up within ~3 min
```

## Namespace Strategy

Actions resources live in the `actions` namespace.
- Actions service pod runs here
- Actions Postgres runs here (small audit DB)
- Ops UI pod runs here

## Working Convention

### Before starting work
1. Read `ARCHITECTURE_DESIRED.md` to know what the platform should look like
2. Read the current sprint `PLAN.md` — milestones are ordered and self-contained
3. Read the relevant source code to understand what exists today

### While working (after each milestone)
1. **Sprint PLAN.md** — mark milestone status as `[x] Done`
2. **Update ARCHITECTURE_DESIRED.md** ONLY if the goal itself changes (rare)

### After finishing a sprint
1. Write `documentation/sprint/sprintN/REVIEW.md`
2. Update `ROADMAP.md` — mark sprint as complete
3. Update contract docs if applicable
4. Commit and push

### Sprint directory structure
```
documentation/sprint/sprintN/
├── PLAN.md     ← written BEFORE the sprint
└── REVIEW.md   ← written AFTER the sprint
```

### REVIEW.md template
```markdown
# Sprint N Review — <Title>

**Sprint:** N
**Duration:** <date or date range>
**Status:** Complete

## Objective
## What We Shipped
## Key Metrics
## Incidents & Fixes During Rollout
## Architecture Before & After
## Design Decisions
## What We Didn't Do (and why)
## Completion Checklist
## What's Next
```

## Testing

Every sprint must ship with automated E2E tests following Team 2's pattern.

### Test structure
```
tests/
├── requirements.txt          # pytest, httpx, pytest-timeout
└── e2e/
    ├── conftest.py           # shared fixtures: client, ssot_client
    ├── test_actions_api.py       # Sprint 1 — restart, scale, RBAC denial, audit log
    ├── test_recommendations.py   # Sprint 2 — Kafka events → recommendations
    ├── test_ops_ui.py            # Sprint 3 — UI pages load, action buttons work
    └── test_auto_remediation.py  # Sprint 4 — auto-actions triggered, rate limited
```

### Running tests
```bash
# Install test deps:
pip install -r tests/requirements.txt

# All tests against k3s (default):
pytest tests/e2e/ -v

# Only Sprint 1 tests:
pytest tests/e2e/ -m sprint1 -v

# Against local:
ACTIONS_API_URL=http://localhost:8080 pytest tests/e2e/ -v
```

### Convention
- **One test file per sprint feature area**
- **File-level `pytestmark = pytest.mark.sprintN`**
- **Caution: Sprint 1 restart/scale tests execute real K8s actions** — they restart and scale the calculator API deployment. The test suite scales back to 1 replica after scale tests.
- **After deploying, always run the sprint's tests** to verify

## Quick Reference

```bash
ssh 5560 "sudo kubectl get pods -n actions"                                # check Actions pods
ssh 5560 "sudo kubectl logs -n actions deploy/actions-api --tail=20"       # Actions logs
ssh 5560 "curl -s http://192.168.1.210:30900/health_summary?state=UNHEALTHY"  # check SSOT health
ssh 5560 "curl -s http://192.168.1.210:31000/actions?limit=10"            # recent actions
```

## Ports on 5560 (192.168.1.210)

| Port | Service | Namespace |
|------|---------|-----------|
| 31000 | Actions API | actions |
| 31080 | Ops UI | actions |
| 30950 | DHS API | dhs |
| 30900 | SSOT API | ssot |
| 30800 | Calculator API | calculator |
| 30090 | Prometheus | observability |
| 30300 | Grafana | observability |
| 30443 | ArgoCD UI | argocd |
