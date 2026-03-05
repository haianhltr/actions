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
        self._escalation_failures: dict[str, int] = {}
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
        # 1. Escalation check
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
