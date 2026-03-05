import json
import logging
import uuid
from collections import OrderedDict
from datetime import datetime, timezone

from aiokafka import AIOKafkaConsumer
from prometheus_client import Counter
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy import func

from config import KAFKA_BOOTSTRAP_SERVERS, KAFKA_TOPIC, KAFKA_CONSUMER_GROUP
from database import async_session_factory
from models import Recommendation

logger = logging.getLogger(__name__)

RECOMMENDATIONS_TOTAL = Counter(
    "actions_recommendations_total", "Health transition events stored as recommendations"
)
RECOMMENDATIONS_CLEARED = Counter(
    "actions_recommendations_cleared_total", "Recommendations cleared on recovery"
)


class HealthTransitionConsumer:
    def __init__(self):
        self.consumer: AIOKafkaConsumer | None = None
        self._running = False
        self._seen_event_ids: OrderedDict[str, None] = OrderedDict()
        self._max_seen = 10000

    async def start(self):
        self.consumer = AIOKafkaConsumer(
            KAFKA_TOPIC,
            bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
            group_id=KAFKA_CONSUMER_GROUP,
            value_deserializer=lambda m: json.loads(m.decode("utf-8")),
            auto_offset_reset="latest",
            enable_auto_commit=True,
        )
        await self.consumer.start()
        self._running = True
        logger.info(
            "Kafka consumer started: topic=%s, group=%s, bootstrap=%s",
            KAFKA_TOPIC, KAFKA_CONSUMER_GROUP, KAFKA_BOOTSTRAP_SERVERS,
        )

    async def stop(self):
        self._running = False
        if self.consumer:
            await self.consumer.stop()
        logger.info("Kafka consumer stopped")

    async def consume_loop(self):
        try:
            async for msg in self.consumer:
                if not self._running:
                    break
                try:
                    await self._process_event(msg.value)
                except Exception:
                    logger.exception("Error processing Kafka message: %s", msg.value)
        except Exception:
            logger.exception("Kafka consumer loop error")

    async def _process_event(self, event: dict):
        event_id = event.get("event_id")
        if not event_id:
            logger.warning("Event missing event_id, skipping")
            return

        # Deduplication
        if event_id in self._seen_event_ids:
            logger.debug("Duplicate event_id=%s, skipping", event_id)
            return
        self._seen_event_ids[event_id] = None
        while len(self._seen_event_ids) > self._max_seen:
            self._seen_event_ids.popitem(last=False)

        entity_id = event["entity_id"]
        new_state = event["new_state"]

        logger.info(
            "Processing health transition: entity=%s, %s -> %s",
            entity_id, event.get("old_state"), new_state,
        )

        async with async_session_factory() as session:
            if new_state == "HEALTHY":
                await session.execute(
                    delete(Recommendation).where(Recommendation.entity_id == entity_id)
                )
                await session.commit()
                logger.info("Cleared recommendation for %s (recovered)", entity_id)
                RECOMMENDATIONS_CLEARED.inc()
            else:
                recommended_action = self._determine_recommended_action(event)
                if not recommended_action:
                    logger.info(
                        "No recommendation for entity=%s (non-Deployment target)",
                        entity_id,
                    )
                    return

                stmt = pg_insert(Recommendation).values(
                    id=str(uuid.uuid4()),
                    entity_id=entity_id,
                    entity_name=event.get("entity_name", ""),
                    entity_type=event.get("entity_type", ""),
                    health_state=new_state,
                    reason=event.get("reason"),
                    root_cause_entity_id=event.get("root_cause_entity_id"),
                    root_cause_entity_name=event.get("root_cause_entity_name"),
                    recommended_action=recommended_action,
                    owner_team=event.get("owner_team"),
                    tier=event.get("tier"),
                    event_id=event_id,
                    since=event.get("since", datetime.now(timezone.utc).isoformat()),
                ).on_conflict_do_update(
                    index_elements=["entity_id"],
                    set_={
                        "entity_name": event.get("entity_name", ""),
                        "entity_type": event.get("entity_type", ""),
                        "health_state": new_state,
                        "reason": event.get("reason"),
                        "root_cause_entity_id": event.get("root_cause_entity_id"),
                        "root_cause_entity_name": event.get("root_cause_entity_name"),
                        "recommended_action": recommended_action,
                        "owner_team": event.get("owner_team"),
                        "tier": event.get("tier"),
                        "event_id": event_id,
                        "since": event.get("since"),
                        "updated_at": func.now(),
                    },
                )
                await session.execute(stmt)
                await session.commit()
                logger.info(
                    "Stored recommendation: entity=%s, action=%s",
                    entity_id, recommended_action,
                )
                RECOMMENDATIONS_TOTAL.inc()

    def _determine_recommended_action(self, event: dict) -> str | None:
        new_state = event["new_state"]
        target_entity_id = event.get("root_cause_entity_id") or event["entity_id"]

        parts = target_entity_id.split(":")
        if len(parts) != 5:
            return None
        entity_kind = parts[3]

        if entity_kind != "Deployment":
            return None

        if new_state == "UNHEALTHY":
            return "restart_deployment"
        elif new_state == "DEGRADED":
            return "scale_deployment"

        return None
