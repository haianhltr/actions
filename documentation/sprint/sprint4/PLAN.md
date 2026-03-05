# Sprint 4 — RBAC + Guardrails + Auto-Remediation

**Goal:** Enforce full RBAC from `config/rbac.yaml` (fail-closed), implement auto-remediation that matches health events against `config/auto-remediation.yaml` rules, and add guardrails (rate limiting, cooldown, escalation) to prevent runaway automation.

**Status:** Not Started
**Depends on:** Sprints 1-3 complete

---

## Pre-Sprint State

- Actions API running at `http://192.168.1.210:31000` with:
  - `POST /actions` — execute restart/scale with RBAC stub + audit
  - `GET /actions`, `GET /actions/{id}` — action listing + detail
  - `GET /recommendations` — pending recommendations from Kafka events
  - Kafka consumer processing `health.transition.v1` events
  - Correlation: actions linked to triggering events
  - **RBAC stub**: checks SSOT ownership but does NOT load from `config/rbac.yaml`, does NOT fail-closed
- Ops UI running at `http://192.168.1.210:31080` with health overview + entity detail + action buttons
- Config files exist but are NOT loaded by the application:
  - `config/rbac.yaml` — team mappings, roles, tier restrictions
  - `config/auto-remediation.yaml` — auto-action rules (all disabled)

## Post-Sprint State

- **Full RBAC enforced** from `config/rbac.yaml`:
  - User → team lookup from config file (`team_mappings`)
  - `platform-admin` role: can act on any entity in any namespace
  - `team-member` role: can only act on entities owned by their team
  - **Fail-closed**: no ownership record in SSOT = deny (403)
  - Tier-1 actions: log warning (approval enforcement deferred to Phase 2)
- **Auto-remediation engine**:
  - Matches health transition events against rules in `config/auto-remediation.yaml`
  - Executes safe actions automatically with guardrails
  - All auto-actions logged with `user: "auto-remediation"`, treated as `platform-admin`
- **Guardrails**:
  - Rate limit: max N auto-actions per hour per entity (configurable per rule)
  - Cooldown: no repeat auto-action within cooldown period
  - Escalation: stop auto-remediating if entity stays UNHEALTHY after N failures
- **Optional Phase 2 actions**: `rollback_deployment`, `pause_rollout` (if straightforward)
- New Prometheus metrics: `actions_auto_remediation_total`, `actions_auto_remediation_blocked_total`

---

## Milestones

### Milestone 1 — Refactor RBAC to load from config/rbac.yaml (fail-closed)

**Status:** [ ] Not Started

Replace the Sprint 1 RBAC stub with a full enforcer that loads team mappings and roles from `config/rbac.yaml`.

**Critical correction from Sprint 1:** The stub allowed actions when no ownership record existed ("fail-open"). This sprint changes to **fail-closed** — no ownership record = deny (403).

