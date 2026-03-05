import pytest
import httpx

pytestmark = pytest.mark.sprint3

OPS_UI = "http://192.168.1.210:31080"


class TestOpsUIStaticFiles:
    """Verify Nginx serves all static files."""

    def test_index_page_loads(self):
        r = httpx.get(f"{OPS_UI}/")
        assert r.status_code == 200
        assert "Health Overview" in r.text

    def test_entity_page_loads(self):
        r = httpx.get(f"{OPS_UI}/entity.html")
        assert r.status_code == 200
        assert "Entity Detail" in r.text

    @pytest.mark.parametrize("path", [
        "/css/styles.css",
        "/js/config.js",
        "/js/api.js",
        "/js/app.js",
    ])
    def test_static_asset(self, path):
        r = httpx.get(f"{OPS_UI}{path}")
        assert r.status_code == 200, f"Failed to load {path}"


class TestOpsUIProxy:
    """Verify Nginx reverse proxy to backend APIs."""

    def test_proxy_actions_api(self):
        r = httpx.get(f"{OPS_UI}/proxy/actions/health")
        assert r.status_code == 200

    def test_proxy_actions_list(self):
        r = httpx.get(f"{OPS_UI}/proxy/actions/actions?limit=5")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_proxy_ssot_entities(self):
        r = httpx.get(f"{OPS_UI}/proxy/ssot/entities")
        assert r.status_code == 200

    def test_proxy_recommendations(self):
        r = httpx.get(f"{OPS_UI}/proxy/actions/recommendations")
        assert r.status_code == 200
        assert isinstance(r.json(), list)
