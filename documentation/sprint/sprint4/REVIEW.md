# Sprint 4 Review — RBAC + Guardrails + Auto-Remediation

**Date:** 2026-03-05
**Status:** Complete
**API Version:** 0.4.0

---

## What Was Delivered

### 1. Full RBAC from config/rbac.yaml

- Replaced Sprint 1 hardcoded RBAC stub with config-driven enforcer
- User → team lookup from `config/rbac.yaml` team_mappings
- `platform-admin` role: can act on any entity (sre@team.com)
- `team-member` role: can act on entities owned by their team (engineer@team.com → app-team)
- `auto-remediation` user: treated as platform-admin (RBAC bypass)
- **Fail-closed**: user not in config → 403, no ownership record in SSOT → 403
- Tier-1 warning logged (approval not enforced in MVP)
- ConfigMap mounted at `/app/config/` via Kubernetes volume

### 2. Auto-Remediation Engine

- `AutoRemediationEngine` loads rules from `config/auto-remediation.yaml`
- Rule matching: `new_state` + `entity_type` (from root cause) + `reason_contains`
- Currently 1 enabled rule: `restart_on_crashloop` (UNHEALTHY + CrashLoopBackOff → restart)
- 1 disabled rule: `scale_on_lag` (DEGRADED + Consumer lag → scale up)
- All auto-actions logged with `user_id: "auto-remediation"`, `user_team: "platform-team"`
- Hooked into Kafka consumer: runs after storing recommendation

### 3. Guardrails

- **Rate limiting**: max N auto-actions per hour per entity (DB-backed count)
- **Cooldown**: no repeat auto-action within cooldown period (DB query)
- **Escalation**: stop auto-remediating after 3 consecutive failures (in-memory counter, resets on pod restart)
- All guardrail blocks logged and counted via Prometheus metrics

### 4. Phase 2 Actions

- `pause_rollout`: patches deployment with `spec.paused: true`
- `resume_rollout`: patches deployment with `spec.paused: false`
- Both use Kubernetes Python client `patch_namespaced_deployment` (no kubectl binary needed)
- `rollback_deployment` deferred (requires kubectl binary in container)

### 5. ConfigMap

- `k8s/actions-api/configmap.yaml` with both `rbac.yaml` and `auto-remediation.yaml`
- Mounted read-only at `/app/config/` in the actions-api pod
- Config changes require ConfigMap update + pod restart

---

## Test Results

**37/37 E2E tests passing** (all sprints combined):
- Sprint 1: 10 tests (API, restart, scale, RBAC)
- Sprint 2: 8 tests (recommendations, correlation, metrics)
- Sprint 3: 10 tests (static files, proxy endpoints)
- Sprint 4: 9 tests (RBAC enforcement, pause/resume, auto-remediation audit)

Sprint 4 tests cover:
- `test_authorized_team_member_allowed` — engineer@team.com → 200
- `test_unknown_user_denied` — nobody@unknown.com → 403
- `test_platform_admin_allowed_on_any_entity` — sre@team.com → 200
- `test_fail_closed_no_ownership` — unknown entity → 403/404
- `test_pause_rollout` — pause succeeds
- `test_resume_rollout` — resume succeeds
- `test_auto_remediation_metrics_exist` — Prometheus metrics registered
- `test_auto_remediation_actions_queryable` — filter by user=auto-remediation works
- `test_rbac_denied_metric` — denial counter exists

---

## Smoke Test Results

| Test | Result |
|------|--------|
| Config mounted at /app/config/ | Pass (rbac.yaml + auto-remediation.yaml) |
| RBAC config loaded (2 teams, 2 roles) | Pass |
| Auto-remediation loaded (2 rules, 1 enabled) | Pass |
| Authorized team member → 200 | Pass |
| Unknown user → 403 | Pass |
| Platform admin → 200 | Pass |
| Pause rollout → success | Pass |
| Resume rollout → success | Pass |
| RBAC denied metric incremented | Pass |
| Auto-remediation metrics registered | Pass |

---

## Design Decisions

| Decision | Rationale |
|----------|-----------|
| Config via ConfigMap (not baked in image) | Can update config without rebuilding Docker image |
| RBAC fail-closed (no ownership = deny) | Security-first for a remediation service |
| Auto-remediation user = "auto-remediation" | Clear audit trail, easy to filter |
| Guardrails: rate limit + cooldown via DB | Accurate across pod restarts |
| Escalation counter: in-memory | Resets on restart = conservative safety net |
| Skip rollback_deployment | Requires kubectl binary; pause/resume sufficient for MVP |
| Tier-1 warning only | Approval workflow deferred to Phase 2 |

---

## Breaking Changes

- **RBAC signature changed**: `check_permission()` no longer accepts `user_team` from HTTP header. Team is looked up from config. Sprint 1 test users updated from `pytest@team.com` to `engineer@team.com`.
- **`X-User-Team` header no longer used**: user_team in audit is resolved from RBAC config, not from the request header.

---

## What's Next (Sprint 5)

- Full end-to-end test: DHS → Actions → K8s → Recovery
- Worker crash → restart via UI → recovery confirmed
- Scale to 0 → scale up via UI → recovery confirmed
- RBAC test → unauthorized user denied
- CI/CD pipeline, ArgoCD Application
- Contract docs (ACTIONS_CONTRACT.md)
