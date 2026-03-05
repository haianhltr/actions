# Sprint 2 — Kafka Consumer + Recommendations

**Goal:** Consume `health.transition.v1` events from Kafka, store pending recommendations in Postgres, expose them via `GET /recommendations`, and link actions to triggering health events via `correlation_id`.

**Status:** Not Started
**Depends on:** Sprint 1 complete, Team 5 Sprint 3 (health.transition.v1 events on Kafka) — ALREADY LIVE, Team 2 Kafka — ALREADY LIVE

---

## Pre-Sprint State

- `actions` namespace running in k3s
- Actions Postgres with `actions` audit table
- Actions API (FastAPI) at `http://192.168.1.210:31000` with:
  - `POST /actions` — execute restart/scale
  - `GET /actions` — list actions with filters
  - `GET /actions/{id}` — action detail
  - RBAC stub (ownership check via SSOT)
  - K8s client (`restart_deployment`, `scale_deployment` via `asyncio.to_thread()`)
  - Audit logging in Postgres
  - Prometheus metrics at `/metrics`
  - Health probe at `/health`

## Post-Sprint State

- Kafka consumer running as background task inside Actions API pod
  - Subscribes to `health.transition.v1` topic
  - Consumer group: `actions-consumer-group`
  - Bootstrap: `kafka.calculator.svc.cluster.local:9092` (FQDN required for cross-namespace)
  - Processes health transition events from DHS
- `recommendations` table in Postgres
  - Stores pending recommendations (one per entity, latest event wins via UPSERT)
  - Clears recommendation on recovery (`new_state == HEALTHY`)
- `GET /recommendations` endpoint with optional filters
- Correlation: actions linked to triggering health events via `correlation_id` (auto-populated from current recommendation)
- New Prometheus metrics: `actions_recommendations_total`, `actions_recommendations_cleared_total`
- Event deduplication via `event_id`

---

## Milestones

### Milestone 1 — Add aiokafka dependency + Kafka config

**Status:** [ ] Not Started

**`apps/actions-api/requirements.txt`** — add:
```
aiokafka==0.11.0
```

**`apps/actions-api/config.py`** — add Kafka config vars:
```python
# Kafka config
KAFKA_BOOTSTRAP_SERVERS = os.getenv(
    "KAFKA_BOOTSTRAP_SERVERS",
    "kafka.calculator.svc.cluster.local:9092",  # FQDN required for cross-namespace
)
KAFKA_TOPIC = os.getenv("KAFKA_TOPIC", "health.transition.v1")
KAFKA_CONSUMER_GROUP = os.getenv("KAFKA_CONSUMER_GROUP", "actions-consumer-group")
```

**Files to modify:**
- `apps/actions-api/requirements.txt`
- `apps/actions-api/config.py`

---

### Milestone 2 — Recommendation model + DB table

**Status:** [ ] Not Started

**`apps/actions-api/models.py`** — add Recommendation model:
```python
class Recommendation(Base):
    __tablename__ = "recommendations"
    id                      = Column(Text, primary_key=True)
    entity_id               = Column(Text, nullable=False, unique=True)  # one per entity
    entity_name             = Column(Text, nullable=False)
    entity_type             = Column(Text, nullable=False)
    health_state            = Column(Text, nullable=False)  # UNHEALTHY, DEGRADED
    reason                  = Column(Text, nullable=True)
    root_cause_entity_id    = Column(Text, nullable=True)
    root_cause_entity_name  = Column(Text, nullable=True)
    recommended_action      = Column(Text, nullable=False)  # restart_deployment, scale_deployment
    owner_team              = Column(Text, nullable=True)
    tier                    = Column(Text, nullable=True)
    event_id                = Column(Text, nullable=False)   # from health.transition event
    since                   = Column(DateTime(timezone=True), nullable=False)
    created_at              = Column(DateTime(timezone=True), server_default=func.now())
    updated_at              = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
```

The table uses UPSERT semantics on `entity_id` — only the latest event per entity is stored. When `new_state == HEALTHY`, the recommendation row is deleted.