**`apps/actions-api/rbac.py`** — full rewrite:
```python
import yaml
import logging

logger = logging.getLogger(__name__)

# Prometheus metric (defined in metrics module)
# RBAC_DENIED = Counter("actions_rbac_denied_total", "RBAC denials")


class RBACEnforcer:
    """
    RBAC enforcer that loads team mappings and roles from config/rbac.yaml.

    Authorization rules:
    1. "auto-remediation" user → treated as platform-admin → ALLOW
    2. User in platform-admin team → ALLOW on any entity
    3. User not found in any team → DENY
    4. No ownership record in SSOT for entity → DENY (fail-closed)
    5. User's team matches entity owner team → ALLOW
    6. User's team does NOT match → DENY
    7. Tier-1 entities → log warning (approval not enforced in MVP)
    """

    def __init__(self, config_path: str = "/app/config/rbac.yaml"):
        with open(config_path) as f:
            self.config = yaml.safe_load(f)
        self.team_mappings = self.config.get("team_mappings", {})
        self.roles = self.config.get("roles", {})
        self.tier_restrictions = self.config.get("tier_restrictions", {})
        logger.info(
            "RBAC config loaded: %d teams, %d roles",
            len(self.team_mappings), len(self.roles),
        )

    def get_user_team(self, user: str) -> str | None:
        """Look up user's team from config/rbac.yaml team_mappings."""
        for team_name, team_config in self.team_mappings.items():
            if user in team_config.get("members", []):
                return team_name
        return None

    def is_platform_admin(self, user: str) -> bool:
        """Check if user has platform-admin role."""
        # Auto-remediation is always treated as platform-admin
        if user == "auto-remediation":
            return True
        for team_name, team_config in self.team_mappings.items():
            if (
                user in team_config.get("members", [])
                and team_config.get("role") == "platform-admin"
            ):
                return True
        return False

    async def check_permission(
        self, user: str, entity_id: str, action_type: str, ssot_client
    ) -> tuple[bool, str]:
        """
        Check if user is authorized to perform action on entity.
        Returns (allowed: bool, reason: str).

        FAIL CLOSED: no ownership record = deny.
        """
        # 1. Platform admins can act on anything
        if self.is_platform_admin(user):
            logger.info("RBAC ALLOW: user=%s is platform-admin", user)
            return True, "platform-admin"

        # 2. Look up user's team from config
        user_team = self.get_user_team(user)
        if not user_team:
            logger.warning("RBAC DENY: user=%s not found in any team", user)
            # RBAC_DENIED.inc()
            return False, f"User {user} not found in RBAC config"

        # 3. Get entity ownership from SSOT
        ownership = await ssot_client.get_ownership(entity_id)

        # 4. FAIL CLOSED: no ownership record = deny
        if not ownership:
            logger.warning(
                "RBAC DENY: no ownership record for entity=%s (fail-closed)",
                entity_id,
            )
            # RBAC_DENIED.inc()
            return False, (
                f"No ownership record for entity {entity_id} — "
                f"access denied (fail-closed)"
            )

        owner_team = ownership.get("team")

        # 5. Check team ownership match
        if user_team != owner_team:
            logger.warning(
                "RBAC DENY: user=%s team=%s, entity owner=%s",
                user, user_team, owner_team,
            )
            # RBAC_DENIED.inc()
            return False, (
                f"User {user} (team={user_team}) does not own "
                f"entity {entity_id} (owner={owner_team})"
            )

        # 6. Check tier restrictions
        tier = ownership.get("tier", "tier-3")
        tier_config = self.tier_restrictions.get(tier, {})
        if tier_config.get("requires_approval", False):
            # MVP: log warning but allow. Phase 2: enforce approval gate.
            logger.warning(
                "RBAC WARN: tier-1 action on entity=%s by user=%s — "
                "approval required (not enforced in MVP)",
                entity_id, user,
            )

        logger.info(
            "RBAC ALLOW: user=%s team=%s, entity=%s owner=%s",
            user, user_team, entity_id, owner_team,
        )
        return True, f"team-member ({user_team})"
```

**`apps/actions-api/requirements.txt`** — add:
```
pyyaml==6.0.2
```

**Files to modify:**
- `apps/actions-api/rbac.py` (full rewrite)
- `apps/actions-api/requirements.txt` (add pyyaml)

---

### Milestone 2 — Mount config files via ConfigMap

**Status:** [ ] Not Started

Mount `config/rbac.yaml` and `config/auto-remediation.yaml` into the Actions API pod via a Kubernetes ConfigMap. This allows config changes without rebuilding the Docker image.

**`k8s/actions-api/configmap.yaml`:**
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: actions-config
  namespace: actions
  labels:
    app: actions-api
    team: team6
data:
  rbac.yaml: |
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
  auto-remediation.yaml: |
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

> **Note:** `restart_on_crashloop` is set to `enabled: true` in the ConfigMap (was `false` in the repo config file). This activates auto-remediation for CrashLoopBackOff in the deployed environment.

**`k8s/actions-api/deployment.yaml`** — add volume mount:
```yaml
spec:
  template:
    spec:
      containers:
        - name: actions-api
          # ... existing config ...
          volumeMounts:
            - name: actions-config
              mountPath: /app/config
              readOnly: true
      volumes:
        - name: actions-config
          configMap:
            name: actions-config
```

**Files to create:**
- `k8s/actions-api/configmap.yaml`

**Files to modify:**
- `k8s/actions-api/deployment.yaml` (add volumeMounts + volumes)

**Verification:**
```bash
# Apply ConfigMap
ssh 5560 "sudo kubectl apply -f k8s/actions-api/configmap.yaml"

# Verify ConfigMap exists
ssh 5560 "sudo kubectl get configmap actions-config -n actions -o yaml"

# After deploying updated pod, verify config is mounted
ssh 5560 "sudo kubectl exec deploy/actions-api -n actions -- cat /app/config/rbac.yaml"
ssh 5560 "sudo kubectl exec deploy/actions-api -n actions -- cat /app/config/auto-remediation.yaml"
```

---

### Milestone 3 — Auto-remediation engine

