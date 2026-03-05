import logging

from prometheus_client import Counter

import ssot_client

logger = logging.getLogger(__name__)

RBAC_DENIED = Counter("actions_rbac_denied_total", "RBAC denials", ["reason"])

PLATFORM_ADMINS = {"sre@team.com"}


class RBACEnforcer:
    async def check_permission(
        self, user: str, user_team: str | None, entity_id: str, action_type: str
    ) -> tuple[bool, str]:
        # Platform admins can act on anything
        if user in PLATFORM_ADMINS:
            logger.info("RBAC ALLOW: user=%s is platform-admin, entity=%s", user, entity_id)
            return True, "platform-admin"

        # Get ownership from SSOT
        ownership = await ssot_client.get_ownership(entity_id)

        # Fail-closed: no ownership record → deny
        if ownership is None:
            reason = f"No ownership record for entity {entity_id} — denied"
            logger.warning("RBAC DENY: %s", reason)
            RBAC_DENIED.labels(reason="no_ownership").inc()
            return False, reason

        owner_team = ownership.get("team")

        # Check if user's team matches entity owner
        if user_team and user_team == owner_team:
            logger.info(
                "RBAC ALLOW: user=%s team=%s owns entity=%s, action=%s",
                user, user_team, entity_id, action_type,
            )
            return True, f"team {user_team} owns entity"

        reason = f"User {user} (team={user_team}) does not own entity {entity_id} (owner={owner_team})"
        logger.warning("RBAC DENY: %s", reason)
        RBAC_DENIED.labels(reason="team_mismatch").inc()
        return False, reason