**`apps/actions-api/schemas.py`** — add response schema:
```python
class RecommendationResponse(BaseModel):
    entity_id: str
    entity_name: str
    entity_type: str
    health_state: str
    reason: str | None = None
    root_cause_entity_id: str | None = None
    root_cause_entity_name: str | None = None
    recommended_action: str
    owner_team: str | None = None
    tier: str | None = None
    since: datetime

    model_config = ConfigDict(from_attributes=True)
```

**Files to modify:**
- `apps/actions-api/models.py`
- `apps/actions-api/schemas.py`

---

### Milestone 3 — Kafka consumer implementation

**Status:** [ ] Not Started

**`apps/actions-api/kafka_consumer.py`:**
```python
import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone

from aiokafka import AIOKafkaConsumer
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy import func

from config import KAFKA_BOOTSTRAP_SERVERS, KAFKA_TOPIC, KAFKA_CONSUMER_GROUP
from database import async_session_factory
from models import Recommendation

logger = logging.getLogger(__name__)

# Prometheus metrics (defined in main.py or metrics module)
# RECOMMENDATIONS_TOTAL = Counter("actions_recommendations_total", "Health transition events stored as recommendations")
# RECOMMENDATIONS_CLEARED = Counter("actions_recommendations_cleared_total", "Recommendations cleared on recovery")


class HealthTransitionConsumer:
    def __init__(self):
        self.consumer: AIOKafkaConsumer | None = None
        self._running = False
        self._seen_event_ids: set[str] = set()  # Simple dedup (bounded)
        self._max_seen = 10000

    async def start(self):
        """Connect to Kafka and start the consumer."""
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
        """Stop the consumer gracefully."""
        self._running = False
        if self.consumer:
            await self.consumer.stop()
        logger.info("Kafka consumer stopped")

    async def consume_loop(self):
        """Main consumption loop — run as asyncio background task."""
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
        """Process a single health.transition.v1 event."""
        event_id = event.get("event_id")
        if not event_id:
            logger.warning("Event missing event_id, skipping")
            return

        # Deduplication via event_id (at-least-once delivery)
        if event_id in self._seen_event_ids:
            logger.debug("Duplicate event_id=%s, skipping", event_id)
            return
        self._seen_event_ids.add(event_id)
        if len(self._seen_event_ids) > self._max_seen:
            self._seen_event_ids = set(list(self._seen_event_ids)[-5000:])

        entity_id = event["entity_id"]
        new_state = event["new_state"]

        logger.info(
            "Processing health transition: entity=%s, %s → %s",
            entity_id, event.get("old_state"), new_state,
        )

        async with async_session_factory() as session:
            if new_state == "HEALTHY":
                # Clear recommendation for this entity (it recovered)
                await session.execute(
                    delete(Recommendation).where(Recommendation.entity_id == entity_id)
                )
                await session.commit()
                logger.info("Cleared recommendation for %s (recovered)", entity_id)
                # RECOMMENDATIONS_CLEARED.inc()
            else:
                # Determine recommended action based on event
                recommended_action = self._determine_recommended_action(event)
                if not recommended_action:
                    logger.info(
                        "No recommendation for entity=%s (non-Deployment target)",
                        entity_id,
                    )
                    return

                # UPSERT recommendation (latest event per entity wins)
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
                # RECOMMENDATIONS_TOTAL.inc()

    def _determine_recommended_action(self, event: dict) -> str | None:
        """
        Determine recommended action based on health transition event.

        Logic:
        - Use root_cause_entity_id if present (remediate root cause, not symptom)
        - Parse entity kind from ID format: k8s:{cluster}:{namespace}:{kind}:{name}
        - MVP: only Deployment targets are actionable
        - UNHEALTHY → restart_deployment
        - DEGRADED  → scale_deployment
        """
        new_state = event["new_state"]

        # Determine target entity for remediation
        target_entity_id = event.get("root_cause_entity_id") or event["entity_id"]

        # Parse entity kind from ID: k8s:{cluster}:{namespace}:{kind}:{name}
        parts = target_entity_id.split(":")
        if len(parts) != 5:
            return None
        entity_kind = parts[3]

        # MVP: only Deployment targets are actionable
        if entity_kind != "Deployment":
            return None

        if new_state == "UNHEALTHY":
            return "restart_deployment"
        elif new_state == "DEGRADED":
            return "scale_deployment"

        return None
```

**Files to create:**
- `apps/actions-api/kafka_consumer.py`

---