**Status:** [ ] Not Started

**`apps/actions-api/auto_remediation.py`:**
```python
import yaml
import logging

logger = logging.getLogger(__name__)

# Prometheus metrics (defined in metrics module)
# AUTO_REMEDIATION_TOTAL = Counter(
#     "actions_auto_remediation_total", "Auto-remediation actions",
#     ["action_name", "status"],
# )
# AUTO_REMEDIATION_BLOCKED = Counter(
#     "actions_auto_remediation_blocked_total", "Auto-remediation blocked by guardrails",
# )


class AutoRemediationEngine:
    """
    Matches health.transition events against rules in config/auto-remediation.yaml.
    Executes safe actions automatically with guardrails.
    All auto-actions logged with user="auto-remediation".
    """

    def __init__(self, config_path: str = "/app/config/auto-remediation.yaml"):
        with open(config_path) as f:
            self.config = yaml.safe_load(f)
        self.rules = self.config.get("auto_actions", [])
        self.enabled_rules = [r for r in self.rules if r.get("enabled", False)]
        logger.info(
            "Auto-remediation loaded: %d rules (%d enabled)",
            len(self.rules), len(self.enabled_rules),
        )

    def match_rule(self, event: dict) -> dict | None:
        """
        Find the first matching auto-remediation rule for a health event.

        Matching logic:
        - trigger.new_state must match event.new_state
        - trigger.entity_type matches the KIND of the root_cause_entity_id
          (parsed from k8s:{cluster}:{namespace}:{kind}:{name})
        - trigger.reason_contains must be a substring of event.reason
        """
        new_state = event.get("new_state")
        reason = event.get("reason", "")

        # Determine target entity kind from root cause (or entity itself)
        target_id = event.get("root_cause_entity_id") or event.get("entity_id", "")
        parts = target_id.split(":")
        target_kind = parts[3] if len(parts) == 5 else ""

        for rule in self.enabled_rules:
            trigger = rule.get("trigger", {})

            if trigger.get("new_state") != new_state:
                continue
            if trigger.get("entity_type") and trigger["entity_type"] != target_kind:
                continue
            if trigger.get("reason_contains") and trigger["reason_contains"] not in reason:
                continue

            return rule

        return None

    async def maybe_auto_remediate(
        self, event: dict, guardrails, action_executor,
    ):
        """
        Check if event matches auto-remediation rules and execute if guardrails allow.

        Args:
            event: health.transition.v1 event dict
            guardrails: Guardrails instance for rate limit/cooldown/escalation checks
            action_executor: async callable to execute the action
        """
        rule = self.match_rule(event)
        if not rule:
            return

        target_id = event.get("root_cause_entity_id") or event["entity_id"]
        action_type = rule["action"]["type"]
        rule_name = rule["name"]

        logger.info(
            "Auto-remediation rule matched: %s for entity=%s",
            rule_name, target_id,
        )

        # Check guardrails before executing
        allowed, reason = await guardrails.check(
            entity_id=target_id,
            action_type=action_type,
            max_per_hour=rule["action"].get("max_per_hour", 2),
            cooldown_minutes=rule["action"].get("cooldown_minutes", 30),
        )
        if not allowed:
            logger.warning(
                "Auto-remediation BLOCKED by guardrails: rule=%s, entity=%s — %s",
                rule_name, target_id, reason,
            )
            # AUTO_REMEDIATION_BLOCKED.inc()
            return

        # Build action parameters
        parameters = dict(rule["action"].get("parameters", {}))

        # For scale_deployment with replicas_add: resolve to absolute replicas count
        # (The action executor will need to read current replicas and add)

        logger.info(
            "Auto-remediation EXECUTING: rule=%s, entity=%s, action=%s",
            rule_name, target_id, action_type,
        )

        await action_executor(
            entity_id=target_id,
            action_type=action_type,
            user="auto-remediation",
            reason=f"Auto-remediation: {rule_name} — {event.get('reason', '')}",
            parameters=parameters,
            correlation_id=event.get("event_id"),
        )

        # AUTO_REMEDIATION_TOTAL.labels(action_name=rule_name, status="executed").inc()
```

**Files to create:**
- `apps/actions-api/auto_remediation.py`

---

### Milestone 4 — Guardrails (rate limiting, cooldown, escalation)

**Status:** [ ] Not Started

