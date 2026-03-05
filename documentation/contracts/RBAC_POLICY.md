# Contract: RBAC Policy

**Owner:** team6 (Actions)
**Consumers:** team4 (SSOT ownership records must align with these roles), engineers, platform team
**Config file:** `config/rbac.yaml`

---

## Roles

| Role | Who Has It | What They Can Do |
|------|-----------|-----------------|
| `platform-admin` | SRE / platform team members | Act on any entity in any namespace |
| `team-member` | Any engineer | Act on entities owned by their team |

---

## Authorization Flow

Before any action executes, Actions API validates:

```
1. Is the user authenticated? (identity from request header or session)
2. What is the user's team? (from config/rbac.yaml team_mappings)
3. Does the target entity exist in SSOT?
4. Who owns the target entity? (GET /ownership/{entity_id} from SSOT)
5. Does the user's team match the owner team? OR is the user a platform-admin?
6. If tier-1: does this require approval? (future — Phase 2)
7. If all checks pass: execute action and record audit log
8. If any check fails: return 403 Forbidden
```

---

## Tier Restrictions

| Tier | Description | Approval Required |
|------|-------------|-----------------|
| `tier-1` | Critical services — outage = immediate revenue impact | Yes (Phase 2) |
| `tier-2` | Important services — degradation affects users | No |
| `tier-3` | Internal / background services | No |

In MVP (Sprint 1): approval workflow is not implemented. Tier-1 services are treated the same as tier-2 (no approval gate). This will change in Phase 2.

---

## RBAC Config Format

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
    requires_approval: true    # enforced in Phase 2
  tier-2:
    requires_approval: false
  tier-3:
    requires_approval: false
```

---

## Entity Ownership Source

Ownership data comes from SSOT: `GET /ownership/{entity_id}`

| Field | Used For |
|-------|----------|
| `team` | Match against user's team from `team_mappings` |
| `tier` | Determine if approval is required |

If SSOT has no ownership record for an entity, the action is **denied** (fail closed).

---

## Auto-Remediation Identity

All auto-remediation actions run with user identity `"auto-remediation"` and are recorded in the audit log with this identity. The auto-remediation system is treated as a `platform-admin` for authorization purposes.

---

## Kubernetes RBAC (Service Account)

The Actions service account has the minimum K8s permissions needed:

```yaml
ClusterRole: actions-role
Rules:
  - apiGroups: ["apps"]
    resources: ["deployments"]
    verbs: ["get", "list", "patch"]       # patch for restart annotation + scale
  - apiGroups: ["apps"]
    resources: ["deployments/scale"]
    verbs: ["get", "patch"]
  - apiGroups: [""]
    resources: ["pods"]
    verbs: ["get", "list"]               # check pod status after action
  - apiGroups: ["apps"]
    resources: ["replicasets"]
    verbs: ["get", "list"]               # for rollback history (Phase 2)
  - apiGroups: ["platform.lab.io"]
    resources: ["actionrequests"]
    verbs: ["create", "get", "list"]     # Phase 2 — create ActionRequest CRs
```

---

## Audit Requirements

Every action — whether allowed or denied — must be logged:

| Event | What is logged |
|-------|---------------|
| Action allowed + executed | Full audit record in Postgres `actions` table |
| Action denied (RBAC) | Log entry with `status=denied`, user, entity_id, reason |
| Auto-remediation action | Same as manual, but `user_id="auto-remediation"` |

Audit logs must never be deleted. Retention: indefinite (small table — 1Gi storage is sufficient).
