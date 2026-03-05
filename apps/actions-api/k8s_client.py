import asyncio
import logging
from datetime import datetime, timezone

from kubernetes import client, config as k8s_config
from kubernetes.client.exceptions import ApiException

from config import K8S_IN_CLUSTER, MAX_SCALE_REPLICAS, MIN_SCALE_REPLICAS

logger = logging.getLogger(__name__)


class K8sClient:
    def __init__(self):
        if K8S_IN_CLUSTER:
            k8s_config.load_incluster_config()
        else:
            k8s_config.load_kube_config()
        self.apps_v1 = client.AppsV1Api()

    async def restart_deployment(self, name: str, namespace: str) -> str:
        body = {
            "spec": {
                "template": {
                    "metadata": {
                        "annotations": {
                            "kubectl.kubernetes.io/restartedAt": datetime.now(timezone.utc).isoformat()
                        }
                    }
                }
            }
        }
        try:
            await asyncio.to_thread(
                self.apps_v1.patch_namespaced_deployment, name, namespace, body
            )
            logger.info("Restarted deployment %s in namespace %s", name, namespace)
            return f"Rollout restart initiated for deployment {name} in namespace {namespace}"
        except ApiException as e:
            if e.status == 404:
                raise ValueError(f"Deployment {name} not found in namespace {namespace}")
            raise RuntimeError(f"K8s API error restarting {name}: {e.reason}")

    async def scale_deployment(self, name: str, namespace: str, replicas: int) -> str:
        if replicas < MIN_SCALE_REPLICAS or replicas > MAX_SCALE_REPLICAS:
            raise ValueError(
                f"Replicas {replicas} out of bounds [{MIN_SCALE_REPLICAS}, {MAX_SCALE_REPLICAS}]"
            )

        # Get current replica count
        try:
            deployment = await asyncio.to_thread(
                self.apps_v1.read_namespaced_deployment, name, namespace
            )
            old_replicas = deployment.spec.replicas or 1
        except ApiException as e:
            if e.status == 404:
                raise ValueError(f"Deployment {name} not found in namespace {namespace}")
            raise RuntimeError(f"K8s API error reading {name}: {e.reason}")

        body = {"spec": {"replicas": replicas}}
        try:
            await asyncio.to_thread(
                self.apps_v1.patch_namespaced_deployment_scale, name, namespace, body
            )
            logger.info(
                "Scaled deployment %s in namespace %s: %d → %d",
                name, namespace, old_replicas, replicas,
            )
            return f"Scaled deployment {name} in namespace {namespace}: {old_replicas} → {replicas} replicas"
        except ApiException as e:
            raise RuntimeError(f"K8s API error scaling {name}: {e.reason}")

    async def pause_rollout(self, name: str, namespace: str) -> str:
        """Pause deployment rollout progression."""
        body = {"spec": {"paused": True}}
        try:
            await asyncio.to_thread(
                self.apps_v1.patch_namespaced_deployment, name, namespace, body
            )
            logger.info("Paused rollout for deployment %s in namespace %s", name, namespace)
            return f"Rollout paused for deployment {name} in namespace {namespace}"
        except ApiException as e:
            if e.status == 404:
                raise ValueError(f"Deployment {name} not found in namespace {namespace}")
            raise RuntimeError(f"K8s API error pausing {name}: {e.reason}")

    async def resume_rollout(self, name: str, namespace: str) -> str:
        """Resume a paused deployment rollout."""
        body = {"spec": {"paused": False}}
        try:
            await asyncio.to_thread(
                self.apps_v1.patch_namespaced_deployment, name, namespace, body
            )
            logger.info("Resumed rollout for deployment %s in namespace %s", name, namespace)
            return f"Rollout resumed for deployment {name} in namespace {namespace}"
        except ApiException as e:
            if e.status == 404:
                raise ValueError(f"Deployment {name} not found in namespace {namespace}")
            raise RuntimeError(f"K8s API error resuming {name}: {e.reason}")

    async def get_deployment_status(self, name: str, namespace: str) -> dict:
        try:
            deployment = await asyncio.to_thread(
                self.apps_v1.read_namespaced_deployment, name, namespace
            )
            return {
                "name": deployment.metadata.name,
                "namespace": deployment.metadata.namespace,
                "replicas": deployment.spec.replicas,
                "available_replicas": deployment.status.available_replicas or 0,
                "ready_replicas": deployment.status.ready_replicas or 0,
            }
        except ApiException as e:
            if e.status == 404:
                return None
            raise RuntimeError(f"K8s API error reading {name}: {e.reason}")