**`apps/actions-api/guardrails.py`:**
```python
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, func

from database import async_session_factory
from models import Action

logger = logging.getLogger(__name__)


class Guardrails:
    """
    Safety guardrails for auto-remediation:
    1. Rate limit: max N auto-actions per hour per entity
    2. Cooldown: no repeat auto-action within cooldown_minutes
    3. Escalation: stop after N consecutive failures for an entity
    """

    def __init__(self, max_escalation_failures: int = 3):
        self._escalation_failures: dict[str, int] = {}  # entity_id → consecutive failures
        self._max_escalation_failures = max_escalation_failures

    async def check(
        self,
        entity_id: str,
        action_type: str,
        max_per_hour: int,
        cooldown_minutes: int,
    ) -> tuple[bool, str]:
        """
        Check all guardrails before auto-remediation.
        Returns (allowed: bool, reason: str).
        """
        # 1. Escalation check — stop if entity keeps failing after auto-remediation
        failure_count = self._escalation_failures.get(entity_id, 0)
        if failure_count >= self._max_escalation_failures:
            return False, (
                f"Escalation: entity {entity_id} has {failure_count} consecutive "
                f"auto-remediation failures — manual intervention required"
            )

        async with async_session_factory() as session:
            now = datetime.now(timezone.utc)

            # 2. Rate limit — max N auto-actions per hour for this entity
            one_hour_ago = now - timedelta(hours=1)
            count_result = await session.execute(
                select(func.count(Action.id)).where(
                    Action.entity_id == entity_id,
                    Action.user_id == "auto-remediation",
                    Action.created_at >= one_hour_ago,
                )
            )
            hourly_count = count_result.scalar()
            if hourly_count >= max_per_hour:
                return False, (
                    f"Rate limit: {hourly_count} auto-actions in last hour "
                    f"(max {max_per_hour}) for entity {entity_id}"
                )

            # 3. Cooldown — no repeat auto-action within cooldown period
            cooldown_ago = now - timedelta(minutes=cooldown_minutes)
            last_action_result = await session.execute(
                select(Action)
                .where(
                    Action.entity_id == entity_id,
                    Action.action_type == action_type,
                    Action.user_id == "auto-remediation",
                    Action.created_at >= cooldown_ago,
                )
                .order_by(Action.created_at.desc())
                .limit(1)
            )
            last_action = last_action_result.scalar_one_or_none()
            if last_action:
                return False, (
                    f"Cooldown: last auto-{action_type} for {entity_id} was at "
                    f"{last_action.created_at} (cooldown {cooldown_minutes}m)"
                )

        return True, "All guardrails passed"

    def record_success(self, entity_id: str):
        """Reset escalation counter on successful auto-remediation."""
        if entity_id in self._escalation_failures:
            logger.info(
                "Escalation counter reset for entity=%s (auto-remediation succeeded)",
                entity_id,
            )
            del self._escalation_failures[entity_id]

    def record_failure(self, entity_id: str):
        """Increment escalation counter on failed auto-remediation."""
        self._escalation_failures[entity_id] = (
            self._escalation_failures.get(entity_id, 0) + 1
        )
        count = self._escalation_failures[entity_id]
        if count >= self._max_escalation_failures:
            logger.error(
                "ESCALATION: entity %s has %d consecutive auto-remediation failures — "
                "auto-remediation disabled for this entity until manual intervention",
                entity_id, count,
            )
        else:
            logger.warning(
                "Auto-remediation failure %d/%d for entity=%s",
                count, self._max_escalation_failures, entity_id,
            )
```

**Files to create:**
- `apps/actions-api/guardrails.py`

---

### Milestone 5 — Wire auto-remediation into Kafka consumer

**Status:** [ ] Not Started

Modify the Kafka consumer to check auto-remediation rules after storing a recommendation. The auto-remediation path executes actions through the normal action pipeline (K8s client + audit DB).

