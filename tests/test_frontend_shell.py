from pathlib import Path
import os

os.environ["GITHUB_ACTIONS"] = "true"

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_root_redirects_to_ui():
    response = client.get("/", follow_redirects=False)
    assert response.status_code in {302, 307}
    assert response.headers["location"] == "/ui/"



def test_frontend_shell_is_served_and_safe():
    response = client.get("/ui/")
    assert response.status_code == 200
    assert response.headers.get("cache-control") == "no-store, max-age=0"
    assert response.headers.get("x-frame-options") == "DENY"
    assert "default-src 'self'" in response.headers.get("content-security-policy", "")
    assert "Panel de memoria" in response.text
    assert "/memories/search" not in response.text
    assert "Conectar proveedor" in response.text
    assert "localStorage" not in response.text
    assert "sessionStorage" not in response.text
    assert "ver memoria" not in response.text.lower()



def test_frontend_assets_do_not_expose_sensitive_client_behaviors():
    js = client.get("/ui/app.js")
    assert js.status_code == 200
    body = js.text
    assert "localStorage" not in body
    assert "sessionStorage" not in body
    assert "console.log" not in body
    assert "console.error" not in body
    assert "AbortController" in body
    assert "#/dashboard" in body
    assert "request_timeout" in body
    assert "session_expired" in body

    css = client.get("/ui/styles.css")
    assert css.status_code == 200
    assert 'status-chip[data-variant="error"]' in css.text



def test_provider_catalog_public_endpoint():
    response = client.get("/connection/providers")
    assert response.status_code == 200
    body = response.json()
    providers = {item["provider"]: item for item in body["providers"]}
    assert "chatgpt" in providers
    assert providers["chatgpt"]["requires_user_api_key"] is False
    assert providers["claude"]["supports_mcp"] is True


def test_frontend_exposes_connector_url_fields():
    html = (Path("frontend") / "index.html").read_text(encoding="utf-8")
    assert "mcpConnectorUrl" in html
    assert "toolCallingManifestUrl" in html
    assert "toolCallingCallUrl" in html
