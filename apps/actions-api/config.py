import os

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://actions:actions-secret-pw@postgres.actions.svc.cluster.local:5432/actions",
)
SSOT_API_URL = os.getenv("SSOT_API_URL", "http://ssot-api.ssot:8080")
K8S_IN_CLUSTER = os.getenv("K8S_IN_CLUSTER", "true").lower() == "true"
MAX_SCALE_REPLICAS = int(os.getenv("MAX_SCALE_REPLICAS", "10"))
MIN_SCALE_REPLICAS = int(os.getenv("MIN_SCALE_REPLICAS", "0"))

# Kafka config
KAFKA_BOOTSTRAP_SERVERS = os.getenv(
    "KAFKA_BOOTSTRAP_SERVERS",
    "kafka.calculator.svc.cluster.local:9092",
)
KAFKA_TOPIC = os.getenv("KAFKA_TOPIC", "health.transition.v1")
KAFKA_CONSUMER_GROUP = os.getenv("KAFKA_CONSUMER_GROUP", "actions-consumer-group")