**`apps/actions-api/kafka_consumer.py`** — add auto-remediation hook:
```python
class HealthTransitionConsumer:
    def __init__(self, auto_remediation=None, guardrails=None, action_executor=None):
        # ... existing init ...
        self.auto_remediation = auto_remediation  # AutoRemediationEngine instance
        self.guardrails = guardrails              # Guardrails instance
        self._action_executor = action_executor   # Callable to execute actions

    async def _process_event(self, event: dict):
        # ... existing recommendation storage logic (from Sprint 2) ...

        # After storing recommendation, check auto-remediation
        if event["new_state"] != "HEALTHY" and self.auto_remediation:
            await self.auto_remediation.maybe_auto_remediate(
                event=event,
                guardrails=self.guardrails,
                action_executor=self._execute_auto_action,
            )

    async def _execute_auto_action(
        self,
        entity_id: str,
        action_type: str,
        user: str,
        reason: str,
        parameters: dict,
        correlation_id: str | None,
    ):
        """Execute an auto-remediation action through the normal action pipeline."""
        import uuid
        from datetime import datetime, timezone

        # Parse entity_id: k8s:{cluster}:{namespace}:{kind}:{name}
        parts = entity_id.split(":")
        if len(parts) != 5:
            logger.error("Invalid entity_id format for auto-action: %s", entity_id)
            return

        namespace, kind, name = parts[2], parts[3], parts[4]

        if kind != "Deployment":
            logger.warning("Auto-action only supports Deployment targets, got: %s", kind)
            return

        try:
            if action_type == "restart_deployment":
                # Uses asyncio.to_thread() (established pattern from Sprint 1)
                result_msg = await self.k8s_client.restart_deployment(name, namespace)
            elif action_type == "scale_deployment":
                replicas = parameters.get("replicas")
                if not replicas and parameters.get("replicas_add"):
                    # Resolve replicas_add to absolute count
                    status = await self.k8s_client.get_deployment_status(name, namespace)
                    current = status.get("replicas", 1)
                    max_replicas = parameters.get("max_replicas", 10)
                    replicas = min(current + parameters["replicas_add"], max_replicas)
                result_msg = await self.k8s_client.scale_deployment(name, namespace, replicas)
            else:
                logger.warning("Unknown auto-action type: %s", action_type)
                return

            # Record successful action in audit DB
            action_record = Action(
                id=str(uuid.uuid4()),
                entity_id=entity_id,
                entity_type=kind,
                entity_name=name,
                namespace=namespace,
                action_type=action_type,
                user_id=user,  # "auto-remediation"
                user_team="platform-team",
                parameters=parameters,
                reason=reason,
                status="success",
                result_message=result_msg,
                correlation_id=correlation_id,
                completed_at=datetime.now(timezone.utc),
            )
            async with async_session_factory() as session:
                session.add(action_record)
                await session.commit()

            logger.info(
                "Auto-remediation SUCCESS: entity=%s, action=%s, result=%s",
                entity_id, action_type, result_msg,
            )
            self.guardrails.record_success(entity_id)

        except Exception as e:
            logger.exception("Auto-remediation FAILED: entity=%s, action=%s", entity_id, action_type)
            self.guardrails.record_failure(entity_id)

            # Record failed action in audit DB
            action_record = Action(
                id=str(uuid.uuid4()),
                entity_id=entity_id,
                entity_type=kind,
                entity_name=name,
                namespace=namespace,
                action_type=action_type,
                user_id=user,
                user_team="platform-team",
                parameters=parameters,
                reason=reason,
                status="failure",
                result_message=str(e),
                correlation_id=correlation_id,
                completed_at=datetime.now(timezone.utc),
            )
            async with async_session_factory() as session:
                session.add(action_record)
                await session.commit()
```

**`apps/actions-api/main.py`** — wire auto-remediation into lifespan:
```python
from auto_remediation import AutoRemediationEngine
from guardrails import Guardrails

auto_remediation_engine = AutoRemediationEngine("/app/config/auto-remediation.yaml")
guardrails = Guardrails(max_escalation_failures=3)

health_consumer = HealthTransitionConsumer(
    auto_remediation=auto_remediation_engine,
    guardrails=guardrails,
)
```

**Files to modify:**
- `apps/actions-api/kafka_consumer.py` (add auto-remediation hook + execution)
- `apps/actions-api/main.py` (initialize auto-remediation + guardrails, inject into consumer)

---

### Milestone 6 — Optional Phase 2 actions: rollback + pause

**Status:** [ ] Not Started

Add `rollback_deployment` and `pause_rollout` actions. These are simple K8s patch operations. Include if straightforward; defer if edge cases arise.