### Milestone 4 — GET /recommendations endpoint

**Status:** [ ] Not Started

**`apps/actions-api/main.py`** — add recommendations endpoint and consumer lifecycle:
```python
import asyncio
from contextlib import asynccontextmanager
from kafka_consumer import HealthTransitionConsumer
from models import Recommendation
from schemas import RecommendationResponse

# Global consumer instance
health_consumer = HealthTransitionConsumer()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start Kafka consumer on startup, stop on shutdown."""
    # Startup
    try:
        await health_consumer.start()
        consumer_task = asyncio.create_task(health_consumer.consume_loop())
        logger.info("Kafka consumer background task started")
    except Exception:
        logger.exception("Failed to start Kafka consumer — continuing without it")
        consumer_task = None
    yield
    # Shutdown
    await health_consumer.stop()
    if consumer_task:
        consumer_task.cancel()

app = FastAPI(title="Actions API", version="0.2.0", lifespan=lifespan)

@app.get("/recommendations", response_model=list[RecommendationResponse])
async def list_recommendations(
    entity_id: str | None = None,
    health_state: str | None = None,
    entity_type: str | None = None,
    owner_team: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """List pending recommendations from health.transition events."""
    query = select(Recommendation)
    if entity_id:
        query = query.where(Recommendation.entity_id == entity_id)
    if health_state:
        query = query.where(Recommendation.health_state == health_state)
    if entity_type:
        query = query.where(Recommendation.entity_type == entity_type)
    if owner_team:
        query = query.where(Recommendation.owner_team == owner_team)
    query = query.order_by(Recommendation.updated_at.desc())

    result = await db.execute(query)
    return result.scalars().all()
```

**Files to modify:**
- `apps/actions-api/main.py`

---

### Milestone 5 — Correlation: link actions to health events

**Status:** [ ] Not Started

When `POST /actions` is called, auto-populate `correlation_id` from the current recommendation for that entity (if one exists). This links the action to the health event that triggered it.

**`apps/actions-api/schemas.py`** — add `correlation_id` to request:
```python
class ActionRequest(BaseModel):
    entity_id: str
    action_type: str
    user: str
    reason: str | None = None
    parameters: dict = {}
    correlation_id: str | None = None  # Optional: link to health.transition event_id
```

**`apps/actions-api/main.py`** — modify `execute_action`:
```python
@app.post("/actions", response_model=ActionResponse, status_code=200)
async def execute_action(body: ActionRequest, db: AsyncSession = Depends(get_db)):
    # ... existing validation + RBAC ...

    # Auto-populate correlation_id from current recommendation
    correlation_id = body.correlation_id
    if not correlation_id:
        result = await db.execute(
            select(Recommendation).where(Recommendation.entity_id == body.entity_id)
        )
        recommendation = result.scalar_one_or_none()
        if recommendation:
            correlation_id = recommendation.event_id
            logger.info(
                "Auto-populated correlation_id=%s from recommendation for entity=%s",
                correlation_id, body.entity_id,
            )

    # ... create Action record with correlation_id ...
    # ... execute K8s action ...
```

**Files to modify:**
- `apps/actions-api/schemas.py`
- `apps/actions-api/main.py`

---

### Milestone 6 — Deploy updated Actions API

**Status:** [ ] Not Started

**`k8s/actions-api/deployment.yaml`** — add Kafka env vars:
```yaml
env:
  # ... existing env vars (DATABASE_URL, SSOT_API_URL, etc.) ...
  - name: KAFKA_BOOTSTRAP_SERVERS
    value: "kafka.calculator.svc.cluster.local:9092"
  - name: KAFKA_TOPIC
    value: "health.transition.v1"
  - name: KAFKA_CONSUMER_GROUP
    value: "actions-consumer-group"
```

Build and deploy:
```bash
# Build new image with aiokafka
cd apps/actions-api && docker build -t ghcr.io/<repo>/actions-api:sprint2 .
docker push ghcr.io/<repo>/actions-api:sprint2

# Apply updated deployment manifest
ssh 5560 "sudo kubectl apply -f k8s/actions-api/"

# Or update image directly
ssh 5560 "sudo kubectl set image deployment/actions-api \
  actions-api=ghcr.io/<repo>/actions-api:sprint2 -n actions"
```

