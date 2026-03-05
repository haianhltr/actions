import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Header, Request
from fastapi.responses import PlainTextResponse
from prometheus_client import Counter, Histogram, generate_latest
from pythonjsonlogger import jsonlogger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import engine, get_db
from k8s_client import K8sClient
from kafka_consumer import HealthTransitionConsumer
from models import Action, Base, Recommendation
from rbac import RBACEnforcer
from schemas import ActionDetail, ActionRequest, ActionResponse, RecommendationResponse
import ssot_client

# --- Logging ---
handler = logging.StreamHandler()
handler.setFormatter(jsonlogger.JsonFormatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
logging.root.handlers = [handler]
logging.root.setLevel(logging.INFO)
logger = logging.getLogger(__name__)

# --- Prometheus metrics ---
ACTIONS_EXECUTED = Counter(
    "actions_executed_total", "Actions executed", ["action_type", "status"]
)
ACTIONS_EXECUTION_DURATION = Histogram(
    "actions_execution_duration_seconds", "Time to execute action", ["action_type"]
)
API_REQUESTS = Counter(
    "actions_api_requests_total", "API requests", ["method", "endpoint", "status"]
)
API_REQUEST_DURATION = Histogram(
    "actions_api_request_duration_seconds", "API request latency", ["method", "endpoint"]
)

# --- Globals ---
k8s_client: K8sClient | None = None
rbac = RBACEnforcer()
health_consumer = HealthTransitionConsumer()
_start_time = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global k8s_client
    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables created")

    # Initialize K8s client
    try:
        k8s_client = K8sClient()
        logger.info("K8s client initialized")
    except Exception:
        logger.exception("Failed to initialize K8s client — actions will fail")

    # Start Kafka consumer
    consumer_task = None
    try:
        await health_consumer.start()
        consumer_task = asyncio.create_task(health_consumer.consume_loop())
        logger.info("Kafka consumer background task started")
    except Exception:
        logger.exception("Failed to start Kafka consumer — continuing without it")

    yield

    # Shutdown
    await health_consumer.stop()
    if consumer_task:
        consumer_task.cancel()


app = FastAPI(title="Actions API", version="0.2.0", lifespan=lifespan)


# --- Middleware: metrics ---
@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    duration = time.time() - start
    endpoint = request.url.path
    if not endpoint.startswith("/metrics"):
        API_REQUESTS.labels(
            method=request.method, endpoint=endpoint, status=response.status_code
        ).inc()
        API_REQUEST_DURATION.labels(
            method=request.method, endpoint=endpoint
        ).observe(duration)
    return response


# --- Endpoints ---


@app.get("/")
async def root(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Action))
    count = len(result.scalars().all())
    return {
        "service": "actions-api",
        "version": "0.2.0",
        "status": "running",
        "uptime_seconds": round(time.time() - _start_time, 1),
        "action_count": count,
    }


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/metrics")
async def metrics():
    return PlainTextResponse(generate_latest(), media_type="text/plain")


@app.post("/actions", response_model=ActionResponse)
async def execute_action(
    body: ActionRequest,
    x_user_team: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
):
    # 1. Validate entity exists in SSOT
    entity = await ssot_client.get_entity(body.entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail=f"Entity {body.entity_id} not found in SSOT")

    # 2. RBAC check (fail-closed)
    allowed, rbac_reason = await rbac.check_permission(
        user=body.user, user_team=x_user_team, entity_id=body.entity_id, action_type=body.action_type
    )
    if not allowed:
        raise HTTPException(status_code=403, detail=rbac_reason)

    # 3. Parse entity_id: k8s:{cluster}:{namespace}:{kind}:{name}
    parts = body.entity_id.split(":")
    if len(parts) != 5:
        raise HTTPException(status_code=400, detail=f"Invalid entity_id format: {body.entity_id}")

    _, cluster, namespace, kind, name = parts

    if kind != "Deployment":
        raise HTTPException(status_code=400, detail="Only Deployment targets supported")

    # 4. Auto-populate correlation_id from current recommendation
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

    # 5. Execute action
    action_id = str(uuid.uuid4())
    status = "pending"
    result_message = None
    completed_at = None

    start = time.time()
    try:
        if body.action_type == "restart_deployment":
            result_message = await k8s_client.restart_deployment(name, namespace)
            status = "success"
        elif body.action_type == "scale_deployment":
            replicas = body.parameters.get("replicas")
            if replicas is None:
                raise HTTPException(
                    status_code=400, detail="scale_deployment requires 'replicas' in parameters"
                )
            result_message = await k8s_client.scale_deployment(name, namespace, int(replicas))
            status = "success"
        else:
            raise HTTPException(status_code=400, detail=f"Unknown action_type: {body.action_type}")

        completed_at = datetime.now(timezone.utc)
    except ValueError as e:
        status = "failure"
        result_message = str(e)
    except RuntimeError as e:
        status = "failure"
        result_message = str(e)
    finally:
        duration = time.time() - start
        ACTIONS_EXECUTED.labels(action_type=body.action_type, status=status).inc()
        ACTIONS_EXECUTION_DURATION.labels(action_type=body.action_type).observe(duration)

    # 6. Record in audit DB
    action = Action(
        id=action_id,
        entity_id=body.entity_id,
        entity_type=kind,
        entity_name=name,
        namespace=namespace,
        action_type=body.action_type,
        user_id=body.user,
        user_team=x_user_team,
        parameters=body.parameters,
        reason=body.reason,
        status=status,
        result_message=result_message,
        correlation_id=correlation_id,
        completed_at=completed_at,
    )
    db.add(action)
    await db.commit()

    logger.info(
        "Action executed: id=%s type=%s entity=%s user=%s status=%s correlation=%s",
        action_id, body.action_type, body.entity_id, body.user, status, correlation_id,
    )

    return ActionResponse(
        action_id=action_id,
        status=status,
        result_message=result_message,
        completed_at=completed_at,
    )


@app.get("/recommendations", response_model=list[RecommendationResponse])
async def list_recommendations(
    entity_id: str | None = None,
    health_state: str | None = None,
    entity_type: str | None = None,
    owner_team: str | None = None,
    db: AsyncSession = Depends(get_db),
):
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


@app.get("/actions", response_model=list[ActionDetail])
async def list_actions(
    entity_id: str | None = None,
    user: str | None = None,
    status: str | None = None,
    action_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    query = select(Action)
    if entity_id:
        query = query.where(Action.entity_id == entity_id)
    if user:
        query = query.where(Action.user_id == user)
    if status:
        query = query.where(Action.status == status)
    if action_type:
        query = query.where(Action.action_type == action_type)
    query = query.order_by(Action.created_at.desc()).offset(offset).limit(limit)

    result = await db.execute(query)
    return result.scalars().all()


@app.get("/actions/{action_id}", response_model=ActionDetail)
async def get_action(action_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Action).where(Action.id == action_id))
    action = result.scalar_one_or_none()
    if action is None:
        raise HTTPException(status_code=404, detail=f"Action {action_id} not found")
    return action
