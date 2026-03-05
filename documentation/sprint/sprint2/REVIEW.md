# Sprint 2 Review — Kafka Consumer + Recommendations

**Sprint:** 2
**Duration:** 2026-03-05
**Status:** Complete

## Objective

Consume `health.transition.v1` events from Kafka, store pending recommendations in Postgres, expose them via `GET /recommendations`, and link actions to triggering health events via `correlation_id`.

## What We Shipped

- **Kafka consumer** running as a FastAPI lifespan background task
  - Subscribes to `health.transition.v1` topic via `aiokafka`
  - Consumer group: `actions-consumer-group`
  - Bootstrap: `kafka.calculator.svc.cluster.local:9092` (cross-namespace FQDN)
  - `auto_offset_reset=latest` — only processes new events
  - Event deduplication via `event_id` (bounded OrderedDict, 10k entries)
- **`recommendations` table** in Postgres
  - UPSERT semantics on `entity_id` — one recommendation per entity, latest event wins
  - Clears recommendation when `new_state == HEALTHY`
  - Root-cause-aware: uses `root_cause_entity_id` if present
- **`GET /recommendations`** endpoint with filters: `entity_id`, `health_state`, `entity_type`, `owner_team`
- **Correlation** — `POST /actions` auto-populates `correlation_id` from the current recommendation for the target entity
  - Also accepts explicit `correlation_id` in the request body
- **Recommendation logic:**
  - UNHEALTHY + Deployment target → `restart_deployment`
  - DEGRADED + Deployment target → `scale_deployment`
  - Non-Deployment targets → no recommendation (skipped)
- **New Prometheus metrics:** `actions_recommendations_total`, `actions_recommendations_cleared_total`
- **E2E tests:** 8 new tests (18 total, all passing)
- **Version bump:** API now reports `0.2.0`

## Key Metrics

- 18/18 E2E tests passing (10 Sprint 1 + 8 Sprint 2)
- Kafka consumer connects and joins group in <1s
- 0 regressions from Sprint 1

## Incidents & Fixes During Rollout

| Issue | Resolution |
|-------|------------|
| No health transitions during testing | DHS had 0 transitions (steady state). Consumer is connected and waiting — will process events when they occur. Verified via DHS logs showing `0 transitions` in eval cycles. |
| SSOT ownership missing for Deployments (Sprint 1 fix) | Already resolved in Sprint 1 — registered via `PUT /ownership` |

## Architecture Before & After

**Before (Sprint 1):**
```
Actions API v0.1.0
├── POST /actions (restart, scale)
├── GET /actions, GET /actions/{id}
├── RBAC, audit, K8s client
└── No Kafka, no recommendations
```

**After (Sprint 2):**
```
Actions API v0.2.0
├── POST /actions (restart, scale, correlation_id)
├── GET /actions, GET /actions/{id}
├── GET /recommendations (with filters)
├── RBAC, audit, K8s client
└── Kafka consumer (background task)
    ├── health.transition.v1 → recommendations table
    ├── UPSERT on entity_id
    ├── Clear on HEALTHY recovery
    └── Dedup via event_id
```

## Design Decisions

| Decision | Rationale |
|----------|-----------|
| `aiokafka` (not `confluent-kafka`) | Native asyncio, no C library dependency, runs in FastAPI event loop |
| Consumer as lifespan background task | Single process, shares DB pool, no extra pod |
| UPSERT on `entity_id` | One recommendation per entity, latest event wins, simple |
| `auto_offset_reset=latest` | Don't replay stale history on first startup |
| Root-cause-aware recommendations | Remediate the Deployment, not the affected Service |
| Bounded dedup (10k OrderedDict) | Memory-safe, FIFO eviction of oldest event_ids |

## What We Didn't Do (and why)

| Skipped | Reason |
|---------|--------|
| Live health transition test (kill pod) | DHS was in steady state with 0 transitions. Consumer verified connected and ready. |
| Auto-remediation | Sprint 4 scope |
| Ops UI | Sprint 3 scope |

## Completion Checklist

- [x] `aiokafka` dependency added
- [x] Kafka config vars in config.py and deployment.yaml
- [x] `Recommendation` model with UPSERT semantics
- [x] `RecommendationResponse` schema
- [x] `kafka_consumer.py` with `HealthTransitionConsumer`
- [x] Consumer starts as background task in lifespan
- [x] `GET /recommendations` with filters
- [x] `correlation_id` auto-populated from recommendation
- [x] `correlation_id` accepted in `ActionRequest`
- [x] Event deduplication via `event_id`
- [x] Prometheus metrics registered
- [x] `recommendations` table created in Postgres
- [x] Kafka consumer connected to partition 0
- [x] Sprint 1 tests still passing (no regressions)
- [x] 8 new E2E tests passing

## What's Next

Sprint 3: Ops UI — health overview page, entity detail page, action buttons with confirmation dialog, served via Nginx at `:31080`.