**Files to modify:**
- `k8s/actions-api/deployment.yaml`

**Verification:**
```bash
# Check pod is running and ready
ssh 5560 "sudo kubectl get pods -n actions"

# Check consumer started in logs
ssh 5560 "sudo kubectl logs deploy/actions-api -n actions --tail=20 | grep -i kafka"
# Should see: "Kafka consumer started: topic=health.transition.v1, group=actions-consumer-group"

# Verify recommendations table was created
ssh 5560 "sudo kubectl exec -n actions statefulset/postgres -- \
  psql -U actions -c '\dt recommendations'"
```

---

### Milestone 7 — Smoke test: recommendations + correlation

**Status:** [ ] Not Started

```bash
# 1. Verify Kafka consumer is connected:
ssh 5560 "sudo kubectl logs deploy/actions-api -n actions --tail=30 | grep -iE 'kafka|consumer'"

# 2. Check recommendations (may be empty if no transitions occurred yet):
curl -s "http://192.168.1.210:31000/recommendations" | python3 -m json.tool

# 3. Trigger a health transition by killing a worker pod:
ssh 5560 "sudo kubectl delete pod -l app=worker -n calculator"
# Wait ~2-3 min for DHS to detect UNHEALTHY and emit health.transition event

# 4. Check recommendations again — should show the affected entity:
curl -s "http://192.168.1.210:31000/recommendations" | python3 -m json.tool
# Expected: recommendation with recommended_action="restart_deployment"

# 5. Filter recommendations by health state:
curl -s "http://192.168.1.210:31000/recommendations?health_state=UNHEALTHY" | python3 -m json.tool

# 6. Execute action from recommendation and verify correlation:
curl -s -X POST http://192.168.1.210:31000/actions \
  -H "Content-Type: application/json" \
  -H "X-User-Team: app-team" \
  -d '{
    "entity_id": "k8s:lab:calculator:Deployment:worker",
    "action_type": "restart_deployment",
    "user": "engineer@team.com",
    "reason": "Acting on recommendation"
  }'

# 7. Verify correlation_id is set on the action:
curl -s "http://192.168.1.210:31000/actions?limit=1" | python3 -m json.tool
# correlation_id should match the event_id from the recommendation

# 8. After recovery, recommendation should clear automatically:
# Wait for DHS to emit HEALTHY event (~2-3 min after pods recover)
curl -s "http://192.168.1.210:31000/recommendations" | python3 -m json.tool
# Should no longer contain the recovered entity

# 9. Check new Prometheus metrics:
curl -s http://192.168.1.210:31000/metrics | grep actions_recommendations
# Should show actions_recommendations_total, actions_recommendations_cleared_total
```

---

### Milestone 8 — Write E2E tests

**Status:** [ ] Not Started

**`tests/e2e/test_recommendations.py`:**
```python
import pytest
import httpx
import time

pytestmark = pytest.mark.sprint2

ACTIONS_API = "http://192.168.1.210:31000"


class TestRecommendationsEndpoint:
    """Test GET /recommendations endpoint."""

    def test_recommendations_returns_200(self):
        """GET /recommendations returns 200 with a list."""
        r = httpx.get(f"{ACTIONS_API}/recommendations")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_recommendations_filter_by_entity(self):
        """GET /recommendations?entity_id=X returns filtered results."""
        r = httpx.get(
            f"{ACTIONS_API}/recommendations",
            params={"entity_id": "nonexistent-entity"},
        )
        assert r.status_code == 200
        assert r.json() == []

    def test_recommendations_filter_by_health_state(self):
        """GET /recommendations?health_state=UNHEALTHY returns filtered results."""
        r = httpx.get(
            f"{ACTIONS_API}/recommendations",
            params={"health_state": "UNHEALTHY"},
        )
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_recommendation_schema(self):
        """Recommendations include expected fields."""
        r = httpx.get(f"{ACTIONS_API}/recommendations")
        assert r.status_code == 200
        for rec in r.json():
            assert "entity_id" in rec
            assert "recommended_action" in rec
            assert "health_state" in rec
            assert "since" in rec


class TestCorrelation:
    """Test that actions get correlation_id from recommendations."""

    def test_action_with_explicit_correlation_id(self):
        """POST /actions with correlation_id stores it."""
        r = httpx.post(
            f"{ACTIONS_API}/actions",
            json={
                "entity_id": "k8s:lab:calculator:Deployment:api",
                "action_type": "restart_deployment",
                "user": "engineer@team.com",
                "reason": "Correlation test",
                "correlation_id": "test-event-id-123",
            },
        )
        assert r.status_code == 200
        action_id = r.json()["action_id"]

        # Verify correlation_id was stored
        detail = httpx.get(f"{ACTIONS_API}/actions/{action_id}")
        assert detail.json()["correlation_id"] == "test-event-id-123"
```

