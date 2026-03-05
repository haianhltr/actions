import logging

import httpx

from config import SSOT_API_URL

logger = logging.getLogger(__name__)

_client = httpx.AsyncClient(base_url=SSOT_API_URL, timeout=10.0)


async def get_entity(entity_id: str) -> dict | None:
    try:
        r = await _client.get(f"/entities/{entity_id}")
        if r.status_code == 200:
            return r.json()
        if r.status_code == 404:
            return None
        logger.warning("SSOT get_entity %s returned %d", entity_id, r.status_code)
        return None
    except httpx.HTTPError as e:
        logger.error("SSOT get_entity %s failed: %s", entity_id, e)
        return None


async def get_ownership(entity_id: str) -> dict | None:
    try:
        r = await _client.get(f"/ownership/{entity_id}")
        if r.status_code == 200:
            return r.json()
        if r.status_code == 404:
            return None
        logger.warning("SSOT get_ownership %s returned %d", entity_id, r.status_code)
        return None
    except httpx.HTTPError as e:
        logger.error("SSOT get_ownership %s failed: %s", entity_id, e)
        return None


async def get_health_summary(entity_id: str) -> dict | None:
    try:
        r = await _client.get(f"/health_summary/{entity_id}")
        if r.status_code == 200:
            return r.json()
        if r.status_code == 404:
            return None
        logger.warning("SSOT get_health_summary %s returned %d", entity_id, r.status_code)
        return None
    except httpx.HTTPError as e:
        logger.error("SSOT get_health_summary %s failed: %s", entity_id, e)
        return None