**`apps/actions-api/k8s_client.py`** — add new actions:
```python
async def rollback_deployment(self, name: str, namespace: str) -> str:
    """Rollback deployment to previous revision via rollout undo."""
    def _rollback():
        # Kubernetes Python client: rollback is done by removing the
        # template hash annotation, which triggers a rollback to previous RS.
        # Alternatively, use the apps/v1 rollback API (deprecated in v1.16+).
        # Modern approach: patch with previous ReplicaSet template.
        #
        # Simplest approach: use kubectl subprocess as fallback
        # Or: read previous RS, patch deployment template to match
        import subprocess
        result = subprocess.run(
            ["kubectl", "rollout", "undo", f"deployment/{name}", "-n", namespace],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Rollback failed: {result.stderr}")
        return result.stdout.strip()

    # Uses asyncio.to_thread() — same pattern as restart/scale (Sprint 1)
    result = await asyncio.to_thread(_rollback)
    return f"Rollback initiated for deployment {name} in namespace {namespace}: {result}"

async def pause_rollout(self, name: str, namespace: str) -> str:
    """Pause deployment rollout progression."""
    def _pause():
        body = {"spec": {"paused": True}}
        return self.apps_v1.patch_namespaced_deployment(name, namespace, body)

    await asyncio.to_thread(_pause)
    return f"Rollout paused for deployment {name} in namespace {namespace}"

async def resume_rollout(self, name: str, namespace: str) -> str:
    """Resume a paused deployment rollout."""
    def _resume():
        body = {"spec": {"paused": False}}
        return self.apps_v1.patch_namespaced_deployment(name, namespace, body)

    await asyncio.to_thread(_resume)
    return f"Rollout resumed for deployment {name} in namespace {namespace}"
```

**`apps/actions-api/main.py`** — add action type routing:
```python
# In execute_action endpoint, add to action dispatch:
elif body.action_type == "rollback_deployment":
    result_msg = await k8s_client.rollback_deployment(name, namespace)
elif body.action_type == "pause_rollout":
    result_msg = await k8s_client.pause_rollout(name, namespace)
elif body.action_type == "resume_rollout":
    result_msg = await k8s_client.resume_rollout(name, namespace)
```

**Decision:** Include `rollback_deployment` and `pause_rollout`/`resume_rollout` if the `kubectl rollout undo` subprocess approach works cleanly in the k3s environment. If the service account lacks permissions or the subprocess approach is unreliable, defer to a later sprint.

**K8s RBAC note:** The existing ClusterRole already has `replicasets: [get, list]` for rollback history. No additional K8s RBAC changes needed — `deployments: [patch]` covers rollback and pause.

**Files to modify:**
- `apps/actions-api/k8s_client.py` (add rollback, pause, resume)
- `apps/actions-api/main.py` (add action type dispatch)
- `apps/actions-api/schemas.py` (add new action types to validation if enum-validated)

---

### Milestone 7 — Deploy and smoke test

**Status:** [ ] Not Started

```bash
# 1. Apply ConfigMap
ssh 5560 "sudo kubectl apply -f k8s/actions-api/configmap.yaml"

# 2. Build and deploy updated Actions API
cd apps/actions-api && docker build -t ghcr.io/haianhltr/actions-api:sprint4 .
docker push ghcr.io/haianhltr/actions-api:sprint4

# 3. Apply updated deployment (with ConfigMap volume mount)
ssh 5560 "sudo kubectl apply -f k8s/actions-api/"

# 4. Verify pod is running with config mounted
ssh 5560 "sudo kubectl get pods -n actions"
ssh 5560 "sudo kubectl exec deploy/actions-api -n actions -- ls /app/config/"
# Should show: rbac.yaml  auto-remediation.yaml

# 5. Verify RBAC config loaded in logs
ssh 5560 "sudo kubectl logs deploy/actions-api -n actions --tail=20 | grep RBAC"
# Should show: "RBAC config loaded: 2 teams, 2 roles"

# 6. Test RBAC — authorized user (should succeed):
curl -s -X POST http://192.168.1.210:31000/actions \
  -H "Content-Type: application/json" \
  -d '{
    "entity_id": "k8s:lab:calculator:Deployment:api",
    "action_type": "restart_deployment",
    "user": "engineer@team.com",
    "reason": "RBAC test — authorized team member"
  }'
# Should return 200 with status: success

# 7. Test RBAC — unknown user (should 403, fail-closed):
curl -s -X POST http://192.168.1.210:31000/actions \
  -H "Content-Type: application/json" \
  -d '{
    "entity_id": "k8s:lab:calculator:Deployment:api",
    "action_type": "restart_deployment",
    "user": "nobody@unknown.com",
    "reason": "RBAC test — should be denied"
  }'
# Should return 403: "User nobody@unknown.com not found in RBAC config"

# 8. Test RBAC — platform-admin on any entity (should succeed):
curl -s -X POST http://192.168.1.210:31000/actions \
  -H "Content-Type: application/json" \
  -d '{
    "entity_id": "k8s:lab:calculator:Deployment:api",
    "action_type": "restart_deployment",
    "user": "sre@team.com",
    "reason": "RBAC test — platform-admin"
  }'
# Should return 200

# 9. Test auto-remediation — trigger by causing CrashLoopBackOff:
ssh 5560 "sudo kubectl delete pod -l app=worker -n calculator"
# Wait ~2-3 min for DHS to detect UNHEALTHY + emit event + auto-remediation to trigger

# 10. Check logs for auto-remediation execution:
ssh 5560 "sudo kubectl logs deploy/actions-api -n actions --tail=40 | grep -i auto"
# Should show: "Auto-remediation rule matched: restart_on_crashloop"
# Followed by: "Auto-remediation EXECUTING" and "Auto-remediation SUCCESS"

# 11. Verify auto-remediation action in audit log:
curl -s "http://192.168.1.210:31000/actions?user=auto-remediation&limit=5" | python3 -m json.tool
# Should show action with user_id="auto-remediation", status="success"

# 12. Test guardrails — trigger again within cooldown (should be blocked):
ssh 5560 "sudo kubectl delete pod -l app=worker -n calculator"
# Wait for event...
ssh 5560 "sudo kubectl logs deploy/actions-api -n actions --tail=20 | grep -i 'blocked\|cooldown'"
# Should show: "Auto-remediation BLOCKED by guardrails: ... Cooldown"

# 13. Check metrics:
curl -s http://192.168.1.210:31000/metrics | grep -E "auto_remediation|rbac_denied"
```

