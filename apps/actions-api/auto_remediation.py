import yaml
import logging
from prometheus_client import Counter

logger = logging.getLogger(__name__)

AUTO_REMEDIATION_TOTAL = Counter(
    "actions_auto_remediation_total", "Auto-remediation actions",
    ["action_name", "status"],
)
AUTO_REMEDIATION_BLOCKED = Counter(
    "actions_auto_remediation_blocked_total", "Auto-remediation blocked by guardrails",
)


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
        - trigger.reason_contains must be a substring of event.reason
        """
        new_state = event.get("new_state")
        reason = event.get("reason", "")

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
            AUTO_REMEDIATION_BLOCKED.inc()
            return

        # Build action parameters
        parameters = dict(rule["action"].get("parameters", {}))

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

        AUTO_REMEDIATION_TOTAL.labels(action_name=rule_name, status="executed").inc()
