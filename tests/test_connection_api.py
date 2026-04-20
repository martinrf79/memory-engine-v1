import os

os.environ["GITHUB_ACTIONS"] = "true"

from fastapi.testclient import TestClient

from app.firestore_store import (
    audit_events_collection,
    chat_events_collection,
    llm_connections_collection,
    memory_indexes_collection,
    memory_keys_collection,
    projects_collection,
    semantic_collection,
    sessions_collection,
    support_events_collection,
    users_collection,
)
from app.main import app

client = TestClient(app)


def _clear_all():
    for collection in [
        audit_events_collection,
        chat_events_collection,
        llm_connections_collection,
        memory_indexes_collection,
        memory_keys_collection,
        projects_collection,
        semantic_collection,
        sessions_collection,
        support_events_collection,
        users_collection,
    ]:
        collection.clear()


def _register_and_login(test_client: TestClient, user_id: str = "martin", project: str = "memoria-guia"):
    response = test_client.post(
        "/auth/register",
        json={"user_id": user_id, "password": "clave-segura-123", "project": project},
    )
    assert response.status_code == 200
    return response



def test_connection_lifecycle_and_panel_with_session():
    _clear_all()
    _register_and_login(client)

    default_status = client.get("/connection/status")
    assert default_status.status_code == 200
    assert default_status.json()["provider"] == "mock"

    connected = client.post(
        "/connection/connect",
        json={"user_id": "martin", "provider": "chatgpt", "project": "memoria-guia"},
    )
    assert connected.status_code == 200
    body = connected.json()
    assert body["provider"] == "chatgpt"
    assert body["bridge_mode"] == "mcp"
    assert body["requires_user_api_key"] is False

    panel = client.get("/panel/me")
    assert panel.status_code == 200
    panel_body = panel.json()
    assert panel_body["panel_mode"] == "public_frontend_private_backend"
    assert panel_body["connection"]["provider"] == "chatgpt"

    bootstrap = client.get("/panel/bootstrap")
    assert bootstrap.status_code == 200
    bootstrap_body = bootstrap.json()
    assert bootstrap_body["me"]["user_id"] == "martin"
    assert any(item["project"] == "memoria-guia" for item in bootstrap_body["projects"])
    assert any(item["provider"] == "chatgpt" for item in bootstrap_body["providers"])

    paused = client.post("/connection/pause")
    assert paused.status_code == 200
    assert paused.json()["status"] == "paused"

    resumed = client.post("/connection/resume")
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "connected"

    disconnected = client.post("/connection/disconnect")
    assert disconnected.status_code == 200
    assert disconnected.json()["provider"] == "mock"



def test_connection_and_panel_require_session():
    _clear_all()
    status = client.get("/connection/status")
    assert status.status_code == 401

    panel = client.get("/panel/me")
    assert panel.status_code == 401

    connect = client.post(
        "/connection/connect",
        json={"user_id": "martin", "provider": "chatgpt", "project": "memoria-guia"},
    )
    assert connect.status_code == 401



def test_admin_and_docs_are_closed_in_product_mode_and_internal_routes_stay_off_schema():
    _clear_all()

    metrics = client.get("/admin/metrics")
    assert metrics.status_code in {403, 404}

    docs = client.get("/docs")
    assert docs.status_code == 404

    openapi = client.get("/openapi.json")
    assert openapi.status_code == 404