**Files to create:**
- `tests/e2e/test_recommendations.py`

**Run tests:**
```bash
pytest tests/e2e/test_recommendations.py -v
```

---

### Milestone 9 — Update docs + write sprint review

**Status:** [ ] Not Started

- Update `documentation/sprint/ROADMAP.md` — mark Sprint 2 as complete
- Write `documentation/sprint/sprint2/REVIEW.md`

**Files to modify:**
- `documentation/sprint/ROADMAP.md`

**Files to create:**
- `documentation/sprint/sprint2/REVIEW.md`

---

## Design Decisions

| Decision | Rationale | Why not X |
|----------|-----------|-----------|
| Postgres `recommendations` table (not in-memory) | Survives pod restarts. Kafka consumer offsets are committed, so old messages won't be re-read after a restart — recommendations would be lost. | In-memory dict: recommendations lost on pod restart. Redis: another dependency to manage. |
| UPSERT on `entity_id` (one recommendation per entity) | An entity can only have one current health state. Latest event supersedes previous. Simple, no cleanup needed. | Multiple rows per entity: requires dedup/expiry logic, more complex queries. |
| `aiokafka` (async Kafka client) | Matches FastAPI's async architecture. Native asyncio support. Runs in the same event loop without blocking. | `confluent-kafka`: sync, requires C library build. `kafka-python`: sync, would block the event loop. |
| `auto_offset_reset=latest` | Don't replay old events on first startup. Recommendations should reflect current state, not history. | `earliest`: would flood with historical events, most already stale. |
| Root-cause-aware recommendations | Recommend action on root cause Deployment, not the affected Service. A Service can't be restarted directly — the underlying Deployment is the remediation target. | Action on affected entity: may not be a Deployment, can't restart a Service. |
| `event_id` for deduplication | At-least-once Kafka delivery means duplicates are possible. `event_id` dedup prevents double-processing. UPSERT makes duplicates harmless but avoids unnecessary DB writes. | No dedup: harmless due to UPSERT but wastes processing. |
| Kafka FQDN `kafka.calculator.svc.cluster.local:9092` | Cross-namespace DNS resolution requires FQDN. Short name `kafka:9092` fails from `actions` namespace. | Short name `kafka:9092`: fails cross-namespace. `kafka.calculator:9092`: works but FQDN is safest. |
| Consumer as FastAPI lifespan background task | Single process, no extra pod. Consumer shares the DB connection pool. Simple deployment. | Separate consumer pod: more infra, harder to share state. Celery: overkill for one consumer. |

---

## Estimated New Files

| File | Purpose |
|------|---------|
| `apps/actions-api/kafka_consumer.py` | Kafka consumer for `health.transition.v1` events |
| `tests/e2e/test_recommendations.py` | Sprint 2 E2E tests |
| `documentation/sprint/sprint2/REVIEW.md` | Sprint retrospective |

## Estimated Modified Files

| File | Change |
|------|--------|
| `apps/actions-api/requirements.txt` | Add `aiokafka==0.11.0` |
| `apps/actions-api/config.py` | Add `KAFKA_BOOTSTRAP_SERVERS`, `KAFKA_TOPIC`, `KAFKA_CONSUMER_GROUP` |
| `apps/actions-api/models.py` | Add `Recommendation` model |
| `apps/actions-api/schemas.py` | Add `RecommendationResponse`, `correlation_id` on `ActionRequest` |
| `apps/actions-api/main.py` | Add `GET /recommendations`, Kafka consumer lifespan, correlation auto-populate |
| `k8s/actions-api/deployment.yaml` | Add Kafka env vars |
| `documentation/sprint/ROADMAP.md` | Mark Sprint 2 complete |
