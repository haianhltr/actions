import yaml
import logging
from prometheus_client import Counter

logger = logging.getLogger(__name__)

RBAC_DENIED = Counter("actions_rbac_denied_total", "RBAC denials", ["reason"])


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
            RBAC_DENIED.labels(reason="user_not_found").inc()
            return False, f"User {user} not found in RBAC config"

        # 3. Get entity ownership from SSOT
        ownership = await ssot_client.get_ownership(entity_id)

        # 4. FAIL CLOSED: no ownership record = deny
        if not ownership:
            logger.warning(
                "RBAC DENY: no ownership record for entity=%s (fail-closed)",
                entity_id,
            )
            RBAC_DENIED.labels(reason="no_ownership").inc()
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
            RBAC_DENIED.labels(reason="team_mismatch").inc()
            return False, (
                f"User {user} (team={user_team}) does not own "
                f"entity {entity_id} (owner={owner_team})"
            )

        # 6. Check tier restrictions
        tier = ownership.get("tier", "tier-3")
        tier_config = self.tier_restrictions.get(tier, {})
        if tier_config.get("requires_approval", False):
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