---

### Milestone 8 — Write E2E tests

**Status:** [ ] Not Started

**`tests/e2e/test_auto_remediation.py`:**
```python
import pytest
import httpx

pytestmark = pytest.mark.sprint4

ACTIONS_API = "http://192.168.1.210:31000"


class TestRBACFullEnforcement:
    """Test full RBAC enforcement from config/rbac.yaml."""

    def test_authorized_team_member_allowed(self):
        """engineer@team.com (app-team) can act on calculator entities."""
        r = httpx.post(
            f"{ACTIONS_API}/actions",
            json={
                "entity_id": "k8s:lab:calculator:Deployment:api",
                "action_type": "restart_deployment",
                "user": "engineer@team.com",
                "reason": "RBAC test — authorized",
            },
        )
        assert r.status_code == 200
        assert r.json()["status"] == "success"

    def test_unknown_user_denied(self):
        """User not in RBAC config gets 403."""
        r = httpx.post(
            f"{ACTIONS_API}/actions",
            json={
                "entity_id": "k8s:lab:calculator:Deployment:api",
                "action_type": "restart_deployment",
                "user": "nobody@unknown.com",
                "reason": "Should be denied",
            },
        )
        assert r.status_code == 403

    def test_platform_admin_allowed_on_any_entity(self):
        """sre@team.com (platform-admin) can act on any entity."""
        r = httpx.post(
            f"{ACTIONS_API}/actions",
            json={
                "entity_id": "k8s:lab:calculator:Deployment:api",
                "action_type": "restart_deployment",
                "user": "sre@team.com",
                "reason": "Platform admin test",
            },
        )
        assert r.status_code == 200

    def test_fail_closed_no_ownership(self):
        """Entity without ownership record in SSOT is denied (fail-closed)."""
        r = httpx.post(
            f"{ACTIONS_API}/actions",
            json={
                "entity_id": "k8s:lab:unknown:Deployment:nonexistent",
                "action_type": "restart_deployment",
                "user": "engineer@team.com",
                "reason": "Should be denied — no ownership",
            },
        )
        assert r.status_code in [403, 404]  # 403 for fail-closed, 404 if entity not found


class TestAutoRemediationAudit:
    """Test that auto-remediation actions appear in audit log."""

    def test_auto_remediation_actions_recorded(self):
        """Auto-remediation actions should be recorded with user=auto-remediation."""
        r = httpx.get(
            f"{ACTIONS_API}/actions",
            params={"user": "auto-remediation", "limit": 10},
        )
        assert r.status_code == 200
        # Note: may be empty if no auto-remediation has triggered

    def test_auto_remediation_has_correlation_id(self):
        """Auto-remediation actions should have correlation_id linking to health event."""
        r = httpx.get(
            f"{ACTIONS_API}/actions",
            params={"user": "auto-remediation", "limit": 1},
        )
        assert r.status_code == 200
        actions = r.json()
        if actions:
            assert actions[0].get("correlation_id") is not None
```

**Files to create:**
- `tests/e2e/test_auto_remediation.py`

