"""
Shared fixtures for Actions E2E tests.

Usage:
    # Against k3s on 5560 (default):
    pytest tests/e2e/ -v

    # Against local:
    ACTIONS_API_URL=http://localhost:8080 pytest tests/e2e/ -v
"""

import os

import httpx
import pytest

ACTIONS_API_URL = os.environ.get("ACTIONS_API_URL", "http://192.168.1.210:31000")
SSOT_API_URL = os.environ.get("SSOT_API_URL", "http://192.168.1.210:30900")


@pytest.fixture(scope="session")
def client():
    """HTTP client pointed at the Actions API."""
    with httpx.Client(base_url=ACTIONS_API_URL, timeout=30) as c:
        yield c


@pytest.fixture(scope="session")
def ssot_client():
    """HTTP client pointed at the SSOT API (for health/ownership context)."""
    with httpx.Client(base_url=SSOT_API_URL, timeout=10) as c:
        yield c