**Run tests:**
```bash
pytest tests/e2e/test_auto_remediation.py -v
```

---

### Milestone 9 — Update docs + write sprint review

**Status:** [ ] Not Started

- Update `documentation/sprint/ROADMAP.md` — mark Sprint 4 as complete
- Write `documentation/sprint/sprint4/REVIEW.md`

**Files to modify:**
- `documentation/sprint/ROADMAP.md`

**Files to create:**
- `documentation/sprint/sprint4/REVIEW.md`

---

## Design Decisions

| Decision | Rationale | Why not X |
|----------|-----------|-----------|
| RBAC fail-closed (no ownership = deny) | Security-first for a remediation service. Unknown entities should not be modifiable. Prevents accidental actions on unregistered resources. | Fail-open: dangerous — anyone could act on unregistered entities. |
| Config file for team mappings (not database) | Simple, static team roster. Changes require ConfigMap update + pod restart (acceptable for lab). Easy to audit in git. | Database: over-engineered for a small team roster. OIDC/LDAP: too complex for MVP. |
| ConfigMap for config files (not baked in image) | K8s-native config management. Can update config without rebuilding Docker image. Standard pattern. | Baked in image: requires rebuild on config change. Env vars: too complex for structured YAML with nested team mappings. |
| Auto-remediation user = `"auto-remediation"` | Clear audit trail. Easy to filter (`?user=auto-remediation`). Treated as `platform-admin` for RBAC bypass. | Generic system account: less descriptive in audit logs. |
| Guardrails: rate limit + cooldown via DB queries | Rate limit counts are accurate across pod restarts. DB is source of truth for action history. Simple SQL count. | In-memory counters: lost on pod restart, inaccurate counts. Redis: another dependency. |
| Escalation counter: in-memory (not DB) | Conservative — counter resets on pod restart, allowing retry. Escalation is a safety net, not critical state. Pod restart = "manual intervention" equivalent. | DB-backed counter: overkill for a simple guard. Would need cleanup logic. |
| Tier-1 warning only (not enforced) | Approval workflow requires UI flow + state machine + approver routing. Deferred to Phase 2. Warning ensures visibility in logs and metrics. | Full enforcement: requires building approval workflow not yet designed. |
| `restart_on_crashloop` enabled in ConfigMap | Allows testing auto-remediation in deployed environment. Source config file keeps `enabled: false` as safe default. ConfigMap overrides for deployment. | Enabled in source: risky default. Disabled everywhere: can't test. |
| `kubectl` subprocess for rollback | The Kubernetes Python client's rollback API was deprecated in apps/v1. `kubectl rollout undo` is the standard approach. Wrapped in `asyncio.to_thread()`. | Python client rollback: deprecated API, complex to implement. Direct RS patching: fragile. |
| Auto-remediation rule matches root cause kind | The `trigger.entity_type: Deployment` in config should match the root cause entity's kind, not the affected entity (which may be a Service). Root cause is the remediation target. | Matching affected entity type: may not be actionable (can't restart a Service). |

---

## Estimated New Files

| File | Purpose |
|------|---------|
| `apps/actions-api/auto_remediation.py` | Auto-remediation engine (rule matching + execution) |
| `apps/actions-api/guardrails.py` | Rate limiting, cooldown, escalation guardrails |
| `k8s/actions-api/configmap.yaml` | ConfigMap with rbac.yaml + auto-remediation.yaml |
| `tests/e2e/test_auto_remediation.py` | Sprint 4 E2E tests (RBAC + auto-remediation) |
| `documentation/sprint/sprint4/REVIEW.md` | Sprint retrospective |

## Estimated Modified Files

| File | Change |
|------|--------|
| `apps/actions-api/rbac.py` | Full rewrite — load from config/rbac.yaml, fail-closed |
| `apps/actions-api/requirements.txt` | Add `pyyaml==6.0.2` |
| `apps/actions-api/kafka_consumer.py` | Wire auto-remediation into event processing pipeline |
| `apps/actions-api/main.py` | Initialize AutoRemediationEngine + Guardrails, inject into consumer |
| `apps/actions-api/k8s_client.py` | Add `rollback_deployment`, `pause_rollout`, `resume_rollout` (optional) |
| `apps/actions-api/schemas.py` | Add new action types if enum-validated (optional) |
| `k8s/actions-api/deployment.yaml` | Add ConfigMap volume mount |
| `documentation/sprint/ROADMAP.md` | Mark Sprint 4 complete |
